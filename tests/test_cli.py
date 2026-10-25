import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from csv_contract_check import __version__


ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="csv-contract-check-test-")
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.schema = self.folder / "schema.json"
        self.data = self.folder / "data.csv"
        self.schema.write_text('{"version":1,"columns":[{"name":"id","type":"integer","required":true}]}', encoding="utf-8")
        self.data.write_text("id\n1\n", encoding="utf-8")

    def run_cli(self, *args, input_bytes=None):
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONUTF8"] = "1"
        return subprocess.run(
            [sys.executable, "-B", "-m", "csv_contract_check", *map(str, args)],
            input=input_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=ROOT, env=environment, timeout=10, check=False,
        )

    def report(self, result):
        self.assertEqual(result.stderr, b"")
        self.assertTrue(result.stdout.endswith(b"\n"))
        self.assertNotIn(b"Traceback", result.stdout)
        return json.loads(result.stdout)

    def test_success_text(self):
        result = self.run_cli("--schema", self.schema, self.data)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"OK: 1 record(s) checked.\n")
        self.assertEqual(result.stderr, b"")

    def test_success_json(self):
        result = self.run_cli("--schema", self.schema, "--format", "json", self.data)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.report(result), {"valid": True, "records_checked": 1, "errors": []})

    def test_bad_cell_json_exit_one(self):
        self.data.write_text("id\nsecret-invalid-value\n", encoding="utf-8")
        result = self.run_cli("--schema", self.schema, "--format", "json", self.data)
        self.assertEqual(result.returncode, 1)
        report = self.report(result)
        self.assertFalse(report["valid"])
        self.assertEqual(report["errors"], [{"code": "invalid_type", "line": 2, "column": "id", "message": "expected integer"}])
        self.assertNotIn(b"secret-invalid-value", result.stdout)

    def test_bad_cell_text_and_deterministic_output(self):
        self.data.write_text("id\noops\n", encoding="utf-8")
        first = self.run_cli("--schema", self.schema, self.data)
        second = self.run_cli("--schema", self.schema, self.data)
        self.assertEqual(first.returncode, 1)
        self.assertEqual(first.stdout, second.stdout)
        self.assertIn(b"line 2, column 'id': expected integer [invalid_type]", first.stdout)

    def test_invalid_schema_exit_two(self):
        self.schema.write_text('{"version":true,"columns":[]}', encoding="utf-8")
        result = self.run_cli("--schema", self.schema, "--format", "json", self.data)
        self.assertEqual(result.returncode, 2)
        error = self.report(result)["errors"][0]
        self.assertEqual((error["code"], error["line"], error["column"]), ("invalid_schema", None, None))

    def test_duplicate_json_keys_rejected_through_cli(self):
        self.schema.write_text('{"version":1,"version":1,"columns":[]}', encoding="utf-8")
        result = self.run_cli("--schema", self.schema, "--format", "json", self.data)
        self.assertEqual(result.returncode, 2)
        self.assertIn("duplicate JSON", self.report(result)["errors"][0]["message"])

    def test_missing_schema_and_csv_are_io_errors(self):
        for schema, data in ((self.folder / "missing.json", self.data), (self.schema, self.folder / "missing.csv")):
            with self.subTest(schema=schema, data=data):
                result = self.run_cli("--schema", schema, "--format", "json", data)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(self.report(result)["errors"][0]["code"], "io_error")

    def test_invalid_utf8_in_either_file_is_a_decoding_error(self):
        for target in (self.schema, self.data):
            with self.subTest(target=target):
                original = target.read_bytes()
                target.write_bytes(b"\xff\xfe")
                result = self.run_cli("--schema", self.schema, "--format", "json", self.data)
                target.write_bytes(original)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(self.report(result)["errors"][0]["code"], "invalid_encoding")

    def test_utf8_bom_for_schema_and_quoted_csv_header(self):
        self.schema.write_bytes(b"\xef\xbb\xbf" + self.schema.read_bytes())
        self.data.write_bytes(b'\xef\xbb\xbf"id"\r\n7\r\n')
        result = self.run_cli("--schema", self.schema, "--format", "json", self.data)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(self.report(result)["valid"])

    def test_standard_input_with_bom(self):
        result = self.run_cli("--schema", self.schema, "--format", "json", "-", input_bytes=b'\xef\xbb\xbf"id"\n9\n')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.report(result)["records_checked"], 1)

    def test_standard_input_invalid_utf8(self):
        result = self.run_cli("--schema", self.schema, "--format", "json", "-", input_bytes=b"id\n\xff\n")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.report(result)["errors"][0]["code"], "invalid_encoding")

    def test_malformed_csv_is_data_error(self):
        self.data.write_text('id\n"unclosed\n', encoding="utf-8")
        result = self.run_cli("--schema", self.schema, "--format", "json", self.data)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.report(result)["errors"][0]["code"], "invalid_csv")

    def test_help_and_version_without_inputs(self):
        help_result = self.run_cli("--help")
        self.assertEqual(help_result.returncode, 0)
        self.assertIn(b"--schema", help_result.stdout)
        version_result = self.run_cli("--version")
        self.assertEqual(version_result.returncode, 0)
        self.assertEqual(version_result.stdout.decode().strip(), f"csv-contract-check {__version__}")

    def test_usage_errors_are_exit_two_without_tracebacks(self):
        for arguments in ((), ("--schema", self.schema), ("--schema", self.schema, "--format", "yaml", self.data)):
            with self.subTest(arguments=arguments):
                result = self.run_cli(*arguments)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")
                self.assertIn(b"usage:", result.stderr)
                self.assertNotIn(b"Traceback", result.stderr)

    def test_synthetic_examples(self):
        for name, exit_code, count in (("valid.csv", 0, 3), ("invalid.csv", 1, 2)):
            with self.subTest(name=name):
                result = self.run_cli("--schema", ROOT / "examples/people.schema.json", "--format", "json", ROOT / "examples" / name)
                self.assertEqual(result.returncode, exit_code)
                self.assertEqual(self.report(result)["records_checked"], count)


if __name__ == "__main__":
    unittest.main()
