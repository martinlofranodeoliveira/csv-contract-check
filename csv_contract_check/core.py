"""The schema and validation API; no filesystem or network access."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from decimal import Decimal, DecimalException
from typing import Iterator, TextIO


_TYPES = frozenset({"string", "integer", "number", "boolean"})
_INTEGER = re.compile(r"[+-]?[0-9]+")
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


class SchemaError(ValueError):
    """The contract is not a supported, unambiguous version-1 schema."""


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    required: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise SchemaError("column name must be a nonempty string")
        if not isinstance(self.type, str) or self.type not in _TYPES:
            raise SchemaError(f"column {self.name!r}: unsupported type {self.type!r}")
        if not isinstance(self.required, bool):
            raise SchemaError(f"column {self.name!r}: required must be a boolean")


@dataclass(frozen=True)
class Schema:
    columns: tuple[Column, ...]
    allow_extra_columns: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.columns, tuple) or not self.columns:
            raise SchemaError("columns must be a nonempty tuple of Column objects")
        if not all(isinstance(column, Column) for column in self.columns):
            raise SchemaError("columns must contain Column objects")
        if not isinstance(self.allow_extra_columns, bool):
            raise SchemaError("allow_extra_columns must be a boolean")
        seen: set[str] = set()
        for column in self.columns:
            if column.name in seen:
                raise SchemaError(f"duplicate column name {column.name!r}")
            seen.add(column.name)


@dataclass(frozen=True)
class ValidationError:
    code: str
    line: int | None
    column: str | None
    message: str

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "line": self.line,
            "column": self.column,
            "message": self.message,
        }


@dataclass(frozen=True)
class ValidationResult:
    records_checked: int
    errors: tuple[ValidationError, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "records_checked": self.records_checked,
            "errors": [error.to_dict() for error in self.errors],
        }


def _reject_unknown(data: dict, allowed: set[str], location: str) -> None:
    unknown = sorted(data.keys() - allowed, key=repr)
    if unknown:
        names = ", ".join(repr(key) for key in unknown)
        raise SchemaError(f"{location}: unknown properties: {names}")


def parse_schema(data: object) -> Schema:
    """Validate a decoded JSON object and return an immutable schema.

    Every named column must be present in the CSV header. ``required`` controls
    whether a cell may be empty, not whether the header may omit the column.
    """
    if not isinstance(data, dict):
        raise SchemaError("schema must be a JSON object")
    _reject_unknown(data, {"version", "columns", "allow_extra_columns"}, "schema")
    if type(data.get("version")) is not int or data["version"] != 1:
        raise SchemaError("version must be the integer 1")
    columns = data.get("columns")
    if not isinstance(columns, list) or not columns:
        raise SchemaError("columns must be a nonempty array")
    extra = data.get("allow_extra_columns", False)
    if not isinstance(extra, bool):
        raise SchemaError("allow_extra_columns must be a boolean")
    parsed: list[Column] = []
    for index, column in enumerate(columns, start=1):
        if not isinstance(column, dict):
            raise SchemaError(f"column {index} must be an object")
        _reject_unknown(column, {"name", "type", "required"}, f"column {index}")
        if "name" not in column or "type" not in column:
            raise SchemaError(f"column {index} must contain name and type")
        parsed.append(Column(column["name"], column["type"], column.get("required", False)))
    return Schema(tuple(parsed), extra)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SchemaError(f"duplicate JSON property {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise SchemaError(f"non-standard JSON number {value!r}")


def load_schema(stream: TextIO) -> Schema:
    """Read JSON from a decoded text stream; reject duplicate JSON properties."""
    try:
        data = json.load(
            stream, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
    except SchemaError:
        raise
    except UnicodeError:
        raise
    except (ValueError, RecursionError) as error:
        raise SchemaError(f"invalid JSON: {error}") from error
    return parse_schema(data)


def _without_bom(stream: TextIO) -> Iterator[str]:
    # Remove the BOM before csv.reader sees a possible opening quote.
    iterator = iter(stream)
    first = next(iterator, "")
    first = first.removeprefix("\ufeff")
    if first:
        yield first
    yield from iterator


def _header_errors(header: list[str], schema: Schema) -> list[ValidationError]:
    errors: list[ValidationError] = []
    seen: set[str] = set()
    if not header:
        errors.append(ValidationError("empty_header", 1, None, "header record is empty"))
    for position, name in enumerate(header, start=1):
        if not name:
            errors.append(
                ValidationError("empty_header", 1, None, f"header column {position} has no name")
            )
        elif name in seen:
            errors.append(
                ValidationError("duplicate_header", 1, name, "header name appears more than once")
            )
        seen.add(name)
    expected = {column.name for column in schema.columns}
    for column in schema.columns:
        if column.name not in seen:
            errors.append(
                ValidationError("missing_column", 1, column.name, "schema column is missing")
            )
    if not schema.allow_extra_columns:
        for name in header:
            if name and name not in expected:
                errors.append(
                    ValidationError("unexpected_column", 1, name, "column is not in the schema")
                )
    return errors


def _matches_type(value: str, type_name: str) -> bool:
    if type_name == "string":
        return True
    if type_name == "integer":
        return _INTEGER.fullmatch(value) is not None
    if type_name == "boolean":
        return value in ("true", "false")
    if _NUMBER.fullmatch(value) is None:
        return False
    try:
        return Decimal(value).is_finite()
    except DecimalException:
        return False


def validate_csv(stream: TextIO, schema: Schema) -> ValidationResult:
    """Check decoded CSV without changing the schema or writing any files.

    The stream is consumed. Errors use the first physical line of each record.
    A malformed or ambiguous header prevents validation of subsequent records.
    I/O and Unicode decoding errors propagate to the caller.
    """
    if not isinstance(schema, Schema):
        raise TypeError("schema must be a Schema returned by parse_schema or load_schema")
    reader = csv.reader(_without_bom(stream), strict=True)
    try:
        header = next(reader)
    except StopIteration:
        return ValidationResult(
            0, (ValidationError("missing_header", 1, None, "CSV has no header record"),)
        )
    except csv.Error as error:
        return ValidationResult(0, (ValidationError("invalid_csv", 1, None, str(error)),))
    errors = _header_errors(header, schema)
    if errors:
        return ValidationResult(0, tuple(errors))
    positions = {name: index for index, name in enumerate(header)}
    records_checked = 0
    while True:
        line = reader.line_num + 1
        try:
            record = next(reader)
        except StopIteration:
            break
        except csv.Error as error:
            errors.append(ValidationError("invalid_csv", line, None, str(error)))
            break
        records_checked += 1
        if len(record) != len(header):
            errors.append(
                ValidationError(
                    "column_count", line, None,
                    f"expected {len(header)} fields, got {len(record)}",
                )
            )
            continue
        for column in schema.columns:
            value = record[positions[column.name]]
            if value == "":
                if column.required:
                    errors.append(
                        ValidationError("required_value", line, column.name, "value is required")
                    )
            elif not _matches_type(value, column.type):
                errors.append(
                    ValidationError("invalid_type", line, column.name, f"expected {column.type}")
                )
    return ValidationResult(records_checked, tuple(errors))
