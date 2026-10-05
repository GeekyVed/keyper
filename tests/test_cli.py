import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from keyper.cli import build_parser, main


class CliTests(unittest.TestCase):
    def test_dry_run_builds_transcript_without_runtime_access(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "main.dart"
            source.write_text("void main() {}\n", encoding="utf-8")
            output = io.StringIO()

            with contextlib.redirect_stdout(output):
                result = main(["send", str(source), "--to", r"C:\work\main.dart", "--dry-run"])

            self.assertEqual(result, 0)
            self.assertIn("Keyper PowerShell transcript", output.getvalue())
            self.assertIn(r"C:\work\main.dart", output.getvalue())

    def test_sensitive_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / ".env.production"
            source.write_text("TOKEN=example\n", encoding="utf-8")
            errors = io.StringIO()

            with contextlib.redirect_stderr(errors):
                result = main(["send", str(source), "--to", r"C:\work\.env", "--dry-run"])

            self.assertEqual(result, 2)
            self.assertIn("sensitive-looking file", errors.getvalue())

    def test_parser_rejects_excessive_countdown(self) -> None:
        parser = build_parser()
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parser.parse_args(["probe", "--countdown", "61"])

    def test_ydotool_is_the_default_typing_backend(self) -> None:
        args = build_parser().parse_args(["probe"])
        self.assertEqual(args.backend, "ydotool")

    def test_type_rejects_non_ascii_before_runtime_access(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "unicode.dart"
            source.write_text("// café\n", encoding="utf-8")
            errors = io.StringIO()

            with contextlib.redirect_stderr(errors):
                result = main(["type", str(source)])

            self.assertEqual(result, 2)
            self.assertIn("ASCII text only", errors.getvalue())

    def test_type_only_mode_removes_powershell_commands(self) -> None:
        with patch.dict(os.environ, {"KEYPER_TYPE_ONLY": "1"}):
            parser = build_parser()
            typed = parser.parse_args(["type", "example.dart"])
            self.assertEqual(typed.command, "type")

            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    parser.parse_args(["send", "example.dart", "--to", r"C:\work\example.dart"])

    def test_explicit_false_value_keeps_transfer_commands(self) -> None:
        with patch.dict(os.environ, {"KEYPER_TYPE_ONLY": "false"}):
            args = build_parser().parse_args(
                ["send", "example.dart", "--to", r"C:\work\example.dart", "--dry-run"]
            )
            self.assertEqual(args.command, "send")


if __name__ == "__main__":
    unittest.main()
