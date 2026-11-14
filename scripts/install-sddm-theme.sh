#!/usr/bin/env bash
set -euo pipefail
(( EUID == 0 )) || { echo 'Run: sudo bash scripts/install-sddm-theme.sh' >&2; exit 1; }
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
[[ -x /usr/bin/sddm-greeter-qt6 && -d /usr/lib/qt6/qml/QtQuick/VirtualKeyboard ]] || {
    echo 'Install SDDM and Qt Virtual Keyboard first: sudo pacman -S sddm qt6-virtualkeyboard' >&2; exit 1;
}
backup="/var/backups/hyprland-g8d/theme-$(date +%Y%m%d-%H%M%S)"
install -d -m 700 "$backup"
for path in /usr/share/sddm/themes/g8d /etc/sddm.conf.d/90-g8d-theme.conf; do
    if [[ -e $path ]]; then cp -a --parents "$path" "$backup/"; fi
done
install -d -m 755 /usr/share/sddm/themes/g8d /etc/sddm.conf.d
install -m 644 "$root"/extras/sddm/g8d/{Main.qml,theme.conf,metadata.desktop} /usr/share/sddm/themes/g8d/
printf '[Theme]\nCurrent=g8d\n' > /etc/sddm.conf.d/90-g8d-theme.conf
echo "Theme installed for the next login. Backup: $backup"
echo 'Display manager, display backend, PAM and current session were not changed.'
