"""Compact sound controls with a playback mixer inside quick settings."""
from gi.repository import GLib, Gtk, Pango

import audio
from bluetooth_battery import BatteryMonitor, format_charge
from quick_settings import accessible, icon_button, image, text


MIXER_HEIGHT = 290
MIXED_OUTPUT = 'g8d/mixed-output'


class OutputSelector(Gtk.ComboBox):
    def __init__(self, name, on_change):
        self.options = Gtk.ListStore(str, str, str)
        super().__init__(model=self.options)
        self.set_id_column(0)
        self.names = ()
        accessible(self, name)
        device = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END, max_width_chars=25)
        self.pack_start(device, True)
        self.add_attribute(device, 'text', 1)
        battery = Gtk.CellRendererText(xalign=1, xpad=4)
        self.pack_end(battery, False)
        self.add_attribute(battery, 'text', 2)
        self.connect('changed', on_change)

    def update(self, options, active, mixed=False):
        if self.get_property('popup-shown'):
            return
        options = tuple((item['name'], item['label'], item.get('charge', '')) for item in options)
        if mixed:
            options = ((MIXED_OUTPUT, 'Разные выходы', ''),) + options
        if options != self.names:
            self.names = options
            self.options.clear()
            for option in options:
                self.options.append(option)
        self.set_active_id(MIXED_OUTPUT if mixed else active) if mixed or active else self.set_active(-1)
        self.set_sensitive(bool(options))
        iterator = self.get_active_iter()
        label, charge = self.options[iterator][1:3] if iterator is not None else ('Выберите выход', '')
        self.set_tooltip_text(f'{label}\n{charge}' if charge else label)


class Volume:
    def __init__(self, name, changed, drag):
        self.box = Gtk.Box(spacing=8)
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.scale.set_draw_value(False)
        self.scale.set_hexpand(True)
        self.scale.set_margin_start(4)
        self.scale.set_margin_end(6)
        accessible(self.scale, name)
        self.scale.connect('value-changed', changed)
        self.scale.connect('button-press-event', lambda *_: drag(True))
        self.scale.connect('button-release-event', lambda *_: drag(False))
        self.scale.connect('grab-broken-event', lambda *_: drag(False))
        self.value = text('—', 'quick-percent')
        self.value.set_width_chars(4)
        self.value.set_xalign(1)
        self.box.pack_start(self.scale, True, True, 0)
        self.box.pack_end(self.value, False, False, 0)

    def update(self, percent):
        self.scale.set_sensitive(percent is not None)
        maximum = max(100, percent or 0)
        if self.scale.get_adjustment().get_upper() != maximum:
            self.scale.set_range(0, maximum)
        self.scale.set_value(percent or 0)
        self.value.set_text(f'{percent}%' if percent is not None else '—')


class ApplicationRow:
    def __init__(self, panel, key, name):
        self.data = {}
        self.root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.root.get_style_context().add_class('quick-audio-app')
        title = text(name, 'quick-audio-app-name', 30)
        title.set_single_line_mode(True)
        title.set_tooltip_text(name)
        self.root.pack_start(title, False, False, 0)
        self.volume = Volume('Громкость · ' + name, self.change_volume,
                             lambda active: panel.drag(('volume', key), active))
        self.volume.scale.set_size_request(-1, 31)
        self.root.pack_start(self.volume.box, False, False, 0)
        self.output = OutputSelector('Выход · ' + name, self.change_output)
        self.root.pack_start(self.output, False, False, 0)
        self.panel, self.key = panel, key

    def update(self, group, outputs):
        self.data = group
        if not self.panel.pending(('volume', self.key)):
            self.volume.update(group['volume'])
        if not self.panel.pending(('route', self.key)):
            self.output.update(outputs, group['output'], group['mixed'])

    def change_volume(self, scale):
        if self.panel.syncing or not self.data.get('writable'):
            return
        percent = round(scale.get_value())
        self.volume.value.set_text(f'{percent}%')
        commands = [('set-sink-input-volume', str(stream), f'{percent}%') for stream in self.data['writable']]
        self.panel.enqueue(('volume', self.key), 'Громкость приложения не изменилась.', commands, debounce=True)

    def change_output(self, combo):
        name = combo.get_active_id()
        if self.panel.syncing or not name or name == MIXED_OUTPUT:
            return
        commands = [('move-sink-input', str(stream), name) for stream in self.data['streams']]
        self.panel.enqueue(('route', self.key), 'Выход приложения не изменился.', commands)


