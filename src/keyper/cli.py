"""Command-line interface for Keyper."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import sys

from . import __version__
from .archive import create_project_zip, looks_sensitive
from .errors import KeyperError
from .protocol import TransferPlan, build_file_plan, build_tree_plan
from .runtime import ProcessLock, stop_running
from .sender import send_plan
from .wayland import (
    KEYBOARD_BACKENDS,
    WindowGuard,
    countdown,
    create_keyboard,
    require_runtime,
)

DEFAULT_ALLOWED_WINDOW = r"(?i)remmina"
DEFAULT_MAX_PAYLOAD_MIB = 5
DIRECT_TYPE_CHUNK_CHARS = 1024
TYPE_ONLY_ENV = "KEYPER_TYPE_ONLY"


def type_only_enabled() -> bool:
    """Return whether PowerShell-backed transfer commands must be disabled."""
    value = os.environ.get(TYPE_ONLY_ENV, "").strip().lower()
    return value not in {"", "0", "false", "no", "off"}


def _require_transfer_enabled() -> None:
    if type_only_enabled():
        raise KeyperError(
            f"PowerShell transfers are disabled because {TYPE_ONLY_ENV} is enabled"
        )


def _positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return number


def _nonnegative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("value must be zero or greater")
    return number


def _countdown_seconds(value: str) -> int:
    number = _positive_int(value)
    if number > 60:
        raise argparse.ArgumentTypeError("countdown cannot exceed 60 seconds")
    return number


def _key_delay_ms(value: str) -> int:
    number = _nonnegative_int(value)
    if number > 100:
        raise argparse.ArgumentTypeError("key delay cannot exceed 100 milliseconds")
    return number


def _settle_ms(value: str) -> int:
    number = _nonnegative_int(value)
    if number > 5000:
        raise argparse.ArgumentTypeError("settle time cannot exceed 5000 milliseconds")
    return number


def _add_typing_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--countdown", type=_countdown_seconds, default=7)
    parser.add_argument("--key-delay-ms", type=_key_delay_ms, default=2)
    parser.add_argument("--allowed-window", default=DEFAULT_ALLOWED_WINDOW)
    parser.add_argument(
        "--backend",
        choices=KEYBOARD_BACKENDS,
        default="ydotool",
        help="keyboard injection backend (default: ydotool)",
    )


def _add_transfer_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--to", required=True, help="Destination path in remote PowerShell")
    parser.add_argument("--chunk-chars", type=_positive_int, default=1024)
    parser.add_argument("--max-payload-mib", type=_positive_int, default=DEFAULT_MAX_PAYLOAD_MIB)
    parser.add_argument("--settle-ms", type=_settle_ms, default=100)
    parser.add_argument("--dry-run", action="store_true", help="Print commands instead of typing them")
    _add_typing_options(parser)


def build_parser() -> argparse.ArgumentParser:
    type_only = type_only_enabled()
    parser = argparse.ArgumentParser(
        prog="keyper",
        description=(
            "Type reviewed text into an approved Remmina session."
            if type_only
            else "Ferry reviewed files into an approved Remmina session using visible keyboard input."
        ),
        epilog=(
            f"Type-only mode is active via {TYPE_ONLY_ENV}; PowerShell transfer commands are unavailable."
            if type_only
            else None
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    doctor = commands.add_parser("doctor", help="Check the local Wayland/Hyprland requirements")
    doctor.add_argument("--backend", choices=KEYBOARD_BACKENDS, default="ydotool")

    probe = commands.add_parser("probe", help="Type a harmless keyboard-layout probe into Remmina")
    _add_typing_options(probe)

    raw = commands.add_parser("type", help="Type a text file directly into the focused RDP app")
    raw.add_argument("file", type=Path)
    raw.add_argument("--max-bytes", type=_positive_int, default=200_000)
    _add_typing_options(raw)

    if not type_only:
        send = commands.add_parser("send", help="Transfer one file through a remote PowerShell prompt")
        send.add_argument("file", type=Path)
        send.add_argument("--compression", choices=("auto", "gzip", "none"), default="auto")
        send.add_argument("--allow-sensitive", action="store_true")
        _add_transfer_options(send)

        tree = commands.add_parser("send-tree", help="Compress and transfer a project directory")
        tree.add_argument("directory", type=Path)
        tree.add_argument("--allow-sensitive", action="store_true")
        _add_transfer_options(tree)

    commands.add_parser("stop", help="Stop a running transfer")
    return parser


def _print_plan(plan: TransferPlan, key_delay_ms: int, settle_ms: int) -> None:
    ratio = plan.payload_size / plan.source_size if plan.source_size else 1
    print(f"Type:          {plan.kind}")
    print(f"Destination:   {plan.destination}")
    print(f"Source bytes:  {plan.source_size:,}")
    print(f"Payload bytes: {plan.payload_size:,} ({ratio:.1%})")
    print(f"Encoded chars: {plan.encoded_size:,}")
    print(f"Chunks:        {len(plan.chunks):,}")
    print(f"Compression:   {plan.compression}")
    print(f"SHA-256:       {plan.source_sha256}")
    print(f"Estimated time: {plan.estimated_seconds(key_delay_ms, settle_ms):.1f}s")


def _dry_run(plan: TransferPlan) -> None:
    print("# Keyper PowerShell transcript")
    for command in plan.commands:
        print(command)


def _send(plan: TransferPlan, args: argparse.Namespace) -> int:
    _print_plan(plan, args.key_delay_ms, args.settle_ms)
    max_payload = args.max_payload_mib * 1024 * 1024
    if plan.payload_size > max_payload:
        raise KeyperError(
            f"Payload is {plan.payload_size:,} bytes, above the configured {max_payload:,}-byte limit"
        )
    if args.dry_run:
        _dry_run(plan)
        return 0

    keyboard = create_keyboard(args.backend, args.key_delay_ms)
    require_runtime(args.backend)
    with ProcessLock():
        countdown(
            args.countdown,
            "Open PowerShell inside the RDP session, leave an empty prompt ready, "
            "then focus the Remmina window.",
        )
        guard = WindowGuard.capture(args.allowed_window)
        print(f"Locked to Remmina window: {guard.expected.title!r}")

        def progress(current: int, total: int) -> None:
            if current == total or current == 1 or current % max(1, total // 10) == 0:
                print(f"Sent {current}/{total} commands", flush=True)

        send_plan(
            plan,
            keyboard,
            guard,
            settle_ms=args.settle_ms,
            progress=progress,
        )
    print("Transfer commands completed. Confirm the green KEYPER OK message in PowerShell.")
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    checks = {
        args.backend: shutil.which(args.backend),
        "hyprctl": shutil.which("hyprctl"),
        "remmina": shutil.which("remmina"),
        "python": sys.executable,
    }
    failed = False
    if type_only_enabled():
        print(f"[mode] type-only: send and send-tree disabled by {TYPE_ONLY_ENV}")
    for name, path in checks.items():
        if path:
            print(f"[ok] {name}: {path}")
        else:
            failed = True
            print(f"[missing] {name}")
    try:
        require_runtime(args.backend)
        print(f"[ok] Wayland + Hyprland + {args.backend} runtime")
    except KeyperError as exc:
        failed = True
        print(f"[failed] {exc}")
    return 1 if failed else 0


def command_probe(args: argparse.Namespace) -> int:
    probe = "KEYPER-PROBE: abcXYZ 0123456789 +/= $()[]{};,:._-\\"
    keyboard = create_keyboard(args.backend, args.key_delay_ms)
    keyboard.validate_text(probe)
    require_runtime(args.backend)
    with ProcessLock():
        countdown(
            args.countdown,
            "Open Notepad inside the RDP session, click an empty document, then focus Remmina.",
        )
        guard = WindowGuard.capture(args.allowed_window)
        guard.assert_focused()
        keyboard.type_text(probe)
    print(f"Expected text: {probe}")
    return 0


def command_type(args: argparse.Namespace) -> int:
    path = args.file.resolve()
    if not path.is_file():
        raise KeyperError(f"Text file does not exist: {path}")
    data = path.read_bytes()
    if len(data) > args.max_bytes:
        raise KeyperError(f"File is larger than the {args.max_bytes:,}-byte direct-typing limit")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise KeyperError("Direct typing accepts UTF-8 text only; use 'send' for binary files") from exc

    keyboard = create_keyboard(args.backend, args.key_delay_ms)
    keyboard.validate_text(text)
    require_runtime(args.backend)
    with ProcessLock():
        countdown(
            args.countdown,
            "Open the target editor inside RDP, disable auto-closing/format-on-type, "
            "click the insertion point, then focus Remmina.",
        )
        guard = WindowGuard.capture(args.allowed_window)
        for offset in range(0, len(text), DIRECT_TYPE_CHUNK_CHARS):
            guard.assert_focused()
            keyboard.type_text(text[offset : offset + DIRECT_TYPE_CHUNK_CHARS])
    print(f"Typed {len(data):,} UTF-8 bytes.")
    return 0


def command_send(args: argparse.Namespace) -> int:
    _require_transfer_enabled()
    path = args.file.resolve()
    if not path.is_file():
        raise KeyperError(f"File does not exist: {path}")
    if looks_sensitive(path) and not args.allow_sensitive:
        raise KeyperError(
            f"Refusing sensitive-looking file {path.name!r}; pass --allow-sensitive only after review"
        )
    plan = build_file_plan(
        path.read_bytes(),
        args.to,
        chunk_chars=args.chunk_chars,
        compression=args.compression,
    )
    return _send(plan, args)


def command_send_tree(args: argparse.Namespace) -> int:
    _require_transfer_enabled()
    archive, files = create_project_zip(args.directory, allow_sensitive=args.allow_sensitive)
    print(f"Archived {len(files):,} reviewed files from {args.directory.resolve()}")
    plan = build_tree_plan(archive, args.to, chunk_chars=args.chunk_chars)
    return _send(plan, args)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            return command_doctor(args)
        if args.command == "probe":
            return command_probe(args)
        if args.command == "type":
            return command_type(args)
        if args.command == "send":
            return command_send(args)
        if args.command == "send-tree":
            return command_send_tree(args)
        if args.command == "stop":
            return stop_running()
        parser.error(f"Unknown command: {args.command}")
    except KeyperError as exc:
        print(f"keyper: error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"keyper: operating-system error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nkeyper: interrupted", file=sys.stderr)
        return 130
    return 0
