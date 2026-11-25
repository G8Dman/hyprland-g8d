#!/usr/bin/env python3
"""g8d hover panels. Each monitor has independent pointer-safe popups."""
from concurrent.futures import ThreadPoolExecutor
import datetime
import json
import os
from pathlib import Path
import signal
import cairo
import socket
import subprocess
import sys

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GtkLayerShell', '0.1')
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, GtkLayerShell as Layer, Pango
from data import Collector, media_control
import gaming
import appearance
import ui_themes
import branding
import brightness
from window_switcher import WindowSwitcher
from calendar_sync import CalendarSync
from dashboard import Dashboard
from fullscreen_guard import FullscreenGuard
from quick_settings import QuickSettings
from cursor_fracture import Fracture

ROOT = Path(__file__).resolve().parent
SESSION = os.environ.get('HYPRLAND_INSTANCE_SIGNATURE', 'default')
SOCKET = Path(os.environ.get('XDG_RUNTIME_DIR', '/tmp')) / f'g8d-panels-{os.getuid()}-{SESSION}.sock'


def label(text='', style='', wrap=False):
    widget = Gtk.Label(label=text, xalign=0)
    widget.set_line_wrap(wrap)
    widget.set_max_width_chars(58)
    widget.set_ellipsize(Pango.EllipsizeMode.END if not wrap else Pango.EllipsizeMode.NONE)
    if style: widget.get_style_context().add_class(style)
    return widget


def box(vertical=True, spacing=8):
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL, spacing=spacing)


def row(parent, left, right, style='value'):
    line = box(False)
    line.pack_start(label(left), True, True, 0)
    value = label(right, style)
    value.set_xalign(1)
    line.pack_end(value, False, False, 0)
    parent.pack_start(line, False, False, 0)
    return value


def button(text, callback):
    widget = Gtk.Button(label=text)
    widget.connect('clicked', lambda *_: callback())
    return widget


def initials_avatar(name):
    widget = Gtk.DrawingArea()
    widget.set_size_request(64, 64)
    def draw(_, context):
        context.set_source_rgb(.18, .27, .28)
        context.arc(32, 32, 31, 0, 6.2832)
        context.fill()
        context.set_source_rgb(.65, .82, .80)
        context.select_font_face('DejaVu Sans')
        context.set_font_size(24)
        initials = ''.join(part[0] for part in name.split()[:2]).upper()
        extents = context.text_extents(initials)
        context.move_to(32 - extents.width / 2 - extents.x_bearing, 32 - extents.height / 2 - extents.y_bearing)
        context.show_text(initials)
        return False
    widget.connect('draw', draw)
    return widget


