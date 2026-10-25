# csv-contract-check

Check a CSV export against a small JSON contract before importing it into another
tool. The CLI reports missing or duplicate headers, row widths, empty required
cells, and invalid types, with physical line locations.

Python 3.10+. No runtime or test dependencies. No network access. MIT licensed.
[Português brasileiro](README.pt-BR.md).

## Run without installation

From this directory:

```sh
python3 -m csv_contract_check --schema examples/people.schema.json examples/valid.csv
# OK: 3 record(s) checked.

python3 -m csv_contract_check --schema examples/people.schema.json --format json examples/invalid.csv
# Exit status 1; JSON explains the invalid cells and incorrect row width.

cat examples/valid.csv | python3 -m csv_contract_check --schema examples/people.schema.json -
python3 -m csv_contract_check --help
```

An optional local installation exposes the `csv-contract-check` command:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/csv-contract-check --schema examples/people.schema.json examples/valid.csv
```

Installation uses setuptools as the build backend and may download build tools.
Running from source and running the tests require only Python's standard library.

## Contract format

This is a deliberately small contract format, **not JSON Schema**.

```json
{
  "version": 1,
  "allow_extra_columns": false,
  "columns": [
    {"name": "id", "type": "integer", "required": true},
    {"name": "name", "type": "string", "required": true},
    {"name": "active", "type": "boolean", "required": true},
    {"name": "score", "type": "number"}
  ]
}
```

`version` must be the integer `1`; `true` and `1.0` do not qualify. `columns` must
be a nonempty array. Each column needs a unique, nonempty string `name` and one of
the four types below. `required` defaults to `false`. `allow_extra_columns` also
defaults to `false`; both options must be JSON booleans.

Unknown properties, missing properties, duplicate JSON properties, duplicate
column names, unsupported versions/types, malformed JSON, and JSON NaN/Infinity
are schema errors. A schema error prevents CSV processing.

Every schema column must appear in the CSV header, even when `required` is false.
Header order can differ from schema order. With `allow_extra_columns: true`,
additional named columns are accepted and their cell values are ignored; their
fields still count toward the record width. Duplicate or unnamed header columns
are always rejected.

| Type | Accepted nonempty cell |
| --- | --- |
| `string` | Any text, including whitespace, Unicode, and quoted newlines |
| `integer` | ASCII digits with an optional `+` or `-`; leading zeros are allowed |
| `number` | A finite decimal with an optional sign and exponent; examples: `1`, `-2.5`, `.5`, `1.`, `+3e-2` |
| `boolean` | Exactly `true` or `false`, in lowercase |

An empty cell (`""`) is accepted for every optional type. A required empty cell
produces one `required_value` error. Whitespace is preserved, so a space satisfies
a required string but is invalid for the other types. Names and values are never
trimmed or case-folded. An entirely blank record has zero fields, which is
different from a quoted empty cell in a one-column CSV.

The exact integer grammar is `[+-]?[0-9]+`. The number grammar is
`[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?`, checked using a
finite `decimal.Decimal`, without converting to a float. Thus `1e9999` is valid,
while NaN, Infinity, hex, underscores, Unicode digits, decimal commas, and padded
numbers are invalid. A decimal exponent outside the interpreter's Decimal
representation is also rejected.

## Reports and exit codes

```sh
python3 -m csv_contract_check --schema examples/people.schema.json --format json examples/invalid.csv
```

The JSON report contains exactly three keys:

```json
{
  "valid": false,
  "records_checked": 1,
  "errors": [
    {"code": "invalid_type", "line": 2, "column": "id", "message": "expected integer"}
  ]
}
```

This shortened illustration shows one error; the actual example reports all five.
Reports omit cell values. Header names appear in the `column` field and may appear
in schema error messages. JSON output is one object followed by a newline.

| Exit | Meaning |
| --- | --- |
| `0` | The CSV matches the contract |
| `1` | Invalid header, CSV syntax, field count, required cell, or type |
| `2` | Invalid schema, unreadable input, invalid UTF-8, or incorrect CLI usage |

Validation and input error reports go to stdout in the chosen format. CLI usage
errors use argparse's text on stderr, including when `--format json` is requested.
`--help` and `--version` exit successfully without reading inputs.

Error codes are `missing_header`, `empty_header`, `duplicate_header`,
`missing_column`, `unexpected_column`, `column_count`, `required_value`,
`invalid_type`, `invalid_csv`, `invalid_schema`, `invalid_encoding`, and `io_error`.
Every error has `code`, `line`, `column`, and `message`. Input-level errors use null
for both location fields. For stable integrations, inspect codes and locations;
stdlib CSV/JSON diagnostic wording can vary by Python version.

For identical inputs on the same Python version, output is deterministic:

1. Header problems: empty/duplicate names in header order, missing names in schema
   order, then unexpected names in header order. Any header problem stops record
   checks and leaves `records_checked` at zero.
2. Record problems: input order, then schema column order. An incorrect field
   count produces one error and skips that record's field checks.
3. Malformed CSV stops parsing; its incomplete record is not counted. Previously
   completed records, including blank and incorrect-width records, are counted.

## CSV details and limits

Input files and stdin use UTF-8, with an optional BOM. CSV uses comma separators,
double-quoted fields, doubled quote escaping, LF or CRLF, and Python's strict
`csv.reader` Excel dialect. Quoted commas and multiline fields work. A line number
identifies the **first physical line** of a record, including a malformed record.
The header starts at line 1 and can itself contain quoted multiline names.

A conforming header-only file is valid; an empty file has no header and fails.
There is no row-count rule, date inference, locale guessing, coercion, output file,
or configurable dialect. This validator checks CSV structure and this contract;
it does not sanitize spreadsheet formulas or prove that data is correct.

Input streams are processed record by record, but all errors are retained in
memory until reporting. Python's current `csv.field_size_limit()` applies (normally
131,072 characters); crossing it yields `invalid_csv`. The library does not change
that process-wide setting. The JSON schema is read into memory. This tool is
intended for ordinary exports, not adversarial inputs requiring resource limits.

## Python API

```python
from csv_contract_check import load_schema, validate_csv

with open("examples/people.schema.json", encoding="utf-8-sig") as stream:
    schema = load_schema(stream)

with open("examples/valid.csv", encoding="utf-8", newline="") as stream:
    result = validate_csv(stream, schema)

assert result.valid
print(result.records_checked)
print(result.to_dict())
```

`parse_schema(decoded_object)` is available for an already decoded JSON object;
use `load_schema(text_stream)` when duplicate JSON properties must be detected.
Both return an immutable `Schema` or raise `SchemaError`. Schemas contain a tuple
of immutable `Column` objects.

`validate_csv(text_stream, schema)` consumes the decoded text stream and returns
an immutable `ValidationResult` with `.valid`, `.records_checked`, `.errors`, and
`.to_dict()`. Each error is an immutable `ValidationError`. CSV validation problems
are returned as errors; input I/O and Unicode decoding exceptions propagate to API
callers. The CLI converts those input exceptions to exit-2 reports.

## Development

```sh
python3 -B -m unittest discover -s tests -v
```

Tests use synthetic data and only the standard library. CI runs Python 3.10–3.14
with repository contents read permission. No test needs a network connection.
An additional Ubuntu job stages only tracked public files under `/tmp` with
`git archive`, using traversable staging directories for user namespaces,
then runs the suite inside bubblewrap: read-only source, an empty home, a cleared
environment, no external network interfaces, zero Linux capabilities, and
`NoNewPrivs=1`. It verifies those properties and compares source hashes before and
after the run. Checkout metadata and runner credentials are not mounted.

For a clean source copy on Linux with bubblewrap already available:

```sh
python3 -B scripts/test_isolated.py /path/to/clean/source-copy
```

The isolation helper does not install anything or request sudo locally. In CI,
if bubblewrap is absent, its system package is downloaded and extracted in a
temporary folder without installing it. If AppArmor or namespace restrictions
block unprivileged bubblewrap, the workflow permits sudo for the bubblewrap
process only on the ephemeral GitHub-hosted runner. It does not change system
security policies. The tests themselves still run with no capabilities and no
new privileges. A local machine with blocked user namespaces must use the regular
unittest command or an administrator-provided isolated environment.

Contributions should include a small synthetic failing case, document any format
change, and preserve deterministic error order. Do not include real exports or
credentials in bug reports.

Copyright 2026 Martin Lofrano de Oliveira. See [LICENSE](LICENSE).
