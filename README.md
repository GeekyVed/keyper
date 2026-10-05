# Keyper

[![CI](https://github.com/GeekyVed/keyper/actions/workflows/ci.yml/badge.svg)](https://github.com/GeekyVed/keyper/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Wayland%20%2B%20Hyprland-58E1FF)](https://hypr.land/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Keyper plays reviewed files into an approved Windows RDP session as keyboard
input. It is designed for environments where administrators explicitly allow
keyboard automation while clipboard and drive redirection remain disabled.

Keyper does not install anything on Windows or open a separate connection to
the remote machine. Its default `ydotool` backend emits local kernel input
events that Remmina handles like a physical keyboard. In transfer mode, it
types visible PowerShell commands that reconstruct and verify the file.

> [!IMPORTANT]
> This is auditable automation, not a stealth or policy-bypass tool. PowerShell
> history, script-block logging, EDR, RDS auditing, and screen recording may
> record its activity. Use it only where the system owner has approved both the
> transfer channel and the commands being executed.

## Features

- Transfers individual files or complete project trees.
- Compresses suitable files and sends bounded Base64 chunks.
- Verifies SHA-256 before replacing or extracting anything remotely.
- Locks each transfer to the original Remmina window and stops on focus loss.
- Excludes generated project directories such as `.git`, `.dart_tool`, and
  `build`.
- Refuses common environment, signing-key, and credential files by default.
- Includes dry-run inspection, transfer estimates, process locking, and an
  emergency-stop command.
- Has no third-party Python dependencies.

## Requirements

### Local Linux machine

- Python 3.11 or newer
- Wayland with Hyprland
- `ydotool`, its `ydotoold` service, and `hyprctl`
- Remmina with RDP support

### Remote Windows machine

- An approved RDP session
- Windows PowerShell 5.1 or PowerShell 7+
- Permission to create files at the chosen destination

## Installation

On Omarchy, a fresh installation is:

```bash
git clone https://github.com/GeekyVed/keyper.git
cd keyper
./install.sh --with-deps
keyper doctor
```

`--with-deps` installs missing Arch packages through `omarchy pkg add`. On a
plain Arch installation it uses `pacman`. If the prerequisites are already
installed, the dependency-free path is simply:

```bash
./install.sh
```

On Arch, `/dev/uinput` belongs to the `input` group. If the installer reports
that permission is missing, review this command, run it, and then sign out of
Linux and back in before rerunning the installer:

```bash
sudo usermod -aG input "$USER"
```

Membership in `input` is security-sensitive: it permits access to local input
devices, not just Keyper. A machine administrator can instead configure a
narrower distro-specific permission for `/dev/uinput`. Keyper checks the
`ydotoold` socket before every run and fails before the countdown when the
service is unavailable.

The installer links the checkout's launcher into `~/.local/bin`; it does not
download Python packages or modify the remote Windows machine. Keep the clone
in place after installation. If you move it, rerun the installer from its new
location.

To remove that launcher safely:

```bash
./install.sh --uninstall
```

You can also run `./keyper` directly without installing it.

## Type-only mode

For environments where PowerShell-backed transfers must not be available,
enable Keyper's fail-safe type-only mode in the local shell:

```bash
export KEYPER_TYPE_ONLY=1
```

While enabled, `send` and `send-tree` are removed from the command parser and
are also blocked by the transfer handlers. `doctor`, `probe`, `type`, and
`stop` remain available. Confirm the mode before typing:

```bash
keyper doctor
keyper --help
```

`doctor` reports the active mode, and `--help` does not list either PowerShell
transfer command. The setting applies to the current shell and its child
processes. Run `unset KEYPER_TYPE_ONLY` only when PowerShell transfers have
been explicitly approved again.

## First-run keyboard check

Keyboard layouts can disagree about punctuation. Before transferring files,
open Notepad inside RDP, focus an empty document, and run:

```bash
keyper probe
```

You get a seven-second countdown to focus Remmina. Compare the typed result
with the expected probe shown in the local terminal. Do not continue if they
differ.

`ydotool` is the default because its kernel-level events survive Remmina's RDP
translation. The older `wtype` backend remains available only for diagnostics
with `--backend wtype`; it is known to produce incorrect keys in some Remmina
sessions.

## Transfer one file

Open PowerShell inside RDP and leave an empty prompt ready. Then run locally:

```bash
keyper send ./lib/main.dart --to 'C:\work\superadmin\lib\main.dart'
```

Relative destinations use PowerShell's current directory:

```bash
keyper send ./lib/main.dart --to '.\lib\main.dart'
```

Keyper types and executes the reconstruction commands. Confirm the green
`KEYPER OK` message in the remote PowerShell window before continuing.

## Transfer a Flutter project

```bash
keyper send-tree ~/projects/superadmin --to 'C:\work\superadmin'
```

The project is archived locally, transferred, hash-verified, and extracted
with `Expand-Archive -Force`. Existing matching files are overwritten;
unrelated destination files remain. `.git`, `.dart_tool`, `build`, `.venv`,
`__pycache__`, and `.pytest_cache` are excluded automatically.

Keyper stops if it finds likely secrets such as `.env.*`, `key.properties`,
`google-services.json`, private keys, signing keystores, or certificate files.
Review and remove them instead of transferring secrets. `--allow-sensitive`
exists for explicitly approved fixtures but should be exceptional.

## Direct typing

For a small ASCII source file or snippet that should be typed into an editor:

```bash
keyper type ./snippet.txt
```

This command deliberately does not press Enter afterward. Editors may
auto-indent, auto-close brackets, or format while typing, so PowerShell-based
`send` is more reliable for source files.

## Dry run and tuning

Inspect the exact PowerShell transcript without typing anything:

```bash
keyper send ./lib/main.dart --to '.\lib\main.dart' --dry-run
```

The transcript contains the encoded payload, so save or share it only in an
approved location.

For a high-latency session, slow the transfer down:

```bash
keyper send ./file.dart --to '.\file.dart' \
  --key-delay-ms 4 --settle-ms 250 --chunk-chars 768
```

Defaults are 2 ms between keystrokes, 100 ms after each command, and 1,024
Base64 characters per chunk. The default payload limit is 5 MiB because this
channel is intentionally visible and comparatively slow.

## Emergency stop

From another local terminal:

```bash
keyper stop
```

Moving focus away from the captured Remmina window also stops before the next
chunk. The bounded chunk already being typed may take a few seconds to finish.

## How it works

1. Keyper archives or compresses the reviewed local input when appropriate.
2. It splits Base64 into PowerShell-friendly chunks.
3. After the countdown, it captures the focused Remmina window identity.
4. It types one command at a time, checking focus between every chunk.
5. PowerShell decodes into a temporary file and calculates SHA-256.
6. Only a matching payload is moved into place or extracted.

The Windows side receives ordinary RDP keyboard input, but automation may be
recognizable from timing and remains visible to normal Windows auditing.

## Development

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src tests
```

Optional editable packaging installation:

```bash
uv tool install --editable .
```

## Limitations

- Focus protection operates between chunks, not between individual keys.
- Remote security controls may block PowerShell or archive extraction.
- Directory extraction is not atomic.
- Large binaries are a poor fit for a keyboard channel.
- Keyper cannot read the remote success message; a user must confirm it.

## License

[MIT](LICENSE)
