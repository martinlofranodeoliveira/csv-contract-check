"""Command-line interface and input/output handling."""

from __future__ import annotations

import argparse
import io
import json
import sys
from contextlib import ExitStack, contextmanager
from typing import Iterator, TextIO

from . import __version__
from .core import SchemaError, ValidationError, ValidationResult, load_schema, validate_csv


@contextmanager
def _stdin_utf8() -> Iterator[TextIO]:
    binary = getattr(sys.stdin, "buffer", None)
    if binary is None:
        # Also permits a StringIO when embedding main() in a Python program.
        yield sys.stdin
        return
    wrapper = io.TextIOWrapper(binary, encoding="utf-8", errors="strict", newline="")
    try:
        yield wrapper
    finally:
        wrapper.detach()


def _print_report(result: ValidationResult, report_format: str) -> None:
    if report_format == "json":
        print(json.dumps(result.to_dict(), ensure_ascii=False, allow_nan=False))
        return
    if result.valid:
        print(f"OK: {result.records_checked} record(s) checked.")
        return
    for error in result.errors:
        location = f"line {error.line}" if error.line is not None else "input"
        if error.column is not None:
            location += f", column {error.column!r}"
        print(f"{location}: {error.message} [{error.code}]")
    print(f"FAIL: {len(result.errors)} error(s); {result.records_checked} record(s) checked.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="csv-contract-check", description="Validate UTF-8 CSV against a JSON contract, offline."
    )
    parser.add_argument("--schema", required=True, metavar="SCHEMA.json", help="version-1 JSON contract")
    parser.add_argument("--format", choices=("text", "json"), default="text", help="report format (default: text)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("csv", metavar="CSV", help="CSV path, or - for UTF-8 standard input")
    args = parser.parse_args(argv)
    exit_code = 2
    try:
        with ExitStack() as stack:
            schema_stream = stack.enter_context(open(args.schema, encoding="utf-8-sig"))
            schema = load_schema(schema_stream)
            if args.csv == "-":
                csv_stream = stack.enter_context(_stdin_utf8())
            else:
                csv_stream = stack.enter_context(open(args.csv, encoding="utf-8", newline=""))
            result = validate_csv(csv_stream, schema)
            exit_code = 0 if result.valid else 1
    except SchemaError as error:
        result = ValidationResult(0, (ValidationError("invalid_schema", None, None, str(error)),))
    except UnicodeError:
        result = ValidationResult(
            0, (ValidationError("invalid_encoding", None, None, "input must be valid UTF-8"),)
        )
    except OSError as error:
        message = error.strerror or type(error).__name__
        result = ValidationResult(0, (ValidationError("io_error", None, None, f"cannot read input: {message}"),))
    _print_report(result, args.format)
    return exit_code
