"""Compact native quick settings: icon toggles, radio settings and monitor sliders."""
from gi.repository import Gdk, Gtk, GtkLayerShell as Layer, Pango


def image(name, size=28):
    widget = Gtk.Image.new_from_icon_name('g8d-' + name + '-symbolic', Gtk.IconSize.BUTTON)
    widget.set_pixel_size(size)
    return widget


def text(value='', style='', limit=0):
    widget = Gtk.Label(label=value, xalign=0)
    if style: widget.get_style_context().add_class(style)
    if limit:
        widget.set_max_width_chars(limit)
        widget.set_ellipsize(Pango.EllipsizeMode.END)
    return widget


def accessible(widget, name, tooltip=None):
    widget.get_accessible().set_name(name)
    widget.set_tooltip_text(tooltip or name)


def icon_button(symbol, name, callback, style='quick-icon', size=48):
    widget = Gtk.Button()
    widget.set_size_request(size, size)
    widget.get_style_context().add_class(style)
    widget.add(image(symbol, 22))
    accessible(widget, name)
    widget.connect('clicked', lambda *_: callback())
    return widget


class IconToggle:
    def __init__(self, name, symbol, off_symbol, callback, height=64):
        self.name, self.symbol, self.off_symbol = name, symbol, off_symbol
        self.button = Gtk.ToggleButton()
        self.button.set_hexpand(True)
        self.button.set_size_request(88, height)
        self.button.get_style_context().add_class('quick-tile')
        self.icon = image(symbol, 30)
        self.spinner = Gtk.Spinner()
        self.spinner.set_size_request(24, 24)
        self.spinner.set_halign(Gtk.Align.CENTER)
        self.spinner.set_valign(Gtk.Align.CENTER)
        self.stack = Gtk.Stack()
        self.stack.add_named(self.icon, 'icon')
        self.stack.add_named(self.spinner, 'busy')
        self.mark = image('radio-button-unchecked', 12)
        self.mark.set_halign(Gtk.Align.END)
        self.mark.set_valign(Gtk.Align.END)
        self.mark.set_margin_end(8)
        self.mark.set_margin_bottom(7)
        overlay = Gtk.Overlay()
        overlay.add(self.stack)
        overlay.add_overlay(self.mark)
        overlay.set_overlay_pass_through(self.mark, True)
        self.button.add(overlay)
        self.button.connect('toggled', callback)

    def update(self, active, enabled=True, busy=False, description=''):
        self.button.set_active(active)
        self.button.set_sensitive(enabled and not busy)
        self.icon.set_from_icon_name('g8d-' + (self.symbol if active else self.off_symbol) + '-symbolic', Gtk.IconSize.BUTTON)
        self.mark.set_from_icon_name('g8d-' + ('check-circle' if active else 'radio-button-unchecked') + '-symbolic', Gtk.IconSize.BUTTON)
        self.mark.set_pixel_size(12)
        self.stack.set_visible_child_name('busy' if busy else 'icon')
        self.spinner.start() if busy else self.spinner.stop()
        state = 'Изменяю…' if busy else 'Недоступно' if not enabled else 'Включено' if active else 'Выключено'
        tip = self.name + ' · ' + state + ('\n' + description if description else '')
        accessible(self.button, self.name, tip)
        self.button.get_accessible().set_description(state + '. ' + description)


