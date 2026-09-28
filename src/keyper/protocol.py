"""Build the visible PowerShell protocol typed into the remote session."""

from __future__ import annotations

import base64
import gzip
import hashlib
from dataclasses import dataclass
from typing import Literal

from .errors import KeyperError

Compression = Literal["auto", "gzip", "none"]


@dataclass(frozen=True)
class TransferPlan:
    commands: tuple[str, ...]
    chunks: tuple[str, ...]
    source_size: int
    payload_size: int
    encoded_size: int
    source_sha256: str
    payload_sha256: str
    compression: Literal["gzip", "none"]
    destination: str
    kind: Literal["file", "tree"]

    def estimated_seconds(self, key_delay_ms: int, settle_ms: int) -> float:
        typed = sum(len(command) for command in self.commands)
        return (typed * key_delay_ms + len(self.commands) * settle_ms) / 1000


def powershell_quote(value: str) -> str:
    """Return a PowerShell single-quoted string literal."""
    if "\x00" in value:
        raise KeyperError("The remote path cannot contain a NUL byte")
    return "'" + value.replace("'", "''") + "'"


def _prepare_payload(data: bytes, compression: Compression) -> tuple[bytes, str]:
    if compression not in {"auto", "gzip", "none"}:
        raise KeyperError(f"Unsupported compression mode: {compression}")

    if compression == "none":
        return data, "none"

    compressed = gzip.compress(data, compresslevel=9, mtime=0)
    if compression == "gzip" or len(compressed) < len(data):
        return compressed, "gzip"
    return data, "none"


def _decode_command(compression: str) -> str:
    if compression == "none":
        return "$kfb=[Convert]::FromBase64String($kf)"
    return (
        "$kfc=[Convert]::FromBase64String($kf);"
        "$kfi=[IO.MemoryStream]::new();$kfi.Write($kfc,0,$kfc.Length);$kfi.Position=0;"
        "$kfg=[IO.Compression.GZipStream]::new("
        "$kfi,[IO.Compression.CompressionMode]::Decompress);"
        "$kfo=[IO.MemoryStream]::new();$kfg.CopyTo($kfo);"
        "$kfg.Dispose();$kfi.Dispose();$kfb=$kfo.ToArray();$kfo.Dispose()"
    )


def _payload_commands(encoded: str, chunk_chars: int) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if not 256 <= chunk_chars <= 6000:
        raise KeyperError("Chunk size must be between 256 and 6000 characters")
    chunks = tuple(encoded[index : index + chunk_chars] for index in range(0, len(encoded), chunk_chars))
    commands = ("$ErrorActionPreference='Stop';$kf=''",) + tuple(
        f"$kf+='{chunk}'" for chunk in chunks
    )
    return chunks, commands


def build_file_plan(
    data: bytes,
    destination: str,
    *,
    chunk_chars: int = 1024,
    compression: Compression = "auto",
) -> TransferPlan:
    if not destination.strip():
        raise KeyperError("The remote destination path cannot be empty")

    payload, applied_compression = _prepare_payload(data, compression)
    encoded = base64.b64encode(payload).decode("ascii")
    chunks, commands = _payload_commands(encoded, chunk_chars)
    source_hash = hashlib.sha256(data).hexdigest()
    payload_hash = hashlib.sha256(payload).hexdigest()
    quoted_destination = powershell_quote(destination)

    final = (
        f"$kfp=$ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath({quoted_destination});"
        "$kfd=[IO.Path]::GetDirectoryName($kfp);"
        "if($kfd){[IO.Directory]::CreateDirectory($kfd)|Out-Null};"
        + _decode_command(applied_compression)
        + ";$kft=$kfp+'.keyper.tmp';[IO.File]::WriteAllBytes($kft,$kfb);"
        "$kfh=(Get-FileHash -LiteralPath $kft -Algorithm SHA256).Hash.ToLowerInvariant();"
        f"if($kfh -ne '{source_hash}'){{Remove-Item -LiteralPath $kft -Force -ErrorAction SilentlyContinue;"
        "throw ('KEYPER VERIFY FAILED: '+$kfh)};"
        "Move-Item -LiteralPath $kft -Destination $kfp -Force;"
        f"Write-Host ('KEYPER OK: {len(data)} bytes -> '+$kfp) -ForegroundColor Green;"
        "Remove-Variable kf,kfb,kfc,kfi,kfg,kfo,kfp,kfd,kft,kfh -ErrorAction SilentlyContinue"
    )

    return TransferPlan(
        commands=commands + (final,),
        chunks=chunks,
        source_size=len(data),
        payload_size=len(payload),
        encoded_size=len(encoded),
        source_sha256=source_hash,
        payload_sha256=payload_hash,
        compression=applied_compression,
        destination=destination,
        kind="file",
    )


def build_tree_plan(
    archive: bytes,
    destination: str,
    *,
    chunk_chars: int = 1024,
) -> TransferPlan:
    if not destination.strip():
        raise KeyperError("The remote destination directory cannot be empty")

    encoded = base64.b64encode(archive).decode("ascii")
    chunks, commands = _payload_commands(encoded, chunk_chars)
    archive_hash = hashlib.sha256(archive).hexdigest()
    quoted_destination = powershell_quote(destination)

    final = (
        f"$kfp=$ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath({quoted_destination});"
        "$kft=Join-Path $env:TEMP ('keyper-'+[Guid]::NewGuid().ToString('N')+'.zip');"
        "$kfb=[Convert]::FromBase64String($kf);[IO.File]::WriteAllBytes($kft,$kfb);"
        "$kfh=(Get-FileHash -LiteralPath $kft -Algorithm SHA256).Hash.ToLowerInvariant();"
        f"if($kfh -ne '{archive_hash}'){{Remove-Item -LiteralPath $kft -Force -ErrorAction SilentlyContinue;"
        "throw ('KEYPER VERIFY FAILED: '+$kfh)};"
        "[IO.Directory]::CreateDirectory($kfp)|Out-Null;"
        "Expand-Archive -LiteralPath $kft -DestinationPath $kfp -Force;"
        "Remove-Item -LiteralPath $kft -Force;"
        f"Write-Host ('KEYPER OK: project extracted -> '+$kfp) -ForegroundColor Green;"
        "Remove-Variable kf,kfb,kfp,kft,kfh -ErrorAction SilentlyContinue"
    )

    return TransferPlan(
        commands=commands + (final,),
        chunks=chunks,
        source_size=len(archive),
        payload_size=len(archive),
        encoded_size=len(encoded),
        source_sha256=archive_hash,
        payload_sha256=archive_hash,
        compression="none",
        destination=destination,
        kind="tree",
    )
