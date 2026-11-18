#!/usr/bin/env bash
set -euo pipefail
ref=${G8D_REF:-v0.2.0-alpha.1}
[[ $ref =~ ^[A-Za-z0-9._-]+$ ]] || { echo 'Invalid release tag.' >&2; exit 2; }
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
curl --fail --show-error --location --retry 2 "https://codeload.github.com/G8Dman/hyprland-g8d/tar.gz/refs/tags/$ref" -o "$work/source.tar.gz"
mkdir "$work/source"
tar -xzf "$work/source.tar.gz" --strip-components=1 -C "$work/source"
bash "$work/source/install.sh" "$@"
