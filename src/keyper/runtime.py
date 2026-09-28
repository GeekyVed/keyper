"""Single-process lock and emergency-stop support."""

from __future__ import annotations

import atexit
import os
from pathlib import Path
import signal

from .errors import KeyperError


def lock_path() -> Path:
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
    return runtime / f"keyper-{os.getuid()}.pid"


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class ProcessLock:
    def __init__(self) -> None:
        self.path = lock_path()
        self.acquired = False

    def __enter__(self) -> "ProcessLock":
        if self.path.exists():
            try:
                existing_pid = int(self.path.read_text(encoding="ascii").strip())
            except (OSError, ValueError):
                existing_pid = -1
            if existing_pid > 0 and _is_running(existing_pid):
                raise KeyperError(
                    f"Another Keyper transfer is running with PID {existing_pid}. "
                    "Use 'keyper stop' to stop it."
                )
            self.path.unlink(missing_ok=True)

        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        try:
            descriptor = os.open(self.path, flags, 0o600)
        except FileExistsError as exc:
            raise KeyperError("Another Keyper process acquired the transfer lock") from exc
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(str(os.getpid()))
        self.acquired = True
        atexit.register(self.release)
        return self

    def release(self) -> None:
        if self.acquired:
            try:
                if self.path.read_text(encoding="ascii").strip() == str(os.getpid()):
                    self.path.unlink(missing_ok=True)
            except OSError:
                pass
            self.acquired = False

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.release()


def stop_running() -> int:
    path = lock_path()
    if not path.exists():
        print("No Keyper transfer is running.")
        return 0
    try:
        pid = int(path.read_text(encoding="ascii").strip())
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        path.unlink(missing_ok=True)
        print("Removed a stale Keyper lock.")
        return 0
    except (OSError, ValueError) as exc:
        raise KeyperError(f"Unable to stop the running transfer: {exc}") from exc
    print(f"Stop signal sent to Keyper PID {pid}.")
    return 0