class Popup:
    def __init__(self, app, monitor, index, kind):
        self.app, self.index, self.kind = app, index, kind
        self.monitor = monitor
        self.dashboard = None
        self.quick_settings = None
        self.inside = set()
        self.close_timer = 0
        self.open_timer = 0
        self.player = None
        self.preferred_player = None
        self.process_expanded = False
        self.brightness_dragging = False
        self.brightness_timers = {}
        self.brightness_scales = {}
        self.data = {}
        self.window = self.surface(monitor, f'g8d-{kind}', popup=True)
        self.dashboard_width = min(820, monitor.get_geometry().width - 48)
        self.window.set_size_request(360 if kind == 'profile' else self.dashboard_width, -1)
        Layer.set_margin(self.window, Layer.Edge.TOP, 36)
        if kind == 'profile':
            Layer.set_anchor(self.window, Layer.Edge.RIGHT, True)
            Layer.set_margin(self.window, Layer.Edge.RIGHT, 8)
            Layer.set_margin(self.window, Layer.Edge.TOP, 44)
        self.body = box(spacing=12)
        self.body.get_style_context().add_class('body')
        popup_area = Gtk.EventBox()
        popup_area.set_visible_window(False)
        popup_area.add(self.body)
        self.window.add(popup_area)
        # Track the toplevel surface; the transparent EventBox has no native window.
        self.bind_pointer(self.window, 'popup')
        self.trigger = self.surface(monitor, f'g8d-trigger-{kind}', popup=False)
        self.trigger.set_size_request(44 if kind == 'profile' else 112, 36)
        if kind == 'profile': Layer.set_anchor(self.trigger, Layer.Edge.RIGHT, True)
        area = Gtk.EventBox()
        area.set_visible_window(False)
        self.trigger.add(area)
        self.bind_pointer(self.trigger, 'trigger')
        self.trigger.connect('button-press-event', self.click)
        self.trigger.show_all()
        self.render({})

    def surface(self, monitor, namespace, popup):
        window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        window.set_decorated(False)
        window.set_app_paintable(True)
        visual = window.get_screen().get_rgba_visual()
        if visual: window.set_visual(visual)
        window.get_style_context().add_class('g8d-popup' if popup else 'g8d-trigger')
        if popup: window.connect('draw', self.draw_surface)
        Layer.init_for_window(window)
        Layer.set_namespace(window, namespace)
        Layer.set_monitor(window, monitor)
        Layer.set_layer(window, Layer.Layer.OVERLAY)
        Layer.set_keyboard_mode(window, Layer.KeyboardMode.NONE)
        # Ignore Waybar's reserved 36px area: triggers must overlap the bar,
        # and popups add their own exact 36px top margin.
        Layer.set_exclusive_zone(window, -1)
        Layer.set_anchor(window, Layer.Edge.TOP, True)
        return window

    @staticmethod
    def draw_surface(window, context):
        # Clear the entire RGBA buffer, then let GTK paint the CSS rounded surface.
        # A default GtkWindow background otherwise leaves an opaque rectangle behind it.
        context.save()
        context.set_operator(cairo.OPERATOR_SOURCE)
        context.set_source_rgba(0, 0, 0, 0)
        context.paint()
        context.restore()
        style = window.get_style_context()
        width, height = window.get_allocated_width(), window.get_allocated_height()
        Gtk.render_background(style, context, 0, 0, width, height)
        Gtk.render_frame(style, context, 0, 0, width, height)
        return False

    def bind_pointer(self, widget, region):
        widget.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK | Gdk.EventMask.BUTTON_PRESS_MASK)
        widget.connect('enter-notify-event', lambda _, e: self.cross(region, True, e))
        widget.connect('leave-notify-event', lambda _, e: self.cross(region, False, e))

    def cross(self, region, entering, event):
        # Ignore crossings between a popup and its child buttons/labels.
        if event.detail == Gdk.NotifyType.INFERIOR: return False
        if self.blocked(): return False
        if entering:
            self.inside.add(region)
            if self.close_timer:
                GLib.source_remove(self.close_timer)
                self.close_timer = 0
            if region == 'trigger' and not self.window.get_visible() and not self.open_timer:
                self.open_timer = GLib.timeout_add(140, self.open_hover)
        else:
            self.inside.discard(region)
            if self.open_timer:
                GLib.source_remove(self.open_timer)
                self.open_timer = 0
            if not self.inside and not self.close_timer:
                self.close_timer = GLib.timeout_add(350, self.close_hover)
        return False

    def open_hover(self):
        self.open_timer = 0
        if 'trigger' in self.inside: self.show()
        return False

    def close_hover(self):
        self.close_timer = 0
        if self.brightness_dragging or (self.quick_settings and self.quick_settings.page_holds_pointer()):
            self.close_timer = GLib.timeout_add(350, self.close_hover)
            return False
        if not self.inside: self.hide()
        return False

    def blocked(self):
        guard = getattr(self.app, 'fullscreen', None)
        return bool(guard and guard.is_blocked(self))

    def click(self, _, event):
        if self.blocked(): return True
        if event.button == 1:
            if self.window.get_visible(): self.hide()
            else: self.show()
        elif event.button == 3 and self.kind == 'profile':
            self.launch([str(ROOT.parent / 'actions'), 'power'])
        return True

    def show(self):
        guard = getattr(self.app, 'fullscreen', None)
        if guard: guard.refresh()
        if self.blocked(): return
        for popup in self.app.popups:
            if popup is not self: popup.hide()
        self.window.show_all()
        if self.quick_settings:
            self.render(getattr(self.app, 'profile_data', self.data))
        self.app.calendar.refresh()
        self.app.refresh()

    def hide(self):
        self.window.hide()
        self.inside.discard('popup')

    def destroy(self):
        for timer in self.brightness_timers.values(): GLib.source_remove(timer)
        self.brightness_timers.clear()
        for timer in [self.open_timer, self.close_timer]:
            if timer: GLib.source_remove(timer)
        self.trigger.destroy()
        self.window.destroy()

    def launch(self, command):
        self.hide()
        try: subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc: self.app.notify(str(exc))

    def section(self, title):
        if self.body.get_children(): self.body.pack_start(Gtk.Separator(), False, False, 0)
        self.body.pack_start(label(title, 'heading'), False, False, 0)

    def render(self, data):
        self.data = data
        if self.kind == 'dashboard':
            if self.dashboard is None:
                self.dashboard = Dashboard(self, self.dashboard_width)
                self.body.pack_start(self.dashboard.root, True, True, 0)
                Layer.set_keyboard_mode(self.window, Layer.KeyboardMode.ON_DEMAND)
            self.dashboard.update(data)
            self.body.show_all()
            return
        if self.quick_settings is None:
            self.quick_settings = QuickSettings(self)
            self.body.pack_start(self.quick_settings.root, False, False, 0)
        self.quick_settings.update(data)
        self.body.show_all()

    def brightness_changed(self, scale, output, value_label):
        percent = round(scale.get_value())
        value_label.set_text(f'{percent}%')
        self.app.brightness_overrides[output] = percent
        if output in self.brightness_timers: GLib.source_remove(self.brightness_timers[output])
        def send():
            self.brightness_timers.pop(output, None)
            self.app.brightness_writer.request(output, percent)
            return False
        self.brightness_timers[output] = GLib.timeout_add(180, send)

    def brightness_pointer(self, pressed):
        self.brightness_dragging = pressed
        return False

    def cursor_effect_changed(self, switch, _):
        if switch.get_active() == self.app.fracture.enabled: return
        try: self.app.fracture.set_enabled(switch.get_active())
        except OSError:
            switch.set_active(self.app.fracture.enabled)
            self.app.notify('Не удалось сохранить настройку эффекта курсора')

    def render_music(self, data, parent):
        self.dashboard.music_view.update(data)

    def open_yandex_music(self):
        self.hide()
        self.app.music_command([sys.executable, str(ROOT / 'yandex_music.py'), 'show'], 'Открываю приложение…', timeout=15)

    def play_yandex(self, action):
        print(f'g8d music preset: {action}', flush=True)
        self.preferred_player = None
        message = {'wave': 'Запускаю «Мою волну»…', 'favorites': 'Загружаю любимые треки…',
                   'background': 'Запускаю плеер…'}[action]
        self.app.music_command([sys.executable, str(ROOT / 'yandex_music.py'), action], message)

    def select_player(self, selector):
        selected = selector.get_active_id()
        self.preferred_player = None if selected == 'auto' else selected
        self.render(self.data)


