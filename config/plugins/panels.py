#!/usr/bin/env python3
"""g8d hover panels. Each monitor has independent pointer-safe popups."""
from concurrent.futures import ThreadPoolExecutor
import datetime
import json
import os
from pathlib import Path
import signal
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
import brightness
from window_switcher import WindowSwitcher
from calendar_sync import CalendarSync
from dashboard import Dashboard
from fullscreen_guard import FullscreenGuard
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
        self.window.set_size_request(340 if kind == 'profile' else self.dashboard_width, -1)
        Layer.set_margin(self.window, Layer.Edge.TOP, 36)
        if kind == 'profile':
            Layer.set_anchor(self.window, Layer.Edge.RIGHT, True)
            Layer.set_margin(self.window, Layer.Edge.RIGHT, 0)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_propagate_natural_height(True)
        content_height = max(180, min(650 if kind == 'profile' else 680, monitor.get_geometry().height - 54))
        scroller.set_min_content_height(content_height)
        scroller.set_max_content_height(content_height)
        self.body = box(spacing=12)
        self.body.get_style_context().add_class('body')
        if kind == 'profile': scroller.add(self.body)
        popup_area = Gtk.EventBox()
        popup_area.set_visible_window(True)
        popup_area.add(scroller if kind == 'profile' else self.body)
        self.window.add(popup_area)
        self.bind_pointer(popup_area, 'popup')
        self.trigger = self.surface(monitor, f'g8d-trigger-{kind}', popup=False)
        self.trigger.set_size_request(44 if kind == 'profile' else 112, 36)
        if kind == 'profile': Layer.set_anchor(self.trigger, Layer.Edge.RIGHT, True)
        area = Gtk.EventBox()
        area.set_visible_window(False)
        self.trigger.add(area)
        self.bind_pointer(area, 'trigger')
        area.connect('button-press-event', self.click)
        self.trigger.show_all()
        self.render({})

    def surface(self, monitor, namespace, popup):
        window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        window.set_decorated(False)
        window.set_app_paintable(not popup)
        visual = window.get_screen().get_rgba_visual()
        if visual: window.set_visual(visual)
        window.get_style_context().add_class('g8d-popup' if popup else 'g8d-trigger')
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
        if self.brightness_dragging:
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
            if self.kind == 'profile': self.launch([str(ROOT.parent / 'actions'), 'power'])
            elif self.window.get_visible(): self.hide()
            else: self.show()
        return True

    def show(self):
        guard = getattr(self.app, 'fullscreen', None)
        if guard: guard.refresh()
        if self.blocked(): return
        for popup in self.app.popups:
            if popup is not self: popup.hide()
        self.window.show_all()
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
        for child in self.body.get_children(): child.destroy()
        if self.kind == 'profile': self.render_profile(data)
        else: self.render_dashboard(data)
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

    def render_profile(self, data):
        self.section('ПРОФИЛЬ')
        head = box(False, 14)
        name = data.get('name', self.app.collector.user['name'])
        avatar = data.get('avatar', self.app.collector.user['avatar'])
        if avatar:
            try: image = Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(avatar, 64, 64, True))
            except GLib.Error: image = initials_avatar(name)
        else: image = initials_avatar(name)
        head.pack_start(image, False, False, 0)
        info = box(spacing=4)
        info.pack_start(label(name, 'title'), False, False, 0)
        info.pack_start(label(f"{data.get('user', self.app.collector.user['user'])}@{data.get('host', self.app.collector.user['host'])}", 'muted'), False, False, 0)
        head.pack_start(info, True, True, 0)
        self.body.pack_start(head, False, False, 0)
        self.body.pack_start(label(data.get('os', self.app.collector.user['os']), 'muted'), False, False, 0)
        minutes = data.get('uptime', 0) // 60
        row(self.body, 'Сессия', 'hyprland-g8d')
        row(self.body, 'Время работы ПК', f'{minutes // 60} ч {minutes % 60} мин')
        effects = box(False)
        effects.pack_start(label('Эффект перехода курсора'), True, True, 0)
        switch = Gtk.Switch()
        switch.set_active(self.app.fracture.enabled)
        switch.set_valign(Gtk.Align.CENTER)
        switch.connect('notify::active', self.cursor_effect_changed)
        effects.pack_end(switch, False, False, 0)
        self.body.pack_start(effects, False, False, 0)
        self.body.pack_start(button('Настройки g8d', lambda: self.launch([str(ROOT.parent / 'actions'), 'settings'])), False, False, 0)
        self.section('ЯРКОСТЬ ЭКРАНОВ')
        self.brightness_scales = {}
        for monitor in data.get('brightness', []):
            output = monitor['output']
            percent = self.app.brightness_overrides.get(output, monitor['percent'])
            value_label = row(self.body, monitor['title'], f'{percent}%')
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 100, 1)
            scale.set_draw_value(False)
            scale.set_value(percent)
            scale.set_sensitive(monitor['enabled'])
            scale.connect('value-changed', self.brightness_changed, output, value_label)
            scale.connect('button-press-event', lambda *_: self.brightness_pointer(True))
            scale.connect('button-release-event', lambda *_: self.brightness_pointer(False))
            self.brightness_scales[output] = scale
            self.body.pack_start(scale, False, False, 0)
            if not monitor['enabled']:
                self.body.pack_start(label('Управление недоступно · проверь DDC/CI в меню монитора', 'muted', True), False, False, 0)
        if not data.get('brightness'):
            self.body.pack_start(label('Определяю мониторы…', 'muted'), False, False, 0)
        self.section('ИГРОВОЙ РЕЖИМ')
        enabled = self.app.game_state.get('enabled', False)
        toggle = button('Выключить игровой режим' if enabled else 'Включить игровой режим', self.app.toggle_game)
        toggle.set_sensitive(not self.app.game_pending)
        self.body.pack_start(toggle, False, False, 0)
        description = 'Лёгкая панель · без обоев, анимаций и теней' if enabled else 'Освобождает память компонентов рабочего стола'
        self.body.pack_start(label(description, 'muted', True), False, False, 0)
        if enabled:
            released = self.app.game_state.get('released_component_pss_mib', 0)
            row(self.body, 'Выгруженные компоненты', f'~{released:.0f} MiB', 'muted')
        if 'ram_used' in data: row(self.body, 'RAM всей системы', f"{data['ram_used']:.2f} GiB", 'muted')
        self.section('WI-FI')
        state = data.get('wifi', 'unavailable')
        row(self.body, 'Радиомодуль', {'enabled': 'Включён', 'disabled': 'Выключен'}.get(state, 'Недоступен'))
        for connection in data.get('connections', []):
            self.body.pack_start(label(f"{connection['interface']} · {connection['connection'] or connection['state']}", 'muted', True), False, False, 0)
        wifi = box(False)
        toggle = button('Выключить' if state == 'enabled' else 'Включить',
                        lambda state=state: self.app.action(['nmcli', 'radio', 'wifi', 'off' if state == 'enabled' else 'on']))
        toggle.set_sensitive(state in ('enabled', 'disabled'))
        wifi.pack_start(toggle, False, False, 0)
        wifi.pack_start(button('Настройки Wi-Fi', lambda: self.launch(['nm-connection-editor'])), True, True, 0)
        self.body.pack_start(wifi, False, False, 0)
        self.section('BLUETOOTH')
        state = data.get('bluetooth', 'unavailable')
        row(self.body, 'Адаптер', {'on': 'Включён', 'off': 'Выключен'}.get(state, 'Недоступен'))
        devices = data.get('bluetooth_devices', [])
        self.body.pack_start(label(', '.join(devices) if devices else 'Нет подключённых устройств', 'muted', True), False, False, 0)
        bluetooth = box(False)
        toggle = button('Выключить' if state == 'on' else 'Включить',
                        lambda state=state: self.app.action(['bluetoothctl', 'power', 'off' if state == 'on' else 'on']))
        toggle.set_sensitive(state in ('on', 'off'))
        bluetooth.pack_start(toggle, False, False, 0)
        bluetooth.pack_start(button('Настройки Bluetooth', lambda: self.launch(['blueman-manager'])), True, True, 0)
        self.body.pack_start(bluetooth, False, False, 0)

    def render_music(self, data, parent):
        players = data.get('media', [])
        heading = self.dashboard.music_header
        yandex = next((p for p in players if p.get('yandex')), None)
        header = box(False)
        header.pack_start(Gtk.Image.new_from_icon_name('yandexmusic', Gtk.IconSize.LARGE_TOOLBAR), False, False, 0)
        header.pack_start(label('Яндекс Музыка', 'heading'), True, True, 0)
        launch_button = button('Показать приложение' if yandex else 'Запустить плеер',
                               self.open_yandex_music if yandex else lambda: self.play_yandex('background'))
        launch_button.set_tooltip_text('Официальное приложение Яндекс Музыки. Фоновый плеер работает отдельно.')
        launch_button.set_sensitive(not self.app.music_pending)
        header.pack_end(launch_button, False, False, 0)
        heading.pack_start(header, False, False, 0)
        presets = box(False)
        for title, action in [('Моя волна', 'wave'), ('Любимые треки', 'favorites')]:
            preset = button(title, lambda a=action: self.play_yandex(a))
            preset.set_sensitive(not self.app.music_pending)
            presets.pack_start(preset, True, True, 0)
        heading.pack_start(presets, False, False, 0)
        if self.app.music_pending:
            heading.pack_start(label(self.app.music_message, 'muted'), False, False, 0)
        elif self.app.music_error:
            heading.pack_start(label(self.app.music_error, 'muted', True), False, False, 0)
        selected = next((p for p in players if p['bus'] == self.preferred_player),
                        yandex or (players[0] if players else None))
        self.dashboard.record.update(selected)
        if not selected:
            self.player = None
            parent.pack_start(label('Сейчас ничего не играет', 'muted'), False, False, 0)
        else:
            self.player = selected['bus']
            parent.pack_start(label(selected['title'], 'title', True), False, False, 0)
            parent.pack_start(label(selected['artist'] or selected['album'] or selected['player'], 'muted'), False, False, 0)
            row(parent, selected['player'], {'Playing': 'Играет', 'Paused': 'Пауза', 'Stopped': 'Остановлено'}.get(selected['status'], selected['status']))
            if selected.get('yandex') and not selected['play'] and not selected['pause']:
                parent.pack_start(label('Выберите трек или включите «Мою волну» в приложении. '
                                        'Затем управляйте музыкой здесь.', 'muted', True), False, False, 0)
            if len(players) > 1:
                selector = Gtk.ComboBoxText()
                selector.append('auto', 'Авто · Яндекс Музыка' if yandex else 'Авто · сейчас играет')
                for player in players: selector.append(player['bus'], player['player'])
                selector.set_active_id(self.preferred_player or 'auto')
                selector.connect('changed', self.select_player)
                parent.pack_start(selector, False, False, 0)
            length = selected['length']
            if length:
                progress = Gtk.ProgressBar()
                progress.set_fraction(max(0, min(1, selected['position'] / length)))
                parent.pack_start(progress, False, False, 0)
                def clock(us): return f'{int(us / 60000000)}:{int(us / 1000000) % 60:02}'
                row(parent, clock(selected['position']), clock(length), 'muted')
            controls = box(False)
            for text, method, enabled in [('⏮', 'Previous', selected['previous']),
                                          ('Пауза' if selected['status'] == 'Playing' else 'Играть', 'PlayPause', selected['pause'] if selected['status'] == 'Playing' else selected['play']),
                                          ('⏭', 'Next', selected['next'])]:
                widget = button(text, lambda m=method, n=self.player: self.app.music(n, m))
                widget.set_sensitive(selected['control'] and enabled and not self.app.music_pending)
                controls.pack_start(widget, True, True, 0)
            parent.pack_start(controls, False, False, 0)
            if selected.get('seek'):
                seek = box(False)
                for text, method in [('−10 секунд', 'SeekBack'), ('+10 секунд', 'SeekForward')]:
                    control = button(text, lambda m=method, n=self.player: self.app.music(n, m))
                    control.set_sensitive(not self.app.music_pending)
                    seek.pack_start(control, True, True, 0)
                parent.pack_start(seek, False, False, 0)

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
        self.action_pool = ThreadPoolExecutor(max_workers=2)
        self.music_pool = ThreadPoolExecutor(max_workers=1)
        self.music_pending = False
        self.music_message = ''
        self.music_error = ''
        self.pending = False
        self.popups = []
        css = Gtk.CssProvider()
        self.css = css
        css.load_from_path(str(appearance.ROOT / 'plugins/style.css'))
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
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
        self.popups = [Popup(self, self.display.get_monitor(i), i, kind)
                       for i in range(self.display.get_n_monitors()) for kind in ['profile', 'dashboard']]
        self.build_game_bars()
        if hasattr(self, 'fullscreen'): self.fullscreen.refresh()

    def monitors_changed(self):
        self.fracture.clear()
        self.rebuild()
        def work():
            try:
                with appearance.locked(): appearance.start()
            except Exception as exc:
                print(f'g8d wallpaper hotplug: {exc}', file=sys.stderr, flush=True)
        self.pool.submit(work)

    def build_game_bars(self):
        for window in self.game_bars: window.destroy()
        self.game_bars = []
        if not self.game_state.get('enabled'): return
        for i in range(self.display.get_n_monitors()):
            popup = next(p for p in self.popups if p.index == i and p.kind == 'profile')
            window = popup.surface(self.display.get_monitor(i), 'g8d-game-bar', popup=True)
            window.get_style_context().add_class('game-bar')
            Layer.set_layer(window, Layer.Layer.TOP)
            Layer.set_anchor(window, Layer.Edge.LEFT, True)
            Layer.set_anchor(window, Layer.Edge.RIGHT, True)
            Layer.set_exclusive_zone(window, 36)
            window.set_size_request(-1, 36)
            layout = Gtk.Grid()
            layout.set_column_homogeneous(True)
            left, middle, right = box(False), box(False), box(False)
            left.pack_start(label('g8d / GAME', 'value'), False, False, 14)
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

    def message(self, *_):
        try:
            message = json.loads(self.socket.recv(65536))
            if "switcher" in message: self.switcher.update(message["switcher"])
            if message.get('appearance') == 'reload': self.css.load_from_path(str(appearance.ROOT / 'plugins/style.css'))
            if message.get('game') == 'toggle': self.toggle_game()
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

    def refresh(self):
        opened = next((p for p in self.popups if p.window.get_visible()), None)
        if opened and not self.pending:
            self.pending = True
            future = self.pool.submit(self.collector.collect, opened.kind)
            future.add_done_callback(lambda result: GLib.idle_add(self.update, opened, result))
        return True

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

    def action(self, command, timeout=8):
        def work():
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
                if result.returncode:
                    GLib.idle_add(self.notify, result.stderr.strip() or result.stdout.strip() or 'Действие не выполнено')
            except (OSError, subprocess.SubprocessError) as exc:
                GLib.idle_add(self.notify, str(exc))
            GLib.idle_add(self.refresh)
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
        self.action_pool.shutdown(wait=False, cancel_futures=True)
        self.music_pool.shutdown(wait=False, cancel_futures=True)
        Gtk.main_quit()
        return False


if __name__ == '__main__':
    if len(sys.argv) > 1:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as connection:
            connection.sendto(json.dumps({'game': 'toggle'} if sys.argv[1] == 'game' else {'hide': True} if sys.argv[1] == 'hide' else
                                        {'show': sys.argv[1], 'monitor': int(sys.argv[2]) if len(sys.argv) > 2 else 0}).encode(), str(SOCKET))
    else:
        Gtk.init(None)
        if not Layer.is_supported(): raise SystemExit('g8d panels require Wayland Layer Shell')
        app = App()
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, app.close)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, app.close)
        Gtk.main()
