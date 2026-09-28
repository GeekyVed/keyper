"""Create deterministic, reviewed project archives for send-tree."""

from __future__ import annotations

import io
from pathlib import Path
import zipfile

from .errors import KeyperError

DEFAULT_EXCLUDES = frozenset({".git", ".dart_tool", "build", "__pycache__", ".pytest_cache", ".venv"})
SENSITIVE_NAMES = frozenset(
    {
        ".env",
        "credentials.json",
        "google-services.json",
        "id_rsa",
        "id_ed25519",
        "key.properties",
        "service-account.json",
    }
)
SENSITIVE_SUFFIXES = frozenset({".jks", ".key", ".keystore", ".p12", ".pem", ".pfx"})


def looks_sensitive(path: Path) -> bool:
    name = path.name.lower()
    return (
        name in SENSITIVE_NAMES
        or name.startswith(".env.")
        or path.suffix.lower() in SENSITIVE_SUFFIXES
    )


def create_project_zip(
    root: Path,
    *,
    excludes: frozenset[str] = DEFAULT_EXCLUDES,
    allow_sensitive: bool = False,
) -> tuple[bytes, tuple[str, ...]]:
    root = root.resolve()
    if not root.is_dir():
        raise KeyperError(f"Project directory does not exist: {root}")

    files: list[Path] = []
    sensitive: list[str] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in excludes for part in relative.parts):
            continue
        if path.is_symlink():
            continue
        if not path.is_file():
            continue
        if looks_sensitive(path):
            sensitive.append(relative.as_posix())
            if not allow_sensitive:
                continue
        files.append(path)

    if sensitive and not allow_sensitive:
        listing = "\n  - ".join(sensitive)
        raise KeyperError(
            "Sensitive-looking files were found and were not archived:\n"
            f"  - {listing}\n"
            "Remove them, exclude them, or pass --allow-sensitive after review."
        )
    if not files:
        raise KeyperError("No transferable files were found in the project directory")

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            relative = path.relative_to(root).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)

    return output.getvalue(), tuple(path.relative_to(root).as_posix() for path in files)
