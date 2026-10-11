import io
import json
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch
import unittest

from examnet import cli


class CliTests(unittest.TestCase):
    def test_print_schema_outputs_valid_json_array_copies_to_clipboard_and_skips_automation(self):
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch("sys.argv", ["python -m examnet", "--print-schema"]):
            with patch("examnet.cli.configure_logging") as configure_logging_mock:
                with patch("examnet.cli.copy_to_clipboard", return_value=True) as copy_mock:
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        cli.main()

        payload = json.loads(stdout.getvalue())

        self.assertIsInstance(payload, list)
        self.assertGreaterEqual(len(payload), 4)
        self.assertTrue(
            {item["question_type"] for item in payload}
            >= {"multiple_choice", "list_match", "fill_gaps", "long_answer"}
        )
        configure_logging_mock.assert_not_called()
        copy_mock.assert_called_once_with(stdout.getvalue().rstrip("\n"))
        self.assertIn("Schema copied to clipboard.", stderr.getvalue())

    def test_print_schema_reports_when_clipboard_is_unavailable(self):
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch("sys.argv", ["python -m examnet", "--print-schema"]):
            with patch("examnet.cli.copy_to_clipboard", return_value=False):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    cli.main()

        payload = json.loads(stdout.getvalue())
        self.assertGreaterEqual(len(payload), 4)
        self.assertIn("Schema printed, but clipboard copy was unavailable.", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
