#!/usr/bin/env bash
set -euo pipefail
(( EUID == 0 )) || { echo 'Run this session-registration helper with sudo.' >&2; exit 1; }
# Only g8d-owned names are touched; no display manager is installed/restarted.
backup="/var/backups/hyprland-g8d/session-$(date +%Y%m%d-%H%M%S-%N)"
paths=(/usr/local/bin/hyprland-g8d-session /usr/share/wayland-sessions/hyprland-g8d.desktop)
work=()
published=()
cleanup() {
    local status=$? index path directory restore_failed=0
    trap - EXIT
    if (( status != 0 )); then
        for index in "${published[@]}"; do
            path=${paths[index]}
            directory=${work[index]}
            if [[ -e "$directory/previous" || -L "$directory/previous" ]]; then
                mv -fT -- "$directory/previous" "$path" || restore_failed=1
            else
                rm -f -- "$path" || restore_failed=1
            fi
        done
    fi
    if (( restore_failed )); then
        printf 'Session entry rollback failed. Inspect %s\n' "${work[@]}" >&2
    else
        for directory in "${work[@]}"; do rm -rf -- "$directory"; done
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

install -d -m 755 /usr/local/bin /usr/share/wayland-sessions
exec {session_lock}</usr/share/wayland-sessions
flock -x "$session_lock"
for path in "${paths[@]}"; do
    directory=$(mktemp -d "${path%/*}/.g8d-session.XXXXXXXX")
    work+=("$directory")
    if [[ -e "$path" || -L "$path" ]]; then
        install -d -m 700 "$backup" "$backup${path%/*}"
        cp -a -- "$path" "$backup$path"
        cp -a -- "$path" "$directory/previous"
    fi
done
cat > "${work[0]}/new" <<'EOF'
#!/bin/sh
exec "$HOME/.local/bin/hyprland-g8d"
EOF
chmod 755 "${work[0]}/new"
cat > "${work[1]}/new" <<'EOF'
[Desktop Entry]
Name=hyprland-g8d
Comment=g8d / graphite — experimental independent Hyprland session
Exec=/usr/local/bin/hyprland-g8d-session
TryExec=/usr/local/bin/hyprland-g8d-session
Type=Application
DesktopNames=Hyprland;
EOF
chmod 644 "${work[1]}/new"
for index in "${!paths[@]}"; do
    published+=("$index")
    mv -fT -- "${work[index]}/new" "${paths[index]}"
done
