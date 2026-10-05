"""Execute a transfer plan through guarded keyboard input."""

from __future__ import annotations

import time
from collections.abc import Callable

from .protocol import TransferPlan
from .wayland import Keyboard, WindowGuard


def send_plan(
    plan: TransferPlan,
    keyboard: Keyboard,
    guard: WindowGuard,
    *,
    settle_ms: int,
    progress: Callable[[int, int], None] | None = None,
) -> None:
    if not 0 <= settle_ms <= 5000:
        raise ValueError("settle_ms must be between 0 and 5000")

    total = len(plan.commands)
    for index, command in enumerate(plan.commands, start=1):
        guard.assert_focused()
        keyboard.type_text(command)
        guard.assert_focused()
        keyboard.press("Return")
        if settle_ms:
            time.sleep(settle_ms / 1000)
        if progress is not None:
            progress(index, total)