class QuickSettings:
    def __init__(self, popup):
        self.popup, self.app = popup, popup.app
        self.syncing = False
        self.disposed = False
        self.busy = set()
        self.data = {}
        self.monitor_keys = None
        self.brightness_rows = {}
        self.wifi_page = None
        self.bluetooth_page = None
        self.audio_page = None
        self.root = Gtk.Stack()
        self.root.set_homogeneous(False)
        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.root.add_named(main, 'main')
        popup.window.get_style_context().add_class('quick-profile')
        Layer.set_keyboard_mode(popup.window, Layer.KeyboardMode.ON_DEMAND)
        popup.window.connect('key-press-event', self.key)
        popup.window.connect('hide', lambda *_: self.close_page())
        popup.window.connect('destroy', lambda *_: self.dispose())

        header = Gtk.Box(spacing=8)
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        self.name = text('', 'quick-name', 15)
        self.subtitle = text('Быстрые настройки', 'muted', 24)
        info.pack_start(self.name, False, False, 0)
        info.pack_start(self.subtitle, False, False, 0)
        info.set_valign(Gtk.Align.CENTER)
        header.pack_start(info, True, True, 0)
        from pathlib import Path
        self.actions = str(Path(__file__).resolve().parent.parent / 'actions')
        header.pack_end(icon_button('power-settings-new', 'Меню питания и блокировки',
                                   lambda: popup.launch([self.actions, 'power'])), False, False, 0)
        header.pack_end(icon_button('settings', 'Настройки рабочего стола',
                                   lambda: popup.launch([self.actions, 'settings'])), False, False, 0)
        main.pack_start(header, False, False, 0)

        self.wifi = IconToggle('Wi-Fi', 'wifi', 'wifi-off', lambda b: self.radio('wifi', b))
        self.bluetooth = IconToggle('Bluetooth', 'bluetooth', 'bluetooth-disabled', lambda b: self.radio('bluetooth', b))
        radios = Gtk.Box(spacing=8, homogeneous=True)
        for toggle, title, callback in (
                (self.wifi, 'Сети Wi-Fi', self.show_wifi),
                (self.bluetooth, 'Устройства Bluetooth', self.show_bluetooth)):
            group = Gtk.Box(spacing=4)
            group.pack_start(toggle.button, True, True, 0)
            detail = icon_button('chevron-right', title, callback, 'quick-detail')
            detail.set_size_request(48, 64)
            group.pack_end(detail, False, False, 0)
            radios.pack_start(group, True, True, 0)
            if toggle is self.bluetooth:
                self.bluetooth_detail = detail
            else:
                self.wifi_detail = detail
        main.pack_start(radios, False, False, 0)

        modes = Gtk.Box(spacing=8, homogeneous=True)
        self.game = IconToggle('Игровой режим', 'sports-esports', 'sports-esports', self.toggle_game, height=56)
        self.effects = IconToggle('Эффект перехода курсора', 'blur-on', 'blur-off', self.toggle_effects, height=56)
        modes.pack_start(self.game.button, True, True, 0)
        modes.pack_start(self.effects.button, True, True, 0)
        main.pack_start(modes, False, False, 0)

        from power_panel import PowerPanel
        self.power_panel = PowerPanel(popup)
        main.pack_start(self.power_panel.root, False, False, 0)

        self.monitors = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        main.pack_start(self.monitors, False, False, 0)
        self.footer = text('', 'quick-footer', 48)
        main.pack_start(self.footer, False, False, 0)
        self.notice = text('', 'quick-error', 46)
        self.notice.set_no_show_all(True)
        main.pack_start(self.notice, False, False, 0)

    def show_wifi(self):
        if self.wifi_page is None:
            from wifi_networks import Wifi
            from wifi_panel import WifiPanel
            if not hasattr(self.app, 'wifi_controller'):
                self.app.wifi_controller = Wifi()
            self.wifi_page = WifiPanel(self.app.wifi_controller, self.back_from_wifi,
                                       lambda: self.popup.launch(['nm-connection-editor']))
            self.root.add_named(self.wifi_page.root, 'wifi')
            self.wifi_page.root.show_all()
        self.root.set_visible_child_name('wifi')
        self.popup.window.resize(1, 1)
        self.wifi_page.open()
        self.wifi_page.back.grab_focus()

    def back_from_wifi(self, *_):
        if self.root.get_visible_child_name() == 'wifi':
            self.wifi_page.close()
            self.root.set_visible_child_name('main')
            self.popup.window.resize(1, 1)
            self.wifi_detail.grab_focus()

    def show_bluetooth(self):
        if self.bluetooth_page is None:
            from bluetooth import Bluetooth
            from bluetooth_panel import BluetoothPanel
            if not hasattr(self.app, 'bluetooth_controller'):
                self.app.bluetooth_controller = Bluetooth(self.app.action_pool)
            self.bluetooth_page = BluetoothPanel(self.app.bluetooth_controller, self.back_from_bluetooth)
            self.root.add_named(self.bluetooth_page.root, 'bluetooth')
            self.bluetooth_page.root.show_all()
        self.root.set_visible_child_name('bluetooth')
        self.popup.window.resize(1, 1)
        self.bluetooth_page.open()
        self.bluetooth_page.back.grab_focus()

    def back_from_bluetooth(self, *_):
        if self.root.get_visible_child_name() == 'bluetooth':
            self.bluetooth_page.close()
            self.root.set_visible_child_name('main')
            self.popup.window.resize(1, 1)
            self.bluetooth_detail.grab_focus()

    def pairing_active(self):
        return (self.root.get_visible_child_name() == 'bluetooth' and
                self.bluetooth_page.controller.pairing is not None)

    def page_holds_pointer(self):
        return self.pairing_active() or (
            self.root.get_visible_child_name() == 'wifi' and self.wifi_page.holds_pointer()) or (
            self.root.get_visible_child_name() == 'sound' and self.audio_page.holds_pointer())

    def sound_active(self):
        return self.root.get_visible_child_name() == 'sound'

    def show_sound(self):
        self.back_from_wifi()
        self.back_from_bluetooth()
        if self.audio_page is None:
            from audio_panel import AudioPanel
            self.audio_page = AudioPanel(self.app.action_pool, self.popup.hide)
            self.root.add_named(self.audio_page.root, 'sound')
            self.audio_page.root.show_all()
        self.root.set_visible_child_name('sound')
        self.popup.window.resize(1, 1)
        self.audio_page.open()

    def close_page(self):
        if self.sound_active():
            self.audio_page.close()
            self.root.set_visible_child_name('main')
            self.popup.window.resize(1, 1)
        else:
            self.back_from_wifi()
            self.back_from_bluetooth()

    def key(self, _, event):
        if event.keyval == Gdk.KEY_Escape:
            if self.root.get_visible_child_name() == 'wifi':
                if self.wifi_page.selected:
                    self.wifi_page.clear_prompt()
                    self.wifi_page.back.grab_focus()
                else:
                    self.back_from_wifi()
            elif self.root.get_visible_child_name() == 'bluetooth':
                self.back_from_bluetooth()
            else:
                self.popup.hide()
            return True
        return False

    def dispose(self):
        self.disposed = True
        self.power_panel.disposed = True
        self.close_page()
        if self.bluetooth_page:
            self.bluetooth_page.close()
        for toggle in (self.wifi, self.bluetooth, self.game, self.effects): toggle.spinner.stop()

    def radio(self, kind, button):
        if self.syncing or kind in self.busy: return
        target = button.get_active()
        self.busy.add(kind)
        self.notice.hide()
        toggle = self.wifi if kind == 'wifi' else self.bluetooth
        toggle.update(target, busy=True)
        command = (['nmcli', 'radio', 'wifi', 'on' if target else 'off'] if kind == 'wifi'
                   else ['bluetoothctl', 'power', 'on' if target else 'off'])
        def done(error):
            self.busy.discard(kind)
            if self.disposed: return
            if not error: self.data[kind] = ('enabled' if target else 'disabled') if kind == 'wifi' else ('on' if target else 'off')
            self.update(self.data)
            if error:
                self.notice.set_text('Не удалось изменить ' + ('Wi-Fi' if kind == 'wifi' else 'Bluetooth'))
                self.notice.set_tooltip_text(error)
                self.notice.show()
        self.app.action(command, done=done)

    def toggle_game(self, button):
        if not self.syncing: self.app.toggle_game()

    def toggle_effects(self, button):
        if self.syncing: return
        self.popup.cursor_effect_changed(button, None)
        self.update(self.data)

    def build_monitors(self, monitors):
        keys = tuple((m['output'], m['title']) for m in monitors)
        if keys == self.monitor_keys: return
        self.monitor_keys = keys
        for child in self.monitors.get_children(): child.destroy()
        self.brightness_rows.clear()
        self.popup.brightness_scales = {}
        for monitor in monitors:
            output = monitor['output']
            row = Gtk.Box(spacing=10)
            row.get_style_context().add_class('quick-brightness')
            row.set_size_request(-1, 40)
            symbol = image('laptop' if output.startswith('eDP') else 'desktop-windows', 22)
            symbol.set_tooltip_text(monitor['title'])
            row.pack_start(symbol, False, False, 0)
            value = text('', 'quick-percent')
            value.set_width_chars(4)
            value.set_xalign(1)
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 100, 1)
            scale.set_draw_value(False)
            scale.set_hexpand(True)
            accessible(scale, 'Яркость · ' + monitor['title'])
            scale.connect('value-changed', self.brightness_changed, output, value)
            scale.connect('button-press-event', lambda *_: self.popup.brightness_pointer(True))
            scale.connect('button-release-event', lambda *_: self.popup.brightness_pointer(False))
            row.pack_start(scale, True, True, 0)
            row.pack_end(value, False, False, 0)
            self.monitors.pack_start(row, False, False, 0)
            self.brightness_rows[output] = (scale, value)
            self.popup.brightness_scales[output] = scale
        if not monitors:
            self.monitors.pack_start(text('Определяю экраны…', 'muted'), False, False, 0)
        self.monitors.show_all()

    def brightness_changed(self, scale, output, value):
        if not self.syncing: self.popup.brightness_changed(scale, output, value)

    def update(self, data):
        self.data = dict(data)
        if self.popup.window.get_visible() and self.root.get_visible_child_name() == 'main':
            self.power_panel.refresh()
        self.syncing = True
        try:
            user = self.app.collector.user
            name = data.get('name', user['name'])
            self.name.set_text(name)
            self.name.set_tooltip_text(f"{name}\n{data.get('user', user['user'])}@{data.get('host', user['host'])}\n{data.get('os', user['os'])}")
            wifi = data.get('wifi')
            bluetooth = data.get('bluetooth')
            connection = ', '.join(c.get('connection') or c.get('state', '') for c in data.get('connections', []))
            devices = ', '.join(data.get('bluetooth_devices', [])) or 'Нет подключённых устройств'
            if 'wifi' not in self.busy:
                self.wifi.update(wifi == 'enabled', wifi in ('enabled', 'disabled'), busy=wifi is None,
                                 description=connection)
            if 'bluetooth' not in self.busy:
                self.bluetooth.update(bluetooth == 'on', bluetooth in ('on', 'off'), busy=bluetooth is None,
                                      description=devices)
            enabled = self.app.game_state.get('enabled', False)
            released = self.app.game_state.get('released_component_pss_mib', 0)
            self.game.update(enabled, busy=self.app.game_pending,
                             description=f'Выгружено ~{released:.0f} MiB' if enabled else 'Отключает обои, анимации и тени')
            self.effects.update(self.app.fracture.enabled, description='Вспышка при переходе между экранами')
            monitors = data.get('brightness', [])
            self.build_monitors(monitors)
            for monitor in monitors:
                scale, value = self.brightness_rows[monitor['output']]
                percent = self.app.brightness_overrides.get(monitor['output'], monitor['percent'])
                scale.set_value(percent)
                scale.set_sensitive(monitor['enabled'])
                value.set_text(f'{percent}%' if monitor['enabled'] else '—')
                reason = '' if monitor['enabled'] else '\nНедоступно: ' + monitor.get('error', 'Проверь DDC/CI в меню монитора')
                scale.set_tooltip_text(monitor['title'] + reason)
            minutes = data.get('uptime', 0) // 60
            memory = f" · RAM {data['ram_used']:.1f} ГБ" if 'ram_used' in data else ''
            self.footer.set_text(f'{minutes // 60} ч {minutes % 60} мин' + memory if 'uptime' in data else '')
        finally:
            self.syncing = False
