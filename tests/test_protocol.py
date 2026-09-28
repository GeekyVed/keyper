import base64
import gzip
import unittest

from keyper.errors import KeyperError
from keyper.protocol import build_file_plan, build_tree_plan, powershell_quote


class ProtocolTests(unittest.TestCase):
    def test_powershell_quote_escapes_apostrophes(self) -> None:
        self.assertEqual(powershell_quote("C:\\O'Brien\\file.dart"), "'C:\\O''Brien\\file.dart'")

    def test_file_plan_round_trips_compressed_payload(self) -> None:
        source = (b"class AdminPanel {}\n" * 1000)
        plan = build_file_plan(source, r"C:\work\admin.dart", chunk_chars=256)
        payload = base64.b64decode("".join(plan.chunks))
        self.assertEqual(plan.compression, "gzip")
        self.assertEqual(gzip.decompress(payload), source)
        self.assertIn(plan.source_sha256, plan.commands[-1])
        self.assertIn(".keyper.tmp", plan.commands[-1])
        self.assertEqual(plan.commands[-1].count("{"), plan.commands[-1].count("}"))

    def test_file_plan_keeps_incompressible_small_payload_raw(self) -> None:
        source = bytes(range(256))
        plan = build_file_plan(source, "file.bin", chunk_chars=256)
        self.assertEqual(plan.compression, "none")
        self.assertEqual(base64.b64decode("".join(plan.chunks)), source)

    def test_tree_plan_round_trips_archive(self) -> None:
        archive = b"PK\x03\x04fake-zip-content"
        plan = build_tree_plan(archive, r"C:\work\panel", chunk_chars=256)
        self.assertEqual(base64.b64decode("".join(plan.chunks)), archive)
        self.assertIn("Expand-Archive", plan.commands[-1])
        self.assertIn(plan.source_sha256, plan.commands[-1])
        self.assertEqual(plan.commands[-1].count("{"), plan.commands[-1].count("}"))

    def test_rejects_invalid_chunk_size(self) -> None:
        with self.assertRaises(KeyperError):
            build_file_plan(b"hello", "file.txt", chunk_chars=20)


if __name__ == "__main__":
    unittest.main()
