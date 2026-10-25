import csv
import dataclasses
import io
import unittest

from csv_contract_check import (
    Column,
    Schema,
    SchemaError,
    load_schema,
    parse_schema,
    validate_csv,
)


def schema_for(type_name="string", required=False, **options):
    return parse_schema({
        "version": 1,
        "columns": [{"name": "value", "type": type_name, "required": required}],
        **options,
    })


def check_cell(value, type_name, required=False):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["value"])
    writer.writerow([value])
    stream.seek(0)
    return validate_csv(stream, schema_for(type_name, required))


class SchemaTests(unittest.TestCase):
    def test_defaults_and_immutability(self):
        schema = parse_schema({"version": 1, "columns": [{"name": "x", "type": "string"}]})
        self.assertFalse(schema.allow_extra_columns)
        self.assertFalse(schema.columns[0].required)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            schema.allow_extra_columns = True
        with self.assertRaises(dataclasses.FrozenInstanceError):
            schema.columns[0].name = "other"

    def test_rejects_wrong_root_shapes_and_versions(self):
        cases = [None, [], "object", 1, {}, {"columns": []}]
        for version in (None, True, False, "1", 1.0, 0, 2):
            cases.append({"version": version, "columns": [{"name": "x", "type": "string"}]})
        for value in cases:
            with self.subTest(value=value), self.assertRaises(SchemaError):
                parse_schema(value)

    def test_rejects_bad_columns(self):
        cases = [None, {}, [], "x", [None], [{}], [{"name": "x"}], [{"type": "string"}]]
        for name in (None, 1, "", []):
            cases.append([{"name": name, "type": "string"}])
        for type_name in (None, 1, [], "date", "INTEGER"):
            cases.append([{"name": "x", "type": type_name}])
        for required in (None, 0, 1, "false", []):
            cases.append([{"name": "x", "type": "string", "required": required}])
        for columns in cases:
            with self.subTest(columns=columns), self.assertRaises(SchemaError):
                parse_schema({"version": 1, "columns": columns})

    def test_rejects_duplicate_names(self):
        with self.assertRaisesRegex(SchemaError, "duplicate column name"):
            parse_schema({"version": 1, "columns": [
                {"name": "x", "type": "integer"}, {"name": "x", "type": "string"},
            ]})

    def test_rejects_unknown_properties_and_nonboolean_extra(self):
        cases = [
            {"version": 1, "columns": [{"name": "x", "type": "string"}], "additional": False},
            {"version": 1, "columns": [{"name": "x", "type": "string", "require": True}]},
            {"version": 1, "columns": [{"name": "x", "type": "string"}], "allow_extra_columns": 1},
        ]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(SchemaError):
                parse_schema(value)

    def test_json_rejects_duplicates_at_each_depth(self):
        cases = [
            '{"version":1,"version":1,"columns":[{"name":"x","type":"string"}]}',
            '{"version":1,"columns":[{"name":"x","type":"string","type":"integer"}]}',
        ]
        for source in cases:
            with self.subTest(source=source), self.assertRaisesRegex(SchemaError, "duplicate JSON"):
                load_schema(io.StringIO(source))

    def test_rejects_invalid_and_nonstandard_json(self):
        for source in ("", "{", '{"version":1,}', "NaN", "Infinity", "-Infinity"):
            with self.subTest(source=source), self.assertRaises(SchemaError):
                load_schema(io.StringIO(source))

    def test_loads_valid_json(self):
        result = load_schema(io.StringIO('{"version":1,"columns":[{"name":"x","type":"boolean"}]}'))
        self.assertEqual(result.columns, (Column("x", "boolean"),))

    def test_direct_construction_preserves_validated_immutable_shape(self):
        for columns in ([], (), ("x",), (Column("x", "string"), Column("x", "number"))):
            with self.subTest(columns=columns), self.assertRaises(SchemaError):
                Schema(columns)

    def test_decoding_errors_are_not_reclassified_as_schema_errors(self):
        with io.TextIOWrapper(io.BytesIO(b"\xff"), encoding="utf-8") as stream:
            with self.assertRaises(UnicodeDecodeError):
                load_schema(stream)


