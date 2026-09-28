import tempfile
from pathlib import Path
import unittest
import zipfile
import io

from keyper.archive import create_project_zip, looks_sensitive
from keyper.errors import KeyperError


class ArchiveTests(unittest.TestCase):
    def test_archive_is_deterministic_and_excludes_build_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "lib").mkdir()
            (root / "lib" / "main.dart").write_text("void main() {}\n", encoding="utf-8")
            (root / "build").mkdir()
            (root / "build" / "generated.bin").write_bytes(b"skip")

            first, names = create_project_zip(root)
            second, _ = create_project_zip(root)

            self.assertEqual(first, second)
            self.assertEqual(names, ("lib/main.dart",))
            with zipfile.ZipFile(io.BytesIO(first)) as archive:
                self.assertEqual(archive.namelist(), ["lib/main.dart"])

    def test_sensitive_files_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.dart").write_text("void main() {}", encoding="utf-8")
            (root / ".env").write_text("SECRET=x", encoding="utf-8")
            with self.assertRaises(KeyperError):
                create_project_zip(root)

    def test_flutter_and_environment_secrets_are_detected(self) -> None:
        for name in (".env.production", "upload.jks", "key.properties", "google-services.json"):
            with self.subTest(name=name):
                self.assertTrue(looks_sensitive(Path(name)))


if __name__ == "__main__":
    unittest.main()
