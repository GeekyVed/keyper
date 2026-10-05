import os
import socket
import unittest
from unittest.mock import patch

from keyper.errors import KeyperError
from keyper.wayland import (
    WindowGuard,
    WindowIdentity,
    YdotoolKeyboard,
    create_keyboard,
    require_ydotool_daemon,
)


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

    @patch("keyper.wayland.subprocess.run")
    def test_ydotool_types_text_from_stdin(self, run) -> None:
        YdotoolKeyboard(4).type_text("abc 123")

        run.assert_called_once_with(
            ["ydotool", "type", "--key-delay=4", "--file=-"],
            input="abc 123",
            text=True,
            check=True,
            capture_output=True,
        )

    @patch("keyper.wayland.subprocess.run")
    def test_ydotool_rejects_non_ascii_before_sending(self, run) -> None:
        with self.assertRaises(KeyperError):
            YdotoolKeyboard(2).type_text("café")
        run.assert_not_called()

    @patch("keyper.wayland.subprocess.run")
    def test_ydotool_rejects_control_characters_before_sending(self, run) -> None:
        with self.assertRaises(KeyperError):
            YdotoolKeyboard(2).type_text("hello\x1bworld")
        run.assert_not_called()

    def test_default_backend_factory_builds_ydotool_keyboard(self) -> None:
        self.assertIsInstance(create_keyboard("ydotool", 2), YdotoolKeyboard)

    @patch("keyper.wayland.socket.socket")
    def test_ydotool_health_check_uses_datagram_socket(self, socket_factory) -> None:
        with patch.dict(os.environ, {"YDOTOOL_SOCKET": "/tmp/keyper-test.socket"}):
            require_ydotool_daemon()

        socket_factory.assert_called_once_with(socket.AF_UNIX, socket.SOCK_DGRAM)
        socket_factory.return_value.connect.assert_called_once_with("/tmp/keyper-test.socket")
        socket_factory.return_value.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