class CellTests(unittest.TestCase):
    def test_strings_preserve_spaces_unicode_quotes_and_newlines(self):
        for value in (" ", "  padded  ", "José", 'comma, and "quote"', "two\nlines"):
            with self.subTest(value=value):
                self.assertTrue(check_cell(value, "string", True).valid)

    def test_optional_empty_is_valid_for_every_type(self):
        for type_name in ("string", "integer", "number", "boolean"):
            with self.subTest(type_name=type_name):
                self.assertTrue(check_cell("", type_name).valid)

    def test_required_empty_has_one_required_error(self):
        for type_name in ("string", "integer", "number", "boolean"):
            with self.subTest(type_name=type_name):
                result = check_cell("", type_name, True)
                self.assertEqual([(error.code, error.line, error.column) for error in result.errors],
                                 [("required_value", 2, "value")])

    def test_integer_accepted_forms(self):
        for value in ("0", "-0", "+0", "01", "-42", "+12", "9" * 5000):
            with self.subTest(value=value[:30]):
                self.assertTrue(check_cell(value, "integer").valid)

    def test_integer_rejected_forms(self):
        for value in (" 1", "1 ", "1.0", "1e3", "1_000", "١", "１２", "+", "--1"):
            with self.subTest(value=value):
                self.assertEqual(check_cell(value, "integer").errors[0].code, "invalid_type")

    def test_numbers_accept_finite_decimal_forms_without_float_overflow(self):
        for value in ("1", "+1", "-01", ".5", "1.", "-.25", "1.2e+5", "1e9999", "1e-9999"):
            with self.subTest(value=value):
                self.assertTrue(check_cell(value, "number").valid)

    def test_numbers_reject_nonfinite_and_other_syntax(self):
        for value in ("NaN", "nan", "sNaN", "Infinity", "-Infinity", "+inf", "INF", "∞", "0x10",
                      "1_000", "1,25", " 2", "2 ", ".", "1e", "1e+", "١.٢"):
            with self.subTest(value=value):
                self.assertEqual(check_cell(value, "number").errors[0].code, "invalid_type")

    def test_unrepresentable_decimal_exponent_is_a_data_error(self):
        result = check_cell("1e" + "9" * 80, "number")
        self.assertEqual(result.errors[0].code, "invalid_type")

    def test_booleans_are_exact(self):
        for value in ("true", "false"):
            with self.subTest(value=value):
                self.assertTrue(check_cell(value, "boolean").valid)
        for value in ("TRUE", "False", "1", "0", "yes", " true", "false "):
            with self.subTest(value=value):
                self.assertFalse(check_cell(value, "boolean").valid)


