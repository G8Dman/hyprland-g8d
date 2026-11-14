#!/usr/bin/env bash
set -euo pipefail
if [[ ${1:-} != --yes ]]; then
    echo 'This removes only g8d launchers and its session entry. Config is kept by default.'
    echo 'Run: bash uninstall.sh --yes'
    exit 0
fi
rm -f -- "$HOME/.local/bin/hyprland-g8d" "$HOME/.local/bin/g8d-settings" "$HOME/.local/share/applications/g8d-settings.desktop"
sudo rm -f -- /usr/local/bin/hyprland-g8d-session /usr/share/wayland-sessions/hyprland-g8d.desktop
if command -v update-desktop-database >/dev/null; then update-desktop-database "$HOME/.local/share/applications"; fi
echo 'Session removed. Your configuration, backups and wallpapers are preserved.'
echo 'To remove your g8d config manually: rm -rf ~/.config/hyprland-g8d ~/.local/share/hyprland-g8d/venv'
echo 'Other user accounts using the shared hyprland-g8d session entry will need to register it again.'
