#!/usr/bin/env python3
"""Send an ordered switcher update without loading GTK in a helper process."""
import json, os, socket, sys
path = f"{os.environ['XDG_RUNTIME_DIR']}/g8d-panels-{os.getuid()}-{os.environ['HYPRLAND_INSTANCE_SIGNATURE']}.sock"
packet = {'switcher': {'sequence': int(sys.argv[1]), 'index': int(sys.argv[2]), 'addresses': sys.argv[3:]}}
with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as connection:
    connection.sendto(json.dumps(packet).encode(), path)
