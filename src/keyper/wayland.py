"""Wayland keyboard output and Hyprland focus protection."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from typing import Protocol

from .errors import KeyperError


@dataclass(frozen=True)
class WindowIdentity:
    address: str
    class_name: str
    title: str
    pid: int | None

    @classmethod
    def from_hyprland(cls, payload: dict[str, object]) -> "WindowIdentity":
        pid = payload.get("pid")
        return cls(
            address=str(payload.get("address") or ""),
            class_name=str(payload.get("class") or payload.get("initialClass") or ""),
            title=str(payload.get("title") or ""),
            pid=int(pid) if isinstance(pid, int) else None,
        )


KEYBOARD_BACKENDS = ("ydotool", "wtype")


def ydotool_socket_path() -> Path:
    configured = os.environ.get("YDOTOOL_SOCKET")
    if configured:
        return Path(configured).expanduser()
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return Path(runtime_dir) / ".ydotool_socket"


def require_ydotool_daemon() -> None:
    path = ydotool_socket_path()
    client = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    client.settimeout(0.5)
    try:
        client.connect(str(path))
    except (FileNotFoundError, ConnectionRefusedError, PermissionError, TimeoutError, OSError) as exc:
        raise KeyperError(
            "ydotoold is not ready at "
            f"{path}. Start it with 'systemctl --user enable --now ydotool.service'; "
            "on Arch, ensure your user is in the input group and sign out/in first."
        ) from exc
    finally:
        client.close()


def require_runtime(backend: str = "ydotool") -> None:
    if backend not in KEYBOARD_BACKENDS:
        raise KeyperError(f"Unsupported keyboard backend: {backend}")
    missing = [program for program in (backend, "hyprctl") if shutil.which(program) is None]
    if missing:
        raise KeyperError("Missing required program(s): " + ", ".join(missing))
    if os.environ.get("XDG_SESSION_TYPE") != "wayland":
        raise KeyperError("Keyper requires a Wayland session")
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        raise KeyperError("Keyper currently requires a Hyprland session")
    if backend == "ydotool":
        require_ydotool_daemon()


def active_window() -> WindowIdentity:
    try:
        result = subprocess.run(
            ["hyprctl", "-j", "activewindow"],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError, OSError) as exc:
        raise KeyperError(f"Unable to inspect the active Hyprland window: {exc}") from exc

    window = WindowIdentity.from_hyprland(payload)
    if not window.address:
        raise KeyperError("No active window was detected")
    return window


class WindowGuard:
    def __init__(self, expected: WindowIdentity, allowed_pattern: str) -> None:
        self.expected = expected
        try:
            self.allowed = re.compile(allowed_pattern)
        except re.error as exc:
            raise KeyperError(f"Invalid allowed-window pattern: {exc}") from exc

        if not self.allowed.search(expected.class_name):
            raise KeyperError(
                "Focused window is not an approved target. "
                f"Expected class matching {allowed_pattern!r}, got {expected.class_name!r}."
            )

    @classmethod
    def capture(cls, allowed_pattern: str) -> "WindowGuard":
        return cls(active_window(), allowed_pattern)

    def assert_focused(self) -> None:
        current = active_window()
        if current.address != self.expected.address or current.pid != self.expected.pid:
            raise KeyperError(
                "Focus left the original Remmina window; transfer stopped before the next chunk."
            )
        if not self.allowed.search(current.class_name):
            raise KeyperError("The focused window no longer matches the approved window class")


class Keyboard(Protocol):
    def validate_text(self, text: str) -> None: ...

    def type_text(self, text: str) -> None: ...

    def press(self, key: str) -> None: ...


class YdotoolKeyboard:
    """Emit kernel-level key events that Remmina handles like a physical keyboard."""

    KEY_CODES = {"Return": 28}

    def __init__(self, delay_ms: int) -> None:
        if not 0 <= delay_ms <= 100:
            raise KeyperError("Key delay must be between 0 and 100 milliseconds")
        self.delay_ms = delay_ms

    def validate_text(self, text: str) -> None:
        if not text.isascii():
            raise KeyperError(
                "The ydotool backend supports ASCII text only; remove or transliterate "
                "non-ASCII characters before typing"
            )
        unsupported = [
            character
            for character in text
            if ord(character) < 32 and character not in "\t\n\r"
        ]
        if unsupported or "\x7f" in text:
            raise KeyperError("The source contains unsupported control characters")

    def type_text(self, text: str) -> None:
        self.validate_text(text)
        try:
            subprocess.run(
                [
                    "ydotool",
                    "type",
                    f"--key-delay={self.delay_ms}",
                    "--file=-",
                ],
                input=text,
                text=True,
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.strip() if exc.stderr else str(exc)
            raise KeyperError(f"ydotool failed while sending keyboard input: {detail}") from exc
        except OSError as exc:
            raise KeyperError(f"ydotool failed while sending keyboard input: {exc}") from exc

    def press(self, key: str) -> None:
        try:
            code = self.KEY_CODES[key]
        except KeyError as exc:
            raise KeyperError(f"The ydotool backend does not support key {key!r}") from exc
        try:
            subprocess.run(
                [
                    "ydotool",
                    "key",
                    f"--key-delay={self.delay_ms}",
                    f"{code}:1",
                    f"{code}:0",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.strip() if exc.stderr else str(exc)
            raise KeyperError(f"ydotool failed while pressing {key}: {detail}") from exc
        except OSError as exc:
            raise KeyperError(f"ydotool failed while pressing {key}: {exc}") from exc


class WtypeKeyboard:
    def __init__(self, delay_ms: int) -> None:
        if not 0 <= delay_ms <= 100:
            raise KeyperError("Key delay must be between 0 and 100 milliseconds")
        self.delay_ms = delay_ms

    def validate_text(self, text: str) -> None:
        return None

    def type_text(self, text: str) -> None:
        try:
            subprocess.run(
                ["wtype", "-d", str(self.delay_ms), "-"],
                input=text,
                text=True,
                check=True,
            )
        except (subprocess.CalledProcessError, OSError) as exc:
            raise KeyperError(f"wtype failed while sending keyboard input: {exc}") from exc

    def press(self, key: str) -> None:
        try:
            subprocess.run(["wtype", "-k", key], check=True)
        except (subprocess.CalledProcessError, OSError) as exc:
            raise KeyperError(f"wtype failed while pressing {key}: {exc}") from exc


def create_keyboard(backend: str, delay_ms: int) -> Keyboard:
    if backend == "ydotool":
        return YdotoolKeyboard(delay_ms)
    if backend == "wtype":
        return WtypeKeyboard(delay_ms)
    raise KeyperError(f"Unsupported keyboard backend: {backend}")


def countdown(seconds: int, instruction: str) -> None:
    if not 1 <= seconds <= 60:
        raise KeyperError("Countdown must be between 1 and 60 seconds")
    print(instruction, flush=True)
    for remaining in range(seconds, 0, -1):
        print(f"Starting in {remaining}...", flush=True)
        time.sleep(1)
