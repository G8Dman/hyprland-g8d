#!/usr/bin/env python3
"""Stream workspace state for Waybar; refresh from Hyprland events."""
import json
import os
import socket
import subprocess
import sys
import time

slot = int(sys.argv[1])
if not 1 <= slot <= 5:
    raise SystemExit("Workspace slot must be between 1 and 5")

def active_workspace():
    return json.loads(subprocess.check_output(["hyprctl", "-j", "activeworkspace"], timeout=2))["id"]

def workspace_for_slot(active):
    return (max(1, active) - 1) // 5 * 5 + slot

if "--click" in sys.argv:
    target = workspace_for_slot(active_workspace())
    subprocess.run(["hyprctl", "dispatch", f"hl.dsp.focus({{workspace = {target}}})"], check=True)
    raise SystemExit(0)
def update():
    try:
        active = active_workspace()
        workspace = workspace_for_slot(active)
        spaces = json.loads(subprocess.check_output(["hyprctl", "-j", "workspaces"], timeout=2))
        occupied = any(w["id"] == workspace and w["windows"] > 0 for w in spaces)
        state = "active" if active == workspace else "occupied" if occupied else "empty"
        print(json.dumps({"text": str(workspace).zfill(2), "class": state,
                          "tooltip": f"Рабочий стол {workspace}" + (f" · Super+{workspace % 10}" if workspace <= 10 else "")}), flush=True)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass

if "--once" in sys.argv:
    update()
    raise SystemExit(0)

path = os.path.join(os.environ["XDG_RUNTIME_DIR"], "hypr", os.environ["HYPRLAND_INSTANCE_SIGNATURE"], ".socket2.sock")
while True:
    try:
        with socket.socket(socket.AF_UNIX) as sock:
            sock.connect(path)
            update()
            with sock.makefile() as stream:
                for event in stream:
                    if event.split(">>", 1)[0] in {"workspace", "workspacev2", "focusedmon", "focusedmonv2", "openwindow", "closewindow", "movewindow", "movewindowv2", "createworkspace", "destroyworkspace"}:
                        update()
            break
    except OSError:
        time.sleep(2)
