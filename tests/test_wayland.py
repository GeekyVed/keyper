import unittest

from keyper.errors import KeyperError
from keyper.wayland import WindowGuard, WindowIdentity


class WaylandTests(unittest.TestCase):
    def test_window_identity_from_hyprland(self) -> None:
        window = WindowIdentity.from_hyprland(
            {"address": "0x123", "class": "org.remmina.Remmina", "title": "RDP", "pid": 42}
        )
        self.assertEqual(window.address, "0x123")
        self.assertEqual(window.class_name, "org.remmina.Remmina")
        self.assertEqual(window.pid, 42)

    def test_guard_rejects_non_remmina_target(self) -> None:
        window = WindowIdentity("0x123", "com.example.Editor", "Editor", 42)
        with self.assertRaises(KeyperError):
            WindowGuard(window, r"(?i)remmina")


if __name__ == "__main__":
    unittest.main()

