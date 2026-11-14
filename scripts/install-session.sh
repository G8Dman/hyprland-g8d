#!/usr/bin/env bash
set -euo pipefail
(( EUID == 0 )) || { echo 'Run this session-registration helper with sudo.' >&2; exit 1; }
# Only g8d-owned names are touched; no display manager is installed/restarted.
backup="/var/backups/hyprland-g8d/session-$(date +%Y%m%d-%H%M%S)"
for path in /usr/local/bin/hyprland-g8d-session /usr/share/wayland-sessions/hyprland-g8d.desktop; do
    if [[ -e $path ]]; then install -d -m 700 "$backup"; cp -a --parents "$path" "$backup/"; fi
done
install -d -m 755 /usr/local/bin /usr/share/wayland-sessions
cat > /usr/local/bin/hyprland-g8d-session <<'EOF'
#!/bin/sh
exec "$HOME/.local/bin/hyprland-g8d"
EOF
chmod 755 /usr/local/bin/hyprland-g8d-session
cat > /usr/share/wayland-sessions/hyprland-g8d.desktop <<'EOF'
[Desktop Entry]
Name=hyprland-g8d
Comment=g8d / graphite — experimental independent Hyprland session
Exec=/usr/local/bin/hyprland-g8d-session
TryExec=/usr/local/bin/hyprland-g8d-session
Type=Application
DesktopNames=Hyprland;
EOF
