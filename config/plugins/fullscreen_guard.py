"""Track visible fullscreen windows through compositor events, without polling clients."""
import json
import os
from pathlib import Path
import socket
import subprocess
from gi.repository import GLib


class FullscreenGuard:
    def __init__(self, app):
        self.app = app
        self.blocked = set()
        self.buffer = b''
        self.connection = None
        self.watch = 0
        self.timer = 0
        self.retry = GLib.timeout_add_seconds(3, self.connect)
        self.connect()
        self.refresh()

    def connect(self):
        if self.connection: return True
        path = Path(os.environ.get('XDG_RUNTIME_DIR', '/tmp')) / 'hypr' / os.environ.get('HYPRLAND_INSTANCE_SIGNATURE', '') / '.socket2.sock'
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.connect(str(path))
            connection.setblocking(False)
        except OSError:
            connection.close()
            return True
        self.connection = connection
        self.watch = GLib.io_add_watch(connection.fileno(), GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self.event)
        self.refresh()
        return True

    def event(self, _, condition):
        try:
            data = self.connection.recv(65536)
            if not data: raise ConnectionError()
        except BlockingIOError: return True
        except OSError:
            self.connection.close()
            self.connection = None
            self.watch = 0
            return False
        self.buffer += data
        lines = self.buffer.split(b'\n')
        self.buffer = lines.pop()
        for line in lines:
            if line.startswith(b'focusedmon>>'):
                name = line.split(b'>>', 1)[1].split(b',', 1)[0].decode(errors='replace')
                self.app.fracture.monitor_focused(name)
        if not self.timer: self.timer = GLib.timeout_add(50, self.refresh)
        return True

    def refresh(self):
        self.timer = 0
        try:
            monitors = json.loads(subprocess.check_output(['hyprctl', '-j', 'monitors'], text=True, timeout=1))
            clients = json.loads(subprocess.check_output(['hyprctl', '-j', 'clients'], text=True, timeout=1))
            blocked = set()
            for monitor in monitors:
                special = monitor.get('specialWorkspace', {}).get('id', 0)
                visible = special or monitor['activeWorkspace']['id']
                if any(client.get('mapped', True) and not client.get('hidden', False)
                       and client.get('workspace', {}).get('id') == visible
                       and client.get('monitor') == monitor['id']
                       and int(client.get('fullscreen', 0)) & 2 for client in clients):
                    blocked.add((monitor['x'], monitor['y']))
            self.blocked = blocked
        except (OSError, ValueError, subprocess.SubprocessError):
            return False
        for popup in self.app.popups:
            if self.is_blocked(popup):
                popup.hide()
                popup.inside.clear()
                if popup.open_timer:
                    GLib.source_remove(popup.open_timer)
                    popup.open_timer = 0
                popup.trigger.hide()
            elif not popup.trigger.get_visible():
                popup.trigger.show_all()
        return False

    def is_blocked(self, popup):
        geometry = popup.monitor.get_geometry()
        return (geometry.x, geometry.y) in self.blocked

    def close(self):
        for source in (self.watch, self.timer, self.retry):
            if source: GLib.source_remove(source)
        if self.connection: self.connection.close()
