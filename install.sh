#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if ! command -v python3 >/dev/null; then
    command -v pacman >/dev/null || { echo 'Supported installer: Arch Linux / CachyOS.' >&2; exit 1; }
    sudo pacman -S --needed python
fi
exec python3 "$root/scripts/install.py" "$@"
