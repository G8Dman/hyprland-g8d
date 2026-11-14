"""Three animated dashboard tabs; calendar selection survives sensor refreshes."""
import datetime as dt
import subprocess
from gi.repository import Gtk, GLib, Pango
from vinyl import Vinyl


def box(vertical=True, spacing=10):
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL, spacing=spacing)


def text(value, style=''):
    label = Gtk.Label(label=value, xalign=0)
    label.set_ellipsize(Pango.EllipsizeMode.END)
    label.set_max_width_chars(36)
    if style: label.get_style_context().add_class(style)
    return label


def button(title, action):
    widget = Gtk.Button(label=title)
    widget.connect('clicked', lambda *_: action())
    return widget


def row(parent, name, value):
    line = box(False, 8)
    line.pack_start(text(name), True, True, 0)
    label = text(value, 'value')
    label.set_xalign(1)
    line.pack_end(label, False, False, 0)
    parent.pack_start(line, False, False, 0)


class Dashboard:
    def __init__(self, popup, width):
        self.popup = popup
        self.sync = popup.app.calendar
        self.root = box(spacing=12)
        self.stack = Gtk.Stack()
        self.stack.set_homogeneous(False)
        self.stack.set_interpolate_size(True)
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_transition_duration(240)
        switcher = Gtk.StackSwitcher()
        switcher.set_stack(self.stack)
        switcher.set_halign(Gtk.Align.CENTER)
        self.root.pack_start(switcher, False, False, 0)
        self.root.pack_start(self.stack, True, True, 0)
        self.events = []
        self.month_key = None
        self.revision = None
        self.cards = []
        for name, title in [('calendar', 'Календарь'), ('system', 'Мониторинг'), ('music', 'Музыка')]:
            card = box(spacing=12)
            card.get_style_context().add_class('dashboard-card')
            card.set_hexpand(True)
            self.stack.add_titled(card, name, title)
            self.cards.append(card)
        calendar_card, system, music = self.cards
        calendar_layout = box(False, 22)
        calendar_card.pack_start(calendar_layout, True, True, 0)
        calendar = box(spacing=12)
        calendar.set_size_request(330, -1)
        calendar_layout.pack_start(calendar, False, False, 0)
        self.calendar = Gtk.Calendar()
        self.calendar.set_display_options(Gtk.CalendarDisplayOptions.SHOW_HEADING | Gtk.CalendarDisplayOptions.SHOW_DAY_NAMES)
        self.calendar.connect('day-selected', lambda *_: self.agenda())
        self.calendar.connect('month-changed', lambda *_: self.calendar_update())
        calendar.pack_start(self.calendar, False, False, 0)
        self.status = text('', 'muted')
        calendar.pack_start(self.status, False, False, 0)
        controls = box(False, 5)
        controls.pack_start(button('Сегодня', self.today), True, True, 0)
        controls.pack_start(button('↻', lambda: self.sync.refresh(force=True)), False, False, 0)
        controls.pack_start(button('⚙', self.settings_toggle), False, False, 0)
        calendar.pack_start(controls, False, False, 0)
        self.settings = Gtk.Revealer()
        settings = box(spacing=8)
        hint = text('Google → Настройки календаря →\nИнтеграция → Закрытый адрес iCal', 'muted')
        hint.set_ellipsize(Pango.EllipsizeMode.NONE)
        settings.pack_start(hint, False, False, 0)
        self.entry = Gtk.Entry()
        self.entry.set_visibility(False)
        self.entry.set_placeholder_text('Вставь закрытый адрес iCal')
        self.entry.connect('activate', lambda *_: self.connect_calendar())
        settings.pack_start(self.entry, False, False, 0)
        self.settings_message = text('Только просмотр · обновление каждые 5 минут', 'muted')
        settings.pack_start(self.settings_message, False, False, 0)
        settings.pack_start(button('Подключить', self.connect_calendar), False, False, 0)
        settings.pack_start(button('Открыть Google Календарь', lambda: subprocess.Popen(['xdg-open', 'https://calendar.google.com/calendar/u/0/r/settings'])), False, False, 0)
        settings.pack_start(button('Отключить', self.disconnect), False, False, 0)
        self.settings.add(settings)
        calendar.pack_start(self.settings, False, False, 0)
        self.agenda_box = box(spacing=8)
        agenda_scroll = Gtk.ScrolledWindow()
        agenda_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        agenda_scroll.set_propagate_natural_height(True)
        agenda_scroll.set_max_content_height(max(130, min(320, popup.monitor.get_geometry().height - 650)))
        agenda_scroll.add(self.agenda_box)
        calendar_layout.pack_start(agenda_scroll, True, True, 0)
        self.system = box(False, 24)
        self.music = box(spacing=12)
        self.music_header = box(spacing=12)
        self.record = Vinyl()
        system.pack_start(self.system, False, False, 0)
        music.pack_start(self.music_header, False, False, 0)
        music.pack_start(self.record, False, False, 0)
        music.pack_start(self.music, False, False, 0)
        self.stack.connect('notify::visible-child-name', self.tab_changed)
        self.stack.set_visible_child_name('calendar')
        self.tab_changed()
        self.calendar_update()

    def tab_changed(self, *_):
        name = self.stack.get_visible_child_name() or 'calendar'
        width = {'calendar': 820, 'system': 1160, 'music': 620}[name]
        width = min(width, self.popup.monitor.get_geometry().width - 48)
        self.popup.window.set_size_request(width, -1)
        self.popup.window.resize(width, 1)
        self.popup.window.queue_resize()

    def settings_toggle(self):
        self.settings.set_reveal_child(not self.settings.get_reveal_child())
        if self.settings.get_reveal_child(): self.entry.grab_focus()

    def connect_calendar(self):
        try:
            self.sync.configure(self.entry.get_text())
        except ValueError as exc:
            self.settings_message.set_text(str(exc))
            return
        self.entry.set_text('')
        self.settings.set_reveal_child(False)
        self.sync.refresh(force=True)
        self.calendar_update()

    def disconnect(self):
        self.sync.configure('')
        self.entry.set_text('')
        self.settings.set_reveal_child(False)
        self.calendar_update()

    def today(self):
        today = dt.date.today()
        self.calendar.select_month(today.month - 1, today.year)
        self.calendar.select_day(today.day)

    def calendar_update(self):
        self.sync.refresh()
        self.status.set_text(self.sync.status())
        year, month, _ = self.calendar.get_date()
        key = (year, month, self.sync.updated, bool(self.sync.url))
        if key != self.month_key:
            self.month_key = key
            try: self.events = self.sync.month(year, month + 1)
            except Exception:
                self.events = []
                self.status.set_text('Не удалось прочитать события')
            self.calendar.clear_marks()
            for event in self.events:
                start = event['start'].date() if isinstance(event['start'], dt.datetime) else event['start']
                end = event['end'].date() if isinstance(event['end'], dt.datetime) else event['end']
                if event['all_day']: end -= dt.timedelta(days=1)
                day = max(start, dt.date(year, month + 1, 1))
                while day <= max(start, end) and day.year == year and day.month == month + 1:
                    self.calendar.mark_day(day.day)
                    day += dt.timedelta(days=1)
            self.agenda()

    def agenda(self):
        for child in self.agenda_box.get_children(): child.destroy()
        year, month, day = self.calendar.get_date()
        if not day: return
        selected = dt.date(year, month + 1, day)
        self.agenda_box.pack_start(text(selected.strftime('%d.%m.%Y'), 'heading'), False, False, 0)
        found = []
        for event in self.events:
            start, end = event['start'], event['end']
            start_day = start.date() if isinstance(start, dt.datetime) else start
            end_day = end.date() if isinstance(end, dt.datetime) else end
            if event['all_day']: end_day -= dt.timedelta(days=1)
            elif isinstance(end, dt.datetime) and end.time() == dt.time() and end > start: end_day -= dt.timedelta(days=1)
            if start_day <= selected <= max(start_day, end_day): found.append(event)
        for event in found:
            clock = 'Весь день' if event['all_day'] else event['start'].strftime('%H:%M')
            label = text(clock + ' · ' + event['title'])
            label.set_tooltip_text(event['title'] + ('\n' + event['location'] if event['location'] else ''))
            self.agenda_box.pack_start(label, False, False, 0)
        if not found: self.agenda_box.pack_start(text('Нет событий' if self.sync.url else 'Подключи Google Календарь через ⚙', 'muted'), False, False, 0)
        self.agenda_box.show_all()

    def update(self, data):
        self.calendar_update()
        for child in self.system.get_children(): child.destroy()
        for child in self.music.get_children(): child.destroy()
        for child in self.music_header.get_children(): child.destroy()
        self.popup.render_music(data, self.music)
        if not data:
            self.system.pack_start(text('Получаю данные…', 'muted'), False, False, 0)
        else:
            metrics, details = box(spacing=10), box(spacing=10)
            self.system.pack_start(metrics, True, True, 0)
            self.system.pack_start(details, True, True, 0)
            row(metrics, 'CPU', f"{data['cpu']:.0f}%")
            row(metrics, 'RAM', f"{data['ram_used']:.1f} / {data['ram_total']:.1f} GiB · {data['ram_percent']:.0f}%")
            row(metrics, 'Swap', f"{data['swap_used']:.1f} / {data['swap_total']:.1f} GiB")
            for gpu in data['gpu']:
                metrics.pack_start(text(gpu['name'], 'muted'), False, False, 0)
                row(metrics, 'GPU', f"{gpu['load']:.0f}%" if gpu['load'] is not None else 'Нет датчика нагрузки')
                if gpu['used'] is not None and gpu['total']:
                    row(metrics, 'VRAM', f"{gpu['used']/1024:.2f} / {gpu['total']/1024:.2f} GiB")
                sensors = []
                if gpu['temp'] is not None: sensors.append(f"{gpu['temp']:.0f} °C")
                if gpu['watts'] is not None: sensors.append(f"{gpu['watts']:.1f} W")
                if sensors: row(metrics, 'Датчики', ' · '.join(sensors))
            metrics.pack_start(Gtk.Separator(), False, False, 0)
            details.pack_start(text('ПРОЦЕССЫ · CPU / RAM', 'heading'), False, False, 0)
            columns = box(False, 18)
            for name, key in [('Топ CPU', 'processes_cpu'), ('Топ RAM', 'processes_ram')]:
                column = box(spacing=6)
                column.pack_start(text(name, 'muted'), False, False, 0)
                for process in data[key]:
                    item = text(f"{process['name']} · {process['cpu']:.0f}% · {process['ram']:.0f} MiB", 'process')
                    item.set_tooltip_text(f"{process['name']} · PID {process['pid']}\nCPU {process['cpu']:.1f}% · RAM {process['ram']:.0f} MiB")
                    column.pack_start(item, False, False, 0)
                columns.pack_start(column, True, True, 0)
            details.pack_start(columns, False, False, 0)
            details.pack_start(Gtk.Separator(), False, False, 0)
            details.pack_start(text('СЕТЬ · IP ИНТЕРФЕЙСОВ', 'heading'), False, False, 0)
            for interface in data['interfaces']:
                row(details, interface['name'], 'UP' if interface['up'] else 'DOWN')
                ip = text(' · '.join(interface['ips']), 'muted')
                ip.set_ellipsize(Pango.EllipsizeMode.NONE)
                ip.set_line_wrap(True)
                ip.set_line_wrap_mode(Pango.WrapMode.CHAR)
                ip.set_selectable(True)
                ip.set_tooltip_text('\n'.join(interface['ips']))
                details.pack_start(ip, False, False, 0)
        self.root.show_all()
