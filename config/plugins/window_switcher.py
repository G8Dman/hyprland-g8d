"""Centered window chooser; focus stays in the app until Alt is released."""
import json
import subprocess
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GtkLayerShell', '0.1')
from gi.repository import Gtk, GtkLayerShell as Layer, Pango


class WindowSwitcher:
    def __init__(self, display):
        self.display = display
        self.window = None
        self.sequence = -1

    def close(self):
        if self.window:
            self.window.destroy()
            self.window = None

    def update(self, state):
        if state['sequence'] <= self.sequence:
            return
        self.sequence = state['sequence']
        if not state['index']:
            self.close()
            return
        clients = {w['address']: w for w in json.loads(subprocess.check_output(
            ['hyprctl', '-j', 'clients'], timeout=2))}
        if not self.window:
            monitors = json.loads(subprocess.check_output(['hyprctl', '-j', 'monitors'], timeout=2))
            focused = next((m['name'] for m in monitors if m['focused']), None)
            monitor = next((self.display.get_monitor(i) for i in range(self.display.get_n_monitors())
                            if self.display.get_monitor(i).get_model() == focused), None)
            # GDK may expose EDID model rather than connector: use coordinates as fallback.
            if monitor is None:
                output = next((m for m in monitors if m['focused']), monitors[0])
                monitor = self.display.get_monitor_at_point(output['x'] + 1, output['y'] + 1)
            self.monitor = monitor
            self.window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
            self.window.set_decorated(False)
            self.window.get_style_context().add_class('g8d-popup')
            Layer.init_for_window(self.window)
            Layer.set_namespace(self.window, 'g8d-window-switcher')
            Layer.set_monitor(self.window, monitor)
            Layer.set_layer(self.window, Layer.Layer.OVERLAY)
            Layer.set_exclusive_zone(self.window, -1)
            Layer.set_keyboard_mode(self.window, Layer.KeyboardMode.NONE)
        child = self.window.get_child()
        if child:
            self.window.remove(child)
            child.destroy()
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        body.get_style_context().add_class('window-switcher')
        body.pack_start(Gtk.Label(label='Открытые окна · Alt+Tab'), False, False, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_propagate_natural_height(True)
        height = min(560, self.monitor.get_geometry().height - 100, max(58, len(state["addresses"]) * 58))
        scroll.set_min_content_height(height)
        scroll.set_max_content_height(height)
        rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        selected = None
        for index, address in enumerate(state['addresses'], 1):
            client = clients.get(address)
            if not client:
                continue
            button = Gtk.Button()
            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            line.pack_start(Gtk.Image.new_from_icon_name(client['class'], Gtk.IconSize.LARGE_TOOLBAR), False, False, 0)
            text = Gtk.Label(label=client['title'], xalign=0)
            text.set_ellipsize(Pango.EllipsizeMode.END)
            text.set_max_width_chars(60)
            text.set_width_chars(42)
            line.pack_start(text, True, True, 0)
            line.pack_end(Gtk.Label(label=str(client['workspace']['id'])), False, False, 0)
            button.add(line)
            button.connect('clicked', lambda _, i=index: subprocess.Popen(
                ['hyprctl', 'eval', f'g8d_switch_commit({i})'], stdout=subprocess.DEVNULL))
            if index == state['index']:
                button.get_style_context().add_class('switcher-selected')
                selected = button
            rows.pack_start(button, False, False, 0)
        scroll.add(rows)
        body.pack_start(scroll, True, True, 0)
        self.window.add(body)
        self.window.show_all()
        if selected:
            selected.grab_focus()