class AudioPanel:
    def __init__(self, pool, dismiss):
        self.pool = pool
        self.opened = False
        self.inflight = False
        self.syncing = False
        self.refresh_id = self.flush_id = 0
        self.queued = {}
        self.dragging = set()
        self.default = None
        self.outputs = []
        self.rows = {}
        self.batteries = BatteryMonitor(pool, self.battery_changed)
        self.root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.root.get_style_context().add_class('quick-audio')

        header = Gtk.Box(spacing=8)
        header.pack_start(text('Звук', 'quick-name'), True, True, 0)
        close = icon_button('settings', 'Закрыть меню звука', dismiss, size=44)
        close.get_child().set_from_icon_name('window-close-symbolic', Gtk.IconSize.BUTTON)
        header.pack_end(close, False, False, 0)
        self.root.pack_start(header, False, False, 0)

        main = Gtk.Box(spacing=8)
        self.mute = icon_button('volume-up', 'Выключить звук', self.toggle_mute, 'quick-audio-mute', 44)
        main.pack_start(self.mute, False, False, 0)
        self.volume = Volume('Громкость выхода по умолчанию', self.change_volume,
                             lambda active: self.drag('main-volume', active))
        main.pack_start(self.volume.box, True, True, 0)
        self.root.pack_start(main, False, False, 0)

        self.root.pack_start(text('Выход по умолчанию', 'quick-audio-label'), False, False, 0)
        self.output = OutputSelector('Выход по умолчанию', self.change_output)
        self.root.pack_start(self.output, False, False, 0)
        self.notice = text('', 'quick-audio-notice')
        self.notice.set_line_wrap(True)
        self.notice.set_no_show_all(True)
        self.root.pack_start(self.notice, False, False, 0)
        self.expand = Gtk.ToggleButton()
        self.expand.set_size_request(-1, 44)
        self.expand.get_style_context().add_class('quick-audio-expand')
        row = Gtk.Box(spacing=8)
        row.pack_start(text('Микшер приложений'), True, True, 0)
        self.arrow = image('chevron-right', 16)
        row.pack_end(self.arrow, False, False, 0)
        self.expand.add(row)
        self.expand.connect('toggled', self.expanded)
        self.root.pack_start(self.expand, False, False, 0)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_max_content_height(MIXER_HEIGHT)
        self.scroll.set_propagate_natural_height(True)
        self.scroll.set_no_show_all(True)
        self.scroll.add(self.list)
        self.root.pack_start(self.scroll, True, True, 0)
        self.expanded()
        self.update_main(None, [])

    def open(self):
        if self.opened:
            return
        self.opened = True
        self.set_notice('Проверяю звуковые выходы…')
        self.refresh_id = GLib.timeout_add_seconds(2, self.refresh)
        self.flush()
        self.mute.grab_focus()

    def close(self):
        self.opened = False
        self.batteries.watch()
        if self.refresh_id:
            GLib.source_remove(self.refresh_id)
            self.refresh_id = 0
        self.dragging.clear()
        self.expand.set_active(False)
        self.flush()

    def holds_pointer(self):
        return bool(self.dragging or self.output.get_property('popup-shown') or
                    any(row.output.get_property('popup-shown') for row in self.rows.values()))

    def drag(self, key, active):
        if active:
            self.dragging.add(key)
        else:
            self.dragging.discard(key)
        return False

    def expanded(self, *_):
        show = self.expand.get_active()
        self.arrow.set_from_icon_name('go-up-symbolic' if show else 'go-down-symbolic', Gtk.IconSize.BUTTON)
        accessible(self.expand, 'Свернуть микшер приложений' if show else 'Развернуть микшер приложений')
        self.scroll.set_visible(show)
        if show:
            self.update_apps([], [], 'Загружаю аудиопотоки…')
            self.flush()
        window = self.root.get_toplevel()
        if isinstance(window, Gtk.Window):
            window.resize(1, 1)

    def refresh(self):
        if not self.flush_id:
            self.flush()
        return GLib.SOURCE_CONTINUE

    def set_notice(self, message='', detail=''):
        self.notice.set_text(message)
        self.notice.set_tooltip_text(detail or None)
        self.notice.set_visible(bool(message))

    def enqueue(self, key, label, commands, debounce=False):
        self.set_notice()
        self.queued[key] = (label, commands)
        if self.flush_id:
            GLib.source_remove(self.flush_id)
            self.flush_id = 0
        if debounce:
            self.flush_id = GLib.timeout_add(110, self.flush_timeout)
        else:
            self.flush()

    def flush_timeout(self):
        self.flush_id = 0
        self.flush()
        return GLib.SOURCE_REMOVE

    def pending(self, key):
        return key in self.queued or key in self.dragging

    def flush(self):
        if self.inflight or (not self.opened and not self.queued):
            return
        if self.flush_id:
            GLib.source_remove(self.flush_id)
            self.flush_id = 0
        edits, self.queued = tuple(self.queued.values()), {}
        expanded = self.opened and self.expand.get_active()
        self.inflight = True
        future = self.pool.submit(audio.apply, edits, expanded)
        future.add_done_callback(lambda result: GLib.idle_add(self.finished, result, expanded))

    def finished(self, future, expanded):
        self.inflight = False
        state, errors = future.result()
        if self.opened:
            self.syncing = True
            try:
                if state is None:
                    self.update_main(None, [])
                    if self.expand.get_active():
                        self.update_apps([], [], 'Аудиопотоки недоступны.')
                else:
                    default, outputs, apps = state
                    self.update_main(default, outputs)
                    if self.expand.get_active() and apps is not None:
                        self.update_apps(apps, outputs, 'Приложения появятся, когда начнут воспроизводить звук.')
                if errors:
                    self.set_notice(*errors[0])
                elif not self.default:
                    self.set_notice('Нет выхода по умолчанию.')
                elif self.notice.get_text() in ('Проверяю звуковые выходы…', 'Звуковая служба недоступна.', 'Нет выхода по умолчанию.'):
                    self.set_notice()
            finally:
                self.syncing = False
        if (self.queued and not self.flush_id) or (self.opened and self.expand.get_active() and not expanded):
            self.flush()
        return GLib.SOURCE_REMOVE

    def update_main(self, default, outputs):
        self.default = default
        self.outputs = outputs
        if self.opened:
            self.batteries.watch(output.get('bluetooth') for output in outputs)
        muted = bool(default and default['muted'])
        self.mute.set_sensitive(default is not None)
        accessible(self.mute, 'Включить звук' if muted else 'Выключить звук')
        icon = 'audio-volume-muted-symbolic' if muted else 'g8d-volume-up-symbolic'
        self.mute.get_child().set_from_icon_name(icon, Gtk.IconSize.BUTTON)
        if not self.pending('main-volume'):
            self.volume.update(default['volume'] if default else None)
        if not self.pending('default-output'):
            self.output.update(self.with_charge(outputs), default['name'] if default else None)

    def with_charge(self, outputs):
        options = []
        for output in outputs:
            charge = format_charge(self.batteries.values.get(output.get('bluetooth'), {}))
            options.append({**output, 'charge': charge})
        return options

    def battery_changed(self):
        self.syncing = True
        try:
            outputs = self.with_charge(self.outputs)
            if not self.pending('default-output'):
                self.output.update(outputs, self.default['name'] if self.default else None)
            if self.expand.get_active():
                for key, row in self.rows.items():
                    if not self.pending(('route', key)):
                        row.output.update(outputs, row.data['output'], row.data['mixed'])
        finally:
            self.syncing = False

    def update_apps(self, apps, outputs, empty):
        if any(row.output.get_property('popup-shown') for row in self.rows.values()):
            return
        keys = {app['key'] for app in apps}
        for key in tuple(self.rows.keys() - keys):
            self.rows.pop(key).root.destroy()
            self.dragging.discard(('volume', key))
        for child in self.list.get_children():
            if isinstance(child, Gtk.Label):
                child.destroy()
        outputs = self.with_charge(outputs)
        for index, app in enumerate(apps):
            key = app['key']
            if key not in self.rows:
                self.rows[key] = ApplicationRow(self, key, app['name'])
                self.list.pack_start(self.rows[key].root, False, False, 0)
            row = self.rows[key]
            row.update(app, outputs)
            self.list.reorder_child(row.root, index)
        if not apps:
            message = text(empty, 'quick-audio-label')
            message.set_line_wrap(True)
            self.list.pack_start(message, False, False, 6)
        self.list.show_all()
        self.scroll.set_min_content_height(min(MIXER_HEIGHT, self.list.get_preferred_height()[1]))

    def toggle_mute(self):
        if self.default:
            self.enqueue('mute', 'Не удалось переключить звук.',
                         [('set-sink-mute', self.default['name'], 'toggle')])

    def change_volume(self, scale):
        if not self.syncing and self.default:
            percent = round(scale.get_value())
            self.volume.value.set_text(f'{percent}%')
            self.enqueue('main-volume', 'Общая громкость не изменилась.',
                         [('set-sink-volume', self.default['name'], f'{percent}%')], debounce=True)

    def change_output(self, combo):
        name = combo.get_active_id()
        if not self.syncing and name:
            self.enqueue('default-output', 'Основной выход не изменился.', [('set-default-sink', name)])