class App:
    def __init__(self):
        self.collector = Collector()
        self.calendar = CalendarSync()
        self.calendar.refresh()
        GLib.timeout_add_seconds(300, self.sync_calendar)
        self.brightness_overrides = {}
        self.brightness_writer = brightness.Writer(lambda output, value, error: GLib.idle_add(self.brightness_done, output, value, error))
        self.game_state = gaming.read_state()
        self.game_pending = False
        self.game_bars = []
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.profile_pool = ThreadPoolExecutor(max_workers=2)
        self.action_pool = ThreadPoolExecutor(max_workers=2)
        self.music_pool = ThreadPoolExecutor(max_workers=1)
        self.music_pending = False
        self.music_message = ''
        self.music_error = ''
        self.pending = False
        self.profile_pending = set()
        self.profile_data = {}
        self.monitor_timer = 0
        self.popups = []
        css = Gtk.CssProvider()
        self.css = css
        css.load_from_path(str(appearance.ROOT / 'plugins/style.css'))
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        Gtk.IconTheme.get_default().prepend_search_path(str(ROOT / 'icons'))
        self.dashboard_css = Gtk.CssProvider()
        self.dashboard_css.load_from_path(str(ROOT / 'dashboard-material.css'))
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), self.dashboard_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self.quick_css = Gtk.CssProvider()
        self.quick_css.load_from_path(str(ROOT / 'quick-settings.css'))
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), self.quick_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self.interface_css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), self.interface_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 2)
        self.reload_interface()
        self.display = Gdk.Display.get_default()
        self.display.connect('monitor-added', lambda *_: self.monitors_changed())
        self.display.connect('monitor-removed', lambda *_: self.monitors_changed())
        self.fracture = Fracture(self)
        self.rebuild()
        self.fullscreen = FullscreenGuard(self)
        self.switcher = WindowSwitcher(self.display)
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        # There must only be one panel daemon per compositor session.
        if SOCKET.exists():
            try:
                self.socket.sendto(b'ping', str(SOCKET))
                raise RuntimeError('g8d panels already running for this session')
            except ConnectionRefusedError: SOCKET.unlink()
        self.socket.bind(str(SOCKET))
        SOCKET.chmod(0o600)
        GLib.io_add_watch(self.socket.fileno(), GLib.IO_IN, self.message)
        GLib.timeout_add_seconds(2, self.refresh)
        GLib.timeout_add_seconds(30, self.game_clock)

    def sync_calendar(self):
        self.calendar.refresh()
        return True

    def rebuild(self):
        for window in self.game_bars: window.destroy()
        self.game_bars = []
        for popup in self.popups: popup.destroy()
        self.popups = [Popup(self, monitor, i, kind)
                       for i, monitor in self.connected_monitors() for kind in ('profile', 'dashboard')]
        self.build_game_bars()
        if hasattr(self, 'fullscreen'): self.fullscreen.refresh()

    def monitors_changed(self):
        if self.monitor_timer:
            GLib.source_remove(self.monitor_timer)
        self.monitor_timer = GLib.timeout_add(300, self.rebuild_after_hotplug)

    def connected_monitors(self):
        for i in range(self.display.get_n_monitors()):
            monitor = self.display.get_monitor(i)
            if monitor and monitor.get_geometry().width >= 48:
                yield i, monitor

    def rebuild_after_hotplug(self):
        self.monitor_timer = 0
        self.fracture.clear()
        self.rebuild()
        def work():
            try:
                with appearance.locked(): appearance.start()
            except Exception as exc:
                print(f'g8d wallpaper hotplug: {exc}', file=sys.stderr, flush=True)
        self.pool.submit(work)
        return GLib.SOURCE_REMOVE

    def build_game_bars(self):
        for window in self.game_bars: window.destroy()
        self.game_bars = []
        if not self.game_state.get('enabled'): return
        for i, monitor in self.connected_monitors():
            popup = next(p for p in self.popups if p.index == i and p.kind == 'profile')
            window = popup.surface(monitor, 'g8d-game-bar', popup=True)
            window.get_style_context().add_class('game-bar')
            Layer.set_layer(window, Layer.Layer.TOP)
            Layer.set_anchor(window, Layer.Edge.LEFT, True)
            Layer.set_anchor(window, Layer.Edge.RIGHT, True)
            Layer.set_exclusive_zone(window, 36)
            window.set_size_request(-1, 36)
            layout = Gtk.Grid()
            layout.set_column_homogeneous(True)
            left, middle, right = box(False), box(False), box(False)
            left.pack_start(label(branding.read()+' / GAME', 'value'), False, False, 14)
            middle.pack_start(label(datetime.datetime.now().strftime('%H:%M')), False, False, 0)
            right.pack_end(label('⏻'), False, False, 16)
            middle.set_halign(Gtk.Align.CENTER)
            layout.attach(left, 0, 0, 1, 1)
            layout.attach(middle, 1, 0, 1, 1)
            layout.attach(right, 2, 0, 1, 1)
            left.set_hexpand(True)
            right.set_hexpand(True)
            window.add(layout)
            window.clock_label = middle.get_children()[0]
            window.show_all()
            self.game_bars.append(window)

    def game_clock(self):
        for window in self.game_bars:
            window.clock_label.set_text(datetime.datetime.now().strftime('%H:%M'))
        return True

    def toggle_game(self):
        if self.game_pending: return
        self.game_pending = True
        for popup in self.popups:
            if popup.kind == 'profile': popup.render(popup.data)
        future = self.pool.submit(gaming.set_enabled, not self.game_state.get('enabled', False))
        future.add_done_callback(lambda result: GLib.idle_add(self.game_done, result))

    def game_done(self, result):
        self.game_pending = False
        try:
            self.game_state = result.result()
            self.build_game_bars()
            self.collector.processes.clear()
            for popup in self.popups:
                if popup.kind == 'profile': popup.render(popup.data)
                elif not popup.window.get_visible(): popup.render({})
            if os.environ.get('G8D_PREVIEW') == '1':
                (ROOT.parent / 'preview-game-state.json').write_text(json.dumps(self.game_state, indent=2))
            self.refresh()
        except Exception as exc:
            self.game_state = gaming.read_state()
            print(f'g8d game mode: {exc}', file=sys.stderr, flush=True)
            self.notify(f'Игровой режим: {exc}')
        return False

    def reload_interface(self):
        if appearance.interface_style() == 'nothing':
            self.interface_css.load_from_path(str(ROOT / 'nothing.css'))
        else: self.interface_css.load_from_data(b'')
        for popup in self.popups:
            if popup.dashboard: popup.dashboard.restyle()

    def message(self, *_):
        try:
            message = json.loads(self.socket.recv(65536))
            if "switcher" in message: self.switcher.update(message["switcher"])
            if message.get('appearance') == 'reload':
                self.css.load_from_path(str(appearance.ROOT / 'plugins/style.css'))
                self.reload_interface()
            if message.get('branding') == 'reload': self.build_game_bars()
            if message.get('game') == 'toggle': self.toggle_game()
            if message.get('sound') == 'toggle': self.sound_popup(message.get('cursor'))
            if isinstance(message.get('cursor_effect'), bool): self.fracture.set_enabled(message['cursor_effect'], persist=False)
            if isinstance(message.get('brightness'), dict):
                values = message['brightness']
                for popup in self.popups:
                    if popup.kind == 'profile':
                        for output, value in values.items():
                            if output in popup.brightness_scales:
                                popup.brightness_scales[output].set_value(float(value))
                        break
            kind = message.get('show')
            for popup in self.popups:
                if popup.kind == kind and popup.index == int(message.get('monitor', 0)):
                    popup.show()
                    break
                if message.get('hide'): popup.hide()
        except (ValueError, OSError, AttributeError): pass
        return True

    def popup_under_cursor(self, kind, cursor):
        profiles = [popup for popup in self.popups if popup.kind == kind]
        if not profiles:
            return
        if isinstance(cursor, dict):
            x, y = cursor.get('x'), cursor.get('y')
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                for profile in profiles:
                    bounds = profile.monitor.get_geometry()
                    if bounds.x <= x < bounds.x + bounds.width and bounds.y <= y < bounds.y + bounds.height:
                        return profile
        return profiles[0]

    def sound_popup(self, cursor):
        popup = self.popup_under_cursor('profile', cursor)
        if not popup:
            return
        if popup.window.get_visible() and popup.quick_settings.sound_active():
            popup.hide()
            return
        popup.show()
        if popup.window.get_visible():
            popup.quick_settings.show_sound()

    def refresh(self):
        opened = next((p for p in self.popups if p.window.get_visible()), None)
        if opened and opened.kind == 'profile':
            for name, collect in (('status', self.collector.quick_status),
                                  ('brightness', brightness.read)):
                if name not in self.profile_pending:
                    self.profile_pending.add(name)
                    future = self.profile_pool.submit(collect)
                    future.add_done_callback(lambda result, section=name: GLib.idle_add(self.update_profile, section, result))
        elif opened and not self.pending:
            self.pending = True
            future = self.pool.submit(self.collector.collect, opened.kind)
            future.add_done_callback(lambda result: GLib.idle_add(self.update, opened, result))
        return True

    def update_profile(self, section, result):
        self.profile_pending.discard(section)
        try:
            data = result.result()
            self.profile_data.update(data if section == 'status' else {'brightness': data})
            for popup in self.popups:
                if popup.kind == 'profile' and popup.window.get_visible() and not popup.brightness_dragging:
                    popup.render(self.profile_data)
                    if os.environ.get('G8D_PREVIEW') == '1':
                        (ROOT.parent / 'preview-profile.json').write_text(json.dumps(self.profile_data, ensure_ascii=False, indent=2))
        except Exception as exc:
            print(f'g8d quick settings ({section}): {exc}', file=sys.stderr, flush=True)
        return GLib.SOURCE_REMOVE

    def update(self, popup, result):
        self.pending = False
        try:
            data = result.result()
            if popup in self.popups and popup.window.get_visible() and not popup.brightness_dragging:
                popup.render(data)
                if os.environ.get('G8D_PREVIEW') == '1':
                    (ROOT.parent / f'preview-{popup.kind}.json').write_text(json.dumps(data, ensure_ascii=False, indent=2))
        except Exception as exc:
            print(f'g8d panels: {exc}', file=sys.stderr, flush=True)
        return False

    def brightness_done(self, output, value, error):
        self.brightness_overrides.pop(output, None)
        if error:
            self.notify(f'Яркость {output}: {error}')
        for popup in self.popups:
            if popup.kind != 'profile': continue
            for monitor in popup.data.get('brightness', []):
                if monitor['output'] == output and value is not None: monitor['percent'] = value
        self.refresh()
        return False

    def notify(self, text):
        subprocess.Popen(['notify-send', 'g8d', text])

    def action(self, command, timeout=8, done=None):
        def finished(error):
            if error: self.notify(error)
            if done: done(error)
            self.refresh()
            return False
        def work():
            error = ''
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
                if result.returncode:
                    error = result.stderr.strip() or result.stdout.strip() or 'Действие не выполнено'
            except (OSError, subprocess.SubprocessError) as exc:
                error = str(exc)
            GLib.idle_add(finished, error)
        self.action_pool.submit(work)

    def music_command(self, command, message, timeout=100):
        if self.music_pending:
            return
        self.music_pending = True
        self.music_message = message
        self.music_error = ''
        GLib.idle_add(self.render_music_state)
        def work():
            error = ''
            try:
                if callable(command):
                    command()
                else:
                    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
                    if result.returncode:
                        error = result.stderr.strip() or 'Действие не выполнено'
            except (GLib.Error, OSError, subprocess.SubprocessError, ValueError, RuntimeError) as exc:
                error = str(exc)
            GLib.idle_add(self.music_done, error)
        self.music_pool.submit(work)

    def render_music_state(self):
        for popup in self.popups:
            if popup.kind == 'dashboard' and popup.window.get_visible():
                popup.render(popup.data)
        return False

    def music_done(self, error):
        self.music_pending = False
        self.music_error = error[:300]
        if error:
            print('g8d music: ' + error, file=sys.stderr, flush=True)
            self.notify(self.music_error)
        self.render_music_state()
        self.refresh()
        return False

    def music(self, name, method):
        self.music_command(lambda: media_control(name, method), 'Выполняю команду…', timeout=4)

    def close(self):
        self.fracture.close()
        self.fullscreen.close()
        self.switcher.close()
        self.brightness_writer.close()
        self.socket.close()
        SOCKET.unlink(missing_ok=True)
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.profile_pool.shutdown(wait=False, cancel_futures=True)
        self.action_pool.shutdown(wait=False, cancel_futures=True)
        self.music_pool.shutdown(wait=False, cancel_futures=True)
        Gtk.main_quit()
        return False


def cli_message(args):
    action = args[0]
    if action == 'sound':
        try:
            cursor = json.loads(subprocess.check_output(
                ['hyprctl', '-j', 'cursorpos'], text=True, stderr=subprocess.DEVNULL, timeout=1))
        except (OSError, ValueError, subprocess.SubprocessError):
            cursor = None
        return {action: 'toggle', 'cursor': cursor}
    if action == 'game':
        return {'game': 'toggle'}
    if action == 'hide':
        return {'hide': True}
    return {'show': action, 'monitor': int(args[1]) if len(args) > 1 else 0}


if __name__ == '__main__':
    if len(sys.argv) > 1:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as connection:
            connection.sendto(json.dumps(cli_message(sys.argv[1:])).encode(), str(SOCKET))
    else:
        Gtk.init(None)
        if not Layer.is_supported(): raise SystemExit('g8d panels require Wayland Layer Shell')
        app = App()
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, app.close)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, app.close)
        Gtk.main()
