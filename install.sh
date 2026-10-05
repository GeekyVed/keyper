#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source_launcher="$project_dir/keyper"
bin_dir="${HOME}/.local/bin"
installed_launcher="$bin_dir/keyper"
install_dependencies=false
uninstall=false

usage() {
  printf '%s\n' \
    "Usage: ./install.sh [--with-deps | --uninstall]" \
    "" \
    "  --with-deps  Install required packages on Omarchy or Arch first" \
    "  --uninstall  Remove this checkout's ~/.local/bin/keyper link" \
    "  -h, --help   Show this help"
}

for argument in "$@"; do
  case "$argument" in
    --with-deps) install_dependencies=true ;;
    --uninstall) uninstall=true ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$argument" >&2; usage >&2; exit 2 ;;
  esac
done

if $install_dependencies && $uninstall; then
  printf '%s\n' "--with-deps and --uninstall cannot be used together" >&2
  exit 2
fi

if $uninstall; then
  if [[ ! -L "$installed_launcher" ]]; then
    printf 'Nothing removed: %s is not a symbolic link.\n' "$installed_launcher"
    exit 0
  fi
  current_target="$(readlink -f -- "$installed_launcher")"
  expected_target="$(readlink -f -- "$source_launcher")"
  if [[ "$current_target" != "$expected_target" ]]; then
    printf 'Refusing to remove a launcher owned by another installation: %s\n' \
      "$installed_launcher" >&2
    exit 1
  fi
  unlink -- "$installed_launcher"
  printf 'Removed %s\n' "$installed_launcher"
  exit 0
fi

if $install_dependencies; then
  if command -v omarchy >/dev/null 2>&1; then
    omarchy pkg add python ydotool remmina freerdp
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -S --needed python ydotool remmina freerdp
  else
    printf '%s\n' \
      "Automatic dependency installation supports Omarchy and Arch only." \
      "Install Python 3.11+, ydotool, Hyprland, and Remmina, then rerun ./install.sh." >&2
    exit 1
  fi
fi

missing=()
for program in python3 ydotool hyprctl remmina; do
  if ! command -v "$program" >/dev/null 2>&1; then
    missing+=("$program")
  fi
done

if ((${#missing[@]})); then
  printf 'Missing required commands: %s\n' "${missing[*]}" >&2
  printf '%s\n' "On Omarchy, rerun: ./install.sh --with-deps" >&2
  exit 1
fi

if [[ " $(id -nG) " != *" input "* ]]; then
  printf '%s\n' \
    "Your current login does not have the input-group permission required by ydotool on Arch." \
    "Review the security note in README.md, then add the account and sign out/in:" \
    "  sudo usermod -aG input \"\$USER\"" >&2
  exit 1
fi

if command -v systemctl >/dev/null 2>&1 && \
    systemctl --user cat ydotool.service >/dev/null 2>&1; then
  systemctl --user enable --now ydotool.service
fi

if ! python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
  printf '%s\n' "Keyper requires Python 3.11 or newer." >&2
  exit 1
fi

install -d -- "$bin_dir"
if [[ -e "$installed_launcher" || -L "$installed_launcher" ]]; then
  current_target="$(readlink -f -- "$installed_launcher" 2>/dev/null || true)"
  expected_target="$(readlink -f -- "$source_launcher")"
  if [[ "$current_target" != "$expected_target" ]]; then
    printf 'Refusing to replace an existing command: %s\n' "$installed_launcher" >&2
    exit 1
  fi
fi

ln -sfn -- "$source_launcher" "$installed_launcher"
printf 'Installed Keyper launcher: %s -> %s\n' "$installed_launcher" "$source_launcher"

case ":${PATH}:" in
  *":${bin_dir}:"*) ;;
  *) printf 'Add %s to PATH before invoking keyper.\n' "$bin_dir" ;;
esac

"$installed_launcher" doctor
