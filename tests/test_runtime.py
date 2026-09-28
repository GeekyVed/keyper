import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from keyper.errors import KeyperError
from keyper.runtime import ProcessLock


class RuntimeTests(unittest.TestCase):
    def test_second_process_lock_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"XDG_RUNTIME_DIR": directory}):
                with ProcessLock():
                    with self.assertRaises(KeyperError):
                        with ProcessLock():
                            self.fail("second lock must not be acquired")

                self.assertFalse((Path(directory) / f"keyper-{os.getuid()}.pid").exists())


if __name__ == "__main__":
    unittest.main()