class CsvTests(unittest.TestCase):
    def test_quoted_commas_quotes_crlf_and_multiline_record_locations(self):
        schema = parse_schema({"version": 1, "columns": [
            {"name": "label", "type": "string"}, {"name": "count", "type": "integer"},
        ]})
        source = 'label,count\r\n"first, \"\"quoted\"\"",1\r\n"two\r\nlines",bad\r\nlast,no\r\n'
        result = validate_csv(io.StringIO(source, newline=""), schema)
        self.assertEqual(result.records_checked, 3)
        self.assertEqual([(error.code, error.line) for error in result.errors],
                         [("invalid_type", 3), ("invalid_type", 5)])

    def test_bom_before_quoted_header(self):
        result = validate_csv(io.StringIO('\ufeff"value"\nhello\n'), schema_for())
        self.assertTrue(result.valid)

    def test_empty_and_bom_only_inputs_have_missing_header(self):
        for source in ("", "\ufeff"):
            with self.subTest(source=source):
                result = validate_csv(io.StringIO(source), schema_for())
                self.assertEqual(result.errors[0].code, "missing_header")
                self.assertEqual(result.records_checked, 0)

    def test_blank_header_has_empty_and_missing_errors(self):
        result = validate_csv(io.StringIO("\nignored\n"), schema_for())
        self.assertEqual([error.code for error in result.errors], ["empty_header", "missing_column"])
        self.assertEqual(result.records_checked, 0)

    def test_header_errors_have_frozen_order_and_stop_record_validation(self):
        schema = parse_schema({"version": 1, "columns": [
            {"name": "id", "type": "integer"}, {"name": "name", "type": "string"},
        ]})
        result = validate_csv(io.StringIO('extra,,extra\n"unfinished'), schema)
        self.assertEqual([(error.code, error.column) for error in result.errors], [
            ("empty_header", None), ("duplicate_header", "extra"),
            ("missing_column", "id"), ("missing_column", "name"),
            ("unexpected_column", "extra"), ("unexpected_column", "extra"),
        ])
        self.assertEqual(result.records_checked, 0)

    def test_optional_columns_still_need_a_header(self):
        result = validate_csv(io.StringIO("other\nhello\n"), schema_for(allow_extra_columns=True))
        self.assertEqual([error.code for error in result.errors], ["missing_column"])

    def test_headers_are_exact_and_not_trimmed(self):
        for source in ("VALUE\nhello\n", " value\nhello\n", "value \nhello\n"):
            with self.subTest(source=source):
                result = validate_csv(io.StringIO(source), schema_for())
                self.assertEqual([error.code for error in result.errors], ["missing_column", "unexpected_column"])

    def test_header_order_is_independent_from_field_error_order(self):
        schema = parse_schema({"version": 1, "columns": [
            {"name": "a", "type": "integer"}, {"name": "b", "type": "boolean"},
        ]})
        result = validate_csv(io.StringIO("b,a\nyes,oops\n"), schema)
        self.assertEqual([error.column for error in result.errors], ["a", "b"])

    def test_allowed_extra_column_values_are_ignored_but_counted_for_width(self):
        result = validate_csv(io.StringIO("extra,value\nanything,ok\nmissing\n"),
                              schema_for(allow_extra_columns=True))
        self.assertEqual(result.records_checked, 2)
        self.assertEqual([(error.code, error.line) for error in result.errors], [("column_count", 3)])

    def test_extra_column_permission_never_allows_duplicate_headers(self):
        result = validate_csv(io.StringIO("value,x,x\n1,2,3\n"), schema_for(allow_extra_columns=True))
        self.assertEqual([error.code for error in result.errors], ["duplicate_header"])

    def test_header_only_is_valid(self):
        result = validate_csv(io.StringIO("value\n"), schema_for(required=True))
        self.assertEqual(result.to_dict(), {"valid": True, "records_checked": 0, "errors": []})

    def test_width_errors_skip_cells_and_count_blank_records(self):
        result = validate_csv(io.StringIO("value\nbad,extra\n\nno\n"), schema_for("integer", True))
        self.assertEqual(result.records_checked, 3)
        self.assertEqual([(error.code, error.line) for error in result.errors],
                         [("column_count", 2), ("column_count", 3), ("invalid_type", 4)])

    def test_unterminated_record_is_not_counted_and_uses_its_start_line(self):
        result = validate_csv(io.StringIO('value\nok\n"unfinished\nmore'), schema_for())
        self.assertEqual(result.records_checked, 1)
        self.assertEqual([(error.code, error.line) for error in result.errors], [("invalid_csv", 3)])

    def test_invalid_quote_closure_and_malformed_header(self):
        for source, expected_line in (('value\n"value"oops\n', 2), ('"value"oops\n', 1)):
            with self.subTest(source=source):
                result = validate_csv(io.StringIO(source), schema_for())
                self.assertEqual([(error.code, error.line) for error in result.errors], [("invalid_csv", expected_line)])
                self.assertEqual(result.records_checked, 0)

    def test_stdlib_field_size_limit_is_reported_without_global_mutation(self):
        original_limit = csv.field_size_limit()
        source = "value\n" + "x" * (original_limit + 1) + "\n"
        result = validate_csv(io.StringIO(source), schema_for())
        self.assertEqual(result.errors[0].code, "invalid_csv")
        self.assertEqual(csv.field_size_limit(), original_limit)

    def test_report_is_immutable_deterministic_and_does_not_expose_cell_values(self):
        source = "value\nprivate-cell-content\n"
        first = validate_csv(io.StringIO(source), schema_for("integer"))
        second = validate_csv(io.StringIO(source), schema_for("integer"))
        self.assertEqual(first, second)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            first.records_checked = 99
        self.assertNotIn("private-cell-content", str(first.to_dict()))
        self.assertEqual(set(first.to_dict()), {"valid", "records_checked", "errors"})
        self.assertEqual(set(first.errors[0].to_dict()), {"code", "line", "column", "message"})

    def test_io_errors_propagate_to_api_callers(self):
        class BrokenStream:
            def __iter__(self):
                raise OSError("test input failure")

        with self.assertRaises(OSError):
            validate_csv(BrokenStream(), schema_for())

    def test_wrong_schema_argument_is_rejected(self):
        with self.assertRaises(TypeError):
            validate_csv(io.StringIO("value\n"), {})


if __name__ == "__main__":
    unittest.main()
