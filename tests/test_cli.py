import contextlib
import io
from pathlib import Path
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
