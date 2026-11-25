#!/usr/bin/env python3
"""Native, single-instance settings for the isolated g8d desktop."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, Gio, GLib, Gtk, Pango
import branding
import appearance
import ui_themes
import file_associations
import wifi
import shortcuts_ui

GLib.set_prgname('g8d-settings')
GLib.set_application_name('Настройки g8d')

ROOT = Path(__file__).resolve().parent.parent
PLUGINS = ROOT / 'plugins'
EFFECTS = ROOT / 'cursor-effects.json'
MONITORS = ROOT / 'monitors.lua'
SIGNATURE = os.environ.get('HYPRLAND_INSTANCE_SIGNATURE', 'default')
IPC = Path(os.environ.get('XDG_RUNTIME_DIR', '/tmp')) / f'g8d-panels-{os.getuid()}-{SIGNATURE}.sock'


def run(args, timeout=12):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'Не удалось выполнить действие')
    return result.stdout.strip()


def atomic(path, content):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(content)
    temporary.replace(path)


def read_json(path, default):
    try: return json.loads(path.read_text())
    except (OSError, ValueError): return default


def panel(message):
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as connection:
            connection.sendto(json.dumps(message).encode(), str(IPC))
        return True
    except OSError: return False


def column(spacing=12): return Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)


def text(value, style='', wrap=False):
    label = Gtk.Label(label=value, xalign=0)
    label.set_line_wrap(wrap)
    label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if style: label.get_style_context().add_class(style)
    return label


def button(title, action):
    widget = Gtk.Button(label=title)
    widget.connect('clicked', lambda *_: action())
    return widget


def group(parent, title=None):
    if title: parent.pack_start(text(title, 'section-heading'), False, False, 0)
    body = column(0)
    body.get_style_context().add_class('settings-group')
    parent.pack_start(body, False, False, 0)
    return body


def row(parent, title, description='', widget=None):
    if parent.get_style_context().has_class('settings-page'):
        children = parent.get_children()
        parent = children[-1] if children and children[-1].get_style_context().has_class('settings-group') else group(parent)
    line = Gtk.Box(spacing=18)
    line.get_style_context().add_class('setting-row')
    copy = column(4)
    title_widget = text(title, 'row-title', True)
    title_widget.set_max_width_chars(48)
    copy.pack_start(title_widget, False, False, 0)
    if description:
        detail = text(description, 'muted', True)
        detail.set_max_width_chars(48)
        copy.pack_start(detail, False, False, 0)
    line.pack_start(copy, True, True, 0)
    if widget:
        widget.set_valign(Gtk.Align.CENTER)
        widget.get_accessible().set_name(title)
        line.pack_end(widget, False, False, 0)
    parent.pack_start(line, False, False, 0)
    return line


class Settings(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='io.github.g8d.Settings', flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.add_main_option('about', 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE, 'Открыть раздел «О системе»', None)
        self.connect('command-line', self.command_line)
        self.window = None
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix='g8d-settings')
        self.screen_snapshot = None
        self.screen_timer = 0
        self.screen_dialog = None
        self.updating = False
        self.pages = {}
        self.monitor_controls = []
        self.volume_timer = 0
        self.connect('activate', self.activate)
        self.connect('shutdown', self.shutdown)

    def command_line(self, _, command):
        self.activate()
        if command.get_options_dict().contains('about'):
            self.search.set_text('')
            self.list.select_row(next(row for row in self.list.get_children() if row.page == 'about'))
        return 0

    def work(self, operation, done=None, success=''):
        future = self.pool.submit(operation)
        def completed(result):
            try:
                value = result.result()
                if done: done(value)
                if success: self.message(success)
            except Exception as exc:
                self.message(str(exc), error=True)
            return False
        future.add_done_callback(lambda result: GLib.idle_add(completed, result))

    def message(self, value, error=False):
        if getattr(self, 'notice_timer', 0):
            GLib.source_remove(self.notice_timer)
            self.notice_timer = 0
        self.notice.set_text(value[:650])
        self.notice.get_style_context().remove_class('error')
        if error: self.notice.get_style_context().add_class('error')
        self.notice_reveal.set_reveal_child(True)
        if not error:
            def hide():
                self.notice_timer = 0
                self.notice_reveal.set_reveal_child(False)
                return False
            self.notice_timer = GLib.timeout_add_seconds(6, hide)

    def launch(self, command):
        if not shutil.which(command[0]):
            self.message('Это приложение не установлено: ' + command[0], True)
            return
        try: subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc: self.message(str(exc), True)

    def activate(self, *_):
        if self.window:
            self.window.present()
            return
        self.window = Gtk.ApplicationWindow(application=self, title='Настройки g8d')
        self.window.set_default_size(1060, 760)
        self.window.set_size_request(780, 560)
        self.window.get_style_context().add_class('g8d-settings')
        self.window.set_icon_name('preferences-system')
        self.window.connect('delete-event', self.closing)
        self.window.connect('key-press-event', self.key)
        Gtk.IconTheme.get_default().prepend_search_path(str(PLUGINS / 'icons'))
        header = Gtk.HeaderBar(title='Настройки')
        header.set_show_close_button(True)
        refresh = Gtk.Button()
        refresh.add(Gtk.Image.new_from_icon_name('g8d-refresh-symbolic', Gtk.IconSize.LARGE_TOOLBAR))
        refresh.get_style_context().add_class('icon-button')
        refresh.set_tooltip_text('Обновить данные')
        refresh.get_accessible().set_name('Обновить данные')
        refresh.connect('clicked', lambda *_: self.refresh())
        header.pack_end(refresh)
        self.window.set_titlebar(header)
        self.install_css()
        layout = Gtk.Box()
        self.sidebar = sidebar = column(8)
        sidebar.get_style_context().add_class('sidebar')
        sidebar.set_size_request(244, -1)
        self.brand_label=text(branding.read(), 'brand')
        sidebar.pack_start(self.brand_label, False, False, 8)
        self.nav_caption = text('Рабочий стол', 'muted')
        sidebar.pack_start(self.nav_caption, False, False, 0)
        self.search = Gtk.SearchEntry()
        self.search.set_width_chars(28)
        self.search.set_placeholder_text('Поиск настроек')
        self.search.get_accessible().set_name('Поиск настроек')
        self.search.connect('search-changed', self.search_settings)
        header.set_custom_title(self.search)
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_UP_DOWN)
        self.stack.set_transition_duration(180 if Gtk.Settings.get_default().get_property('gtk-enable-animations') else 0)
        self.stack.set_vhomogeneous(False)
        self.list = Gtk.ListBox()
        self.list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list.connect('row-selected', self.page_selected)
        self.list.set_filter_func(lambda item: self.matches_search(item))
        nav_scroll = Gtk.ScrolledWindow()
        nav_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        nav_scroll.add(self.list)
        sidebar.pack_start(nav_scroll, True, True, 8)
        sections = [('network', 'Wi-Fi и сеть', 'Сети, подключения и VPN'),
                    ('bluetooth', 'Bluetooth', 'Устройства и сопряжение'),
                    ('display', 'Экраны', 'Разрешение, масштаб и расположение'),
                    ('defaults', 'Приложения', 'Что открывать по умолчанию'),
                    ('shortcuts', 'Горячие клавиши', 'Приложения и свои команды'),
                    ('appearance', 'Оформление', 'Обои, цвета и эффекты'),
                    ('audio', 'Звук', 'Громкость, выход и микрофон'),
                    ('about', 'О системе', 'Сессия и горячие клавиши')]
        for key, title, subtitle in sections:
            item = Gtk.ListBoxRow()
            item.page = key
            item.search_text = title + ' ' + subtitle
            item.set_tooltip_text(title)
            item.get_accessible().set_name(title)
            symbols = {'network':'wifi', 'bluetooth':'bluetooth', 'display':'desktop-windows', 'defaults':'apps',
                       'shortcuts':'keyboard', 'appearance':'palette', 'audio':'volume-up', 'about':'info'}
            content = Gtk.Box(spacing=14)
            content.get_style_context().add_class('nav-item')
            icon = Gtk.Image.new_from_icon_name('g8d-' + symbols[key] + '-symbolic', Gtk.IconSize.LARGE_TOOLBAR)
            icon.set_pixel_size(22)
            content.pack_start(icon, False, False, 0)
            item.caption = text(title)
            content.pack_start(item.caption, True, True, 0)
            item.add(content); self.list.add(item)
            page = column(18)
            page.get_style_context().add_class('settings-page')
            page.set_border_width(28)
            page.pack_start(text(title, 'title'), False, False, 0)
            page.pack_start(text(subtitle, 'muted'), False, False, 0)
            self.pages[key] = page
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.add(page)
            self.stack.add_named(scroll, key)
        empty = column(12)
        empty.set_border_width(32)
        empty.pack_start(text('Ничего не найдено', 'title'), False, False, 0)
        empty.pack_start(text('Попробуй другое название настройки.', 'muted'), False, False, 0)
        self.stack.add_named(empty, 'search-empty')
        main = column(0)
        self.notice_reveal = Gtk.Revealer()
        self.notice = text('', 'notice', True)
        self.notice.set_margin_start(28); self.notice.set_margin_end(28)
        self.notice.set_margin_top(12); self.notice.set_margin_bottom(12)
        self.notice_reveal.add(self.notice)
        main.pack_start(self.notice_reveal, False, False, 0)
        main.pack_start(self.stack, True, True, 0)
        layout.pack_start(sidebar, False, False, 0)
        layout.pack_start(main, True, True, 0)
        self.window.add(layout)
        self.build_network()
        self.build_bluetooth()
        self.build_display()
        self.build_defaults()
        self.shortcuts_page = shortcuts_ui.ShortcutPage(self, self.pages['shortcuts'])
        self.build_appearance()
        self.build_audio()
        self.build_about()
        self.window.show_all()
        ui_themes.apply_typography(self.window, appearance.interface_style())
        self.list.select_row(self.list.get_row_at_index(0))
        self.refresh()
        self.compact_navigation = None
        self.window.connect('size-allocate', self.resize_navigation)

    def install_css(self):
        css = Gtk.CssProvider()
        css.load_from_path(str(ROOT / 'plugins/settings.css'))
        screen = Gdk.Screen.get_default()
        if getattr(self, 'css', None): Gtk.StyleContext.remove_provider_for_screen(screen, self.css)
        Gtk.StyleContext.add_provider_for_screen(screen, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.css = css
        if not getattr(self, 'material_css', None):
            self.material_css = Gtk.CssProvider()
            self.material_css.load_from_path(str(PLUGINS / 'settings-material.css'))
            Gtk.StyleContext.add_provider_for_screen(screen, self.material_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        if not getattr(self, 'interface_css', None):
            self.interface_css = Gtk.CssProvider()
            Gtk.StyleContext.add_provider_for_screen(screen, self.interface_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 2)
        style = appearance.interface_style()
        if style == 'nothing': self.interface_css.load_from_path(str(PLUGINS / 'nothing.css'))
        else: self.interface_css.load_from_data(b'')
        if self.window: ui_themes.apply_typography(self.window, style)

    def resize_navigation(self, _, allocation):
        compact = allocation.width < 940
        if compact == self.compact_navigation: return
        self.compact_navigation = compact
        context = self.sidebar.get_style_context()
        context.add_class('compact') if compact else context.remove_class('compact')
        self.sidebar.set_size_request(76 if compact else 244, -1)
        self.brand_label.set_visible(not compact)
        self.nav_caption.set_visible(not compact)
        for item in self.list.get_children():
            item.caption.set_visible(not compact)
            item.get_child().set_halign(Gtk.Align.CENTER if compact else Gtk.Align.FILL)

    def matches_search(self, item):
        query = self.search.get_text().strip().casefold()
        if not query: return True
        def labels(widget):
            if isinstance(widget, Gtk.Label): yield widget.get_text()
            if isinstance(widget, Gtk.Container):
                for child in widget.get_children(): yield from labels(child)
        content = item.search_text + ' ' + ' '.join(labels(self.pages[item.page]))
        return query in content.casefold()

    def search_settings(self, *_):
        self.list.invalidate_filter()
        available = [item for item in self.list.get_children() if self.matches_search(item)]
        if not available:
            self.stack.set_visible_child_name('search-empty')
        elif self.list.get_selected_row() not in available or self.stack.get_visible_child_name() == 'search-empty':
            target = next((item for item in available if item.page == getattr(self, 'last_page', None)), available[0])
            self.list.select_row(target)
            self.stack.set_visible_child_name(target.page)

    def refresh_appearance(self):
        self.install_css()
        state = appearance.read_selection()
        self.appearance_updating = True
        self.theme_combo.set_active_id(appearance.theme_name(state))
        self.ui_style_combo.set_active_id(appearance.interface_style(state))
        self.mode_combo.set_active_id(appearance.theme_mode(state))
        self.auto_colors.set_active(bool(state.get('wallpaper_colors')))
        source = state.get('palette_output')
        if source and source not in self.palette_outputs:
            self.palette_output.append(source, source)
            self.palette_outputs.add(source)
        if source: self.palette_output.set_active_id(source)
        self.appearance_updating = False
        self.lock_background_status.set_text(Path(state['lock_background']).name if state.get('lock_background') else 'Однотонный фон темы')
        self.appearance_status.set_text('Стиль: ' + appearance.UI_STYLES[appearance.interface_style(state)] + ' · Таскбар: ' + appearance.TASKBAR_STYLES[appearance.theme_name(state)] +
                                        ' · ' + appearance.MODES[appearance.theme_mode(state)] + ' · Акцент: ' + state['accent'] +
                                        (' · По обоям' if state.get('wallpaper_colors') else ' · Вручную'))
        return False

    def appearance_changed(self, *_):
        if getattr(self, 'appearance_timer', 0): GLib.source_remove(self.appearance_timer)
        def refresh():
            self.appearance_timer = 0
            return self.refresh_appearance()
        self.appearance_timer = GLib.timeout_add(120, refresh)

    def apply_theme(self):
        theme = self.theme_combo.get_active_id()
        mode = self.mode_combo.get_active_id()
        ui_style = self.ui_style_combo.get_active_id()
        if theme not in appearance.THEMES: return
        self.theme_apply.set_sensitive(False)
        self.theme_combo.set_sensitive(False)
        self.ui_style_combo.set_sensitive(False)
        self.mode_combo.set_sensitive(False)
        self.auto_colors.set_sensitive(False)
        self.palette_output.set_sensitive(False)
        self.palette_pick.set_sensitive(False)
        self.palette_edit.set_sensitive(False)
        command = ['python3', str(PLUGINS / 'appearance.py'), 'apply', '--taskbar-style', theme, '--ui-style', ui_style]
        if mode != appearance.theme_mode(): command += ['--mode', mode]
        def operation():
            try:
                run(command)
                return None
            except Exception as exc: return str(exc)
        def done(error):
            self.theme_apply.set_sensitive(True)
            self.theme_combo.set_sensitive(True)
            self.ui_style_combo.set_sensitive(True)
            self.mode_combo.set_sensitive(True)
            self.auto_colors.set_sensitive(True)
            self.palette_output.set_sensitive(True)
            self.palette_pick.set_sensitive(True)
            self.palette_edit.set_sensitive(True)
            self.refresh_appearance()
            self.message(error if error else 'Стиль ' + appearance.UI_STYLES[ui_style] + ' применён', bool(error))
        self.work(operation, done)

    def set_wallpaper_colors(self, enabled):
        if getattr(self, 'appearance_updating', False): return
        command = ['python3', str(PLUGINS / 'appearance.py'), 'apply', '--auto-theme', 'on' if enabled else 'off']
        output = self.palette_output.get_active_id()
        if output: command += ['--output', output]
        self.auto_colors.set_sensitive(False)
        self.palette_output.set_sensitive(False)
        self.palette_pick.set_sensitive(False)
        self.theme_apply.set_sensitive(False)
        self.theme_combo.set_sensitive(False)
        self.ui_style_combo.set_sensitive(False)
        self.mode_combo.set_sensitive(False)
        self.palette_edit.set_sensitive(False)
        def operation():
            try: run(command, timeout=35); return None
            except Exception as exc: return str(exc)
        def done(error):
            self.auto_colors.set_sensitive(True)
            self.palette_output.set_sensitive(True)
            self.palette_pick.set_sensitive(True)
            self.theme_apply.set_sensitive(True)
            self.theme_combo.set_sensitive(True)
            self.ui_style_combo.set_sensitive(True)
            self.mode_combo.set_sensitive(True)
            self.palette_edit.set_sensitive(True)
            self.refresh_appearance()
            self.message(error if error else 'Тема и акцент подобраны по обоям' if enabled else 'Автоподбор выключен', bool(error))
        self.work(operation, done)

    def edit_theme_colors(self):
        state = appearance.read_selection()
        theme = appearance.theme_name(state)
        mode = appearance.theme_mode(state)
        ui_style = appearance.interface_style(state)
        title = appearance.UI_STYLES[ui_style] + ' · ' + appearance.THEMES[theme] + ' · ' + appearance.MODES[mode]
        dialog = Gtk.Dialog(title='Цвета темы · ' + title, transient_for=self.window, modal=True)
        dialog.get_style_context().add_class('g8d-settings')
        dialog.get_style_context().add_class('palette-editor')
        dialog.set_default_size(600, -1)
        dialog.set_resizable(False)
        header = Gtk.HeaderBar(title='Цвета темы · ' + title)
        header.set_show_close_button(True)
        dialog.set_titlebar(header)
        dialog.add_button('Сбросить', 1001)
        dialog.add_button('Отмена', Gtk.ResponseType.CANCEL)
        dialog.add_button('Применить', Gtk.ResponseType.OK).get_style_context().add_class('suggested-action')
        body = dialog.get_content_area()
        body.set_border_width(20); body.set_spacing(10)
        body.pack_start(text('Изменения сохранятся для ' + title + '. Применение выключит автоподбор.\nАкцент подстраивается для читаемости.', 'muted', True), False, False, 0)
        fields = {}
        colors = {'accent': state['accent'], **appearance.theme_colors(theme, state)}
        labels = {'accent': 'Акцент', **appearance.COLOR_LABELS}
        grid = Gtk.Grid(column_spacing=16, row_spacing=8)
        body.pack_start(grid, False, False, 0)
        def rgba(value):
            color = Gdk.RGBA(); color.parse(value); return color
        for index, (key, title) in enumerate(labels.items()):
            name = text(title)
            entry = Gtk.Entry(); entry.set_width_chars(9); entry.set_max_length(7); entry.set_text(colors[key])
            entry.get_accessible().set_name(title + ' · #RRGGBB')
            swatch = Gtk.ColorButton.new_with_rgba(rgba(colors[key]))
            swatch.set_title(title); swatch.set_use_alpha(False)
            swatch.get_accessible().set_name('Выбрать цвет: ' + title)
            def color_set(widget, field=entry):
                color = widget.get_rgba()
                field.set_text('#' + ''.join(f'{round(c * 255):02x}' for c in (color.red, color.green, color.blue)))
            swatch.connect('color-set', color_set)
            entry.connect('changed', lambda field, swatch=swatch: swatch.set_rgba(rgba(field.get_text())) if re.fullmatch(r'#[0-9a-fA-F]{6}', field.get_text()) else None)
            name.set_hexpand(True)
            grid.attach(name, 0, index, 1, 1); grid.attach(entry, 1, index, 1, 1); grid.attach(swatch, 2, index, 1, 1)
            fields[key] = entry
        status = text('', 'error', True)
        body.pack_start(status, False, False, 0)
        def response(_, code):
            if code == 1001:
                for key, value in {'accent': '#8bbfba', **appearance.default_colors(theme, mode, ui_style)}.items(): fields[key].set_text(value)
                status.set_text('Цвета сброшены. Нажми «Применить», чтобы сохранить.')
                return
            if code != Gtk.ResponseType.OK: dialog.destroy(); return
            values = {key: field.get_text().strip().lower() for key, field in fields.items()}
            try:
                for key, value in values.items():
                    if not re.fullmatch(r'#[0-9a-f]{6}', value): raise ValueError(labels[key] + ': введи #RRGGBB')
                custom = appearance.validate_colors({key: value for key, value in values.items() if key != 'accent'}, theme, mode, ui_style)
                custom = {key: value for key, value in custom.items() if value != appearance.default_colors(theme, mode, ui_style)[key]}
            except ValueError as exc: status.set_text(str(exc)); return
            for code in (1001, Gtk.ResponseType.CANCEL, Gtk.ResponseType.OK): dialog.set_response_sensitive(code, False)
            dialog.set_deletable(False)
            command = ['python3', str(PLUGINS / 'appearance.py'), 'apply', '--theme', theme,
                       '--mode', mode, '--ui-style', ui_style, '--accent', values['accent'], '--colors', json.dumps(custom)]
            def operation():
                try: run(command); return None
                except Exception as exc: return str(exc)
            def done(error):
                if error:
                    status.set_text(error)
                    dialog.set_deletable(True)
                    for code in (1001, Gtk.ResponseType.CANCEL, Gtk.ResponseType.OK): dialog.set_response_sensitive(code, True)
                else:
                    dialog.destroy(); self.refresh_appearance(); self.message('Цвета темы сохранены')
            self.work(operation, done)
        dialog.connect('response', response)
        dialog.show_all()

    def page_selected(self, _, item):
        if item:
            self.last_page = item.page
            self.stack.set_visible_child_name(item.page)

    def key(self, _, event):
        if event.keyval in (Gdk.KEY_f, Gdk.KEY_F) and event.state & Gdk.ModifierType.CONTROL_MASK:
            self.search.grab_focus()
            return True
        if event.keyval == Gdk.KEY_Escape:
            if self.search.get_text():
                self.search.set_text('')
                return True
            self.window.close()
            return True
        return False

    def build_network(self):
        page = self.pages['network']
        self.wifi_busy = False
        self.wifi_device = ''
        self.wifi_networks = []
        self.wifi = Gtk.Switch()
        self.wifi.connect('notify::active', self.wifi_changed)
        row(page, 'Wi-Fi', 'Включить или отключить беспроводную сеть', self.wifi)
        self.wifi_refresh = button('Найти сети', lambda: self.refresh_wifi(True))
        row(page, 'Доступные сети', 'Выбери сеть и подключись прямо здесь', self.wifi_refresh)
        self.wifi_list = column(0)
        self.wifi_list.get_style_context().add_class('settings-group')
        page.pack_start(self.wifi_list, False, False, 0)
        self.network_status = text('Проверяю подключения…', 'muted', True)
        page.pack_start(self.network_status, False, False, 0)
        row(page, 'Сведения о сети', 'Адреса интерфейсов и активные подключения', button('Обновить', self.refresh_network))

    def wifi_changed(self, switch, _):
        if self.updating: return
        switch.set_sensitive(False)
        enabled = switch.get_active()
        def operation():
            try: return run(['nmcli', 'radio', 'wifi', 'on' if enabled else 'off'])
            finally: GLib.idle_add(self.refresh_network)
        self.work(operation)

    def show_wifi_status(self, value):
        for child in self.wifi_list.get_children(): child.destroy()
        self.wifi_list.pack_start(text(value, 'muted', True), False, False, 0)
        self.wifi_list.show_all()

    def render_wifi(self, networks):
        self.wifi_networks = networks
        for child in self.wifi_list.get_children(): child.destroy()
        if not self.wifi.get_active():
            self.show_wifi_status('Wi-Fi выключен. Включи его, чтобы увидеть доступные сети.')
            return
        if not networks:
            self.show_wifi_status('Сети не найдены. Нажми «Найти сети», чтобы повторить поиск.')
            return
        for network in networks:
            security = network['security'] or 'Открытая сеть'
            description = f"{network['signal']}% · {security}"
            if network['active']: description = 'Подключено · ' + description
            elif network['saved']: description += ' · сохранённая сеть'
            action = button('Отключить' if network['active'] else 'Подключить',
                            lambda item=network: self.wifi_action(item))
            action.set_sensitive(not self.wifi_busy)
            row(self.wifi_list, network['ssid'], description, action)
        self.wifi_list.show_all()

    def refresh_wifi(self, rescan=False):
        if self.wifi_busy: return
        if not self.wifi.get_active():
            self.wifi_refresh.set_sensitive(False)
            self.render_wifi([])
            return
        self.wifi_busy = True
        self.wifi_refresh.set_sensitive(False)
        self.show_wifi_status('Ищу доступные сети…' if rescan else 'Получаю список сетей…')
        def operation():
            try: return wifi.scan(rescan)
            except Exception as exc: return exc
        def done(result):
            self.wifi_busy = False
            self.wifi_refresh.set_sensitive(self.wifi.get_active())
            if isinstance(result, Exception):
                self.show_wifi_status('Не удалось получить список сетей.')
                self.message(str(result), True)
                return
            self.wifi_device = result['device']
            self.render_wifi(result['networks'])
        self.work(operation, done)

    def wifi_action(self, network):
        if self.wifi_busy: return
        if network['active'] or not wifi.needs_password(network):
            self.start_wifi_connection(network)
        else:
            self.ask_wifi_password(network)

    def ask_wifi_password(self, network):
        dialog = Gtk.Dialog(title='Подключение к '+network['ssid'], transient_for=self.window, modal=True)
        dialog.get_style_context().add_class('g8d-settings')
        dialog.add_button('Отмена', Gtk.ResponseType.CANCEL)
        dialog.add_button('Подключить', Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        content = dialog.get_content_area()
        content.set_spacing(12)
        content.set_border_width(18)
        content.pack_start(text('Введи пароль для '+network['ssid'], wrap=True), False, False, 0)
        entry = Gtk.Entry()
        entry.set_visibility(False)
        entry.set_placeholder_text('Пароль Wi-Fi')
        entry.connect('activate', lambda *_: dialog.response(Gtk.ResponseType.OK))
        content.pack_start(entry, False, False, 0)
        visible = Gtk.CheckButton(label='Показать пароль')
        visible.connect('toggled', lambda toggle: entry.set_visibility(toggle.get_active()))
        content.pack_start(visible, False, False, 0)
        dialog.connect('response', self.wifi_password_response, network, entry)
        dialog.show_all()
        entry.grab_focus()

    def wifi_password_response(self, dialog, response, network, entry):
        if response == Gtk.ResponseType.OK:
            password = entry.get_text()
            if not password:
                self.message('Введите пароль сети', True)
                return
            self.start_wifi_connection(network, password)
        dialog.destroy()

    def start_wifi_connection(self, network, password=None):
        if self.wifi_busy: return
        self.wifi_busy = True
        self.wifi_refresh.set_sensitive(False)
        self.render_wifi(self.wifi_networks)
        def operation():
            try:
                if network['active']: wifi.disconnect(self.wifi_device)
                else: wifi.connect(network['ssid'], self.wifi_device, password)
            except Exception as exc: return exc
            return None
        def done(result):
            self.wifi_busy = False
            if isinstance(result, Exception): self.message(str(result), True)
            elif network['active']: self.message('Отключено от '+network['ssid'])
            else: self.message('Подключено к '+network['ssid'])
            self.refresh_network()
        self.work(operation, done)

    def refresh_network(self):
        def operation():
            enabled = run(['nmcli', '-t', '-f', 'WIFI', 'general']) == 'enabled'
            devices = run(['nmcli', '-t', '-f', 'DEVICE,TYPE,STATE,CONNECTION', 'device'])
            addresses = json.loads(run(['ip', '-j', 'address']))
            ips = {item['ifname']: [a['local'] for a in item['addr_info'] if a.get('scope') == 'global'] for item in addresses}
            lines = []
            for device in devices.splitlines():
                values = wifi.fields(device)
                if len(values) != 4 or values[1] == 'loopback': continue
                name, kind, state, connection = values
                title = {'ethernet':'Проводная сеть', 'wifi':'Wi-Fi', 'tun':'VPN'}.get(kind,kind)
                lines.append(title+' · '+name+' · '+state)
                if connection and connection != '--': lines.append(connection)
                if ips.get(name): lines.append(' · '.join(ips[name]))
                lines.append('')
            return enabled, '\n'.join(lines).strip()
        def done(result):
            self.updating = True
            self.wifi.set_active(result[0]); self.wifi.set_sensitive(True)
            self.updating = False
            self.network_status.set_text(result[1] or 'Подключения не найдены')
            self.wifi_refresh.set_sensitive(result[0] and not self.wifi_busy)
            self.refresh_wifi()
        self.work(operation, done)

    def build_bluetooth(self):
        page = self.pages['bluetooth']
        self.bluetooth = Gtk.Switch()
        self.bluetooth.connect('notify::active', self.bluetooth_changed)
        row(page, 'Bluetooth', 'Включить или отключить адаптер', self.bluetooth)
        self.bluetooth_status = text('Проверяю адаптер…', 'muted', True)
        page.pack_start(self.bluetooth_status, False, False, 0)
        row(page, 'Bluetooth-устройства', 'Поиск, подключение, сопряжение и удаление устройств',
            button('Открыть устройства', lambda: self.launch(['blueman-manager'])))

    def bluetooth_changed(self, switch, _):
        if self.updating: return
        switch.set_sensitive(False)
        enabled = switch.get_active()
        def operation():
            try:
                result = run(['bluetoothctl', 'power', 'on' if enabled else 'off'])
                if 'Failed' in result: raise RuntimeError(result)
                return result
            finally: GLib.idle_add(self.refresh_bluetooth)
        self.work(operation)

    def refresh_bluetooth(self):
        def operation():
            adapter = run(['bluetoothctl', 'show'])
            devices = run(['bluetoothctl', 'devices', 'Connected']) if adapter else ''
            return adapter, devices
        def done(result):
            adapter, devices = result
            self.updating = True
            self.bluetooth.set_active('Powered: yes' in adapter)
            self.bluetooth.set_sensitive('Controller ' in adapter)
            self.updating = False
            name = re.search(r'Alias: (.+)', adapter)
            names = [' '.join(line.split()[2:]) for line in devices.splitlines()]
            self.bluetooth_status.set_text(('Адаптер: '+name[1] if name else 'Адаптер не найден') + '\n' +
                                           ('Подключены: '+', '.join(names) if names else 'Подключённых устройств нет'))
        self.work(operation, done)

    def build_display(self):
        page = self.pages['display']
        self.display_content = column(14)
        page.pack_start(self.display_content, False, False, 0)
        row(page, 'Изменить конфигурацию', 'Если изображение пропадёт, прежние настройки вернутся через 15 секунд.',
            button('Применить', self.apply_display))
        row(page, 'Обновить экраны', 'Обнаружить подключённые мониторы заново', button('Обновить', self.refresh_display))

    def refresh_display(self):
        def done(monitors):
            for child in self.display_content.get_children(): child.destroy()
            self.monitor_controls = []
            for monitor in sorted(monitors, key=lambda m:m['x']):
                card = column(10)
                card.get_style_context().add_class('settings-group')
                card.get_style_context().add_class('monitor-card')
                card.pack_start(text(monitor.get('description') or monitor['name']), False, False, 0)
                card.pack_start(text(monitor['name'], 'muted'), False, False, 0)
                combo = Gtk.ComboBoxText()
                modes = list(dict.fromkeys(monitor.get('availableModes', [])))
                current = f"{monitor['width']}x{monitor['height']}@{monitor['refreshRate']:.2f}Hz"
                active = next((mode for mode in modes if mode.startswith(f"{monitor['width']}x{monitor['height']}@") and abs(float(mode.split('@')[1].removesuffix('Hz'))-monitor['refreshRate']) < .1), None)
                if not active: modes.insert(0,current); active=current
                for mode in modes: combo.append(mode,mode)
                combo.set_active_id(active)
                row(card, 'Разрешение и частота', widget=combo)
                scale = Gtk.ComboBoxText()
                for value in sorted(set([1.,1.25,1.5,1.75,2.,float(monitor['scale'])])):
                    scale.append(str(value),f'{round(value*100)}%')
                scale.set_active_id(str(float(monitor['scale'])))
                row(card, 'Масштаб', widget=scale)
                positions = Gtk.Box(spacing=12)
                coords=[]
                for axis in ('x','y'):
                    positions.pack_start(text(axis.upper()),False,False,0)
                    spin=Gtk.SpinButton.new_with_range(-16000,16000,1)
                    spin.get_accessible().set_name('Положение ' + axis.upper())
                    spin.set_value(monitor[axis]); spin.set_width_chars(5)
                    positions.pack_start(spin,False,False,0);coords.append(spin)
                row(card,'Расположение', 'Координаты верхнего левого угла',positions)
                self.display_content.pack_start(card,False,False,0)
                self.monitor_controls.append((monitor,combo,scale,*coords))
            self.display_content.show_all()
        self.work(lambda:json.loads(run(['hyprctl','-j','monitors'])), done)

    def apply_display(self):
        if not self.monitor_controls or self.screen_snapshot is not None: return
        try:
            instances=json.loads(run(['hyprctl','-j','instances']))
            instance=next((i for i in instances if i['instance']==SIGNATURE), None)
            command=Path(f"/proc/{instance['pid']}/cmdline").read_bytes() if instance else b''
            if str(ROOT/'hyprland.lua').encode() not in command:
                raise RuntimeError('Настройки экранов доступны в сессии hyprland-g8d.')
        except Exception as exc:
            self.message(str(exc),True);return
        lines=['-- Managed by Settings g8d. Previous configuration is backed up before changes.']
        rectangles=[]
        for monitor,combo,scale,x,y in self.monitor_controls:
            mode=combo.get_active_id().removesuffix('Hz')
            factor=float(scale.get_active_id())
            width,height=map(int,mode.split('@')[0].split('x'))
            if monitor.get('transform',0)%2: width,height=height,width
            if abs(width/factor-round(width/factor))>.01 or abs(height/factor-round(height/factor))>.01:
                self.message('Выбери масштаб, при котором размер экрана делится без остатка.',True);return
            px,py=int(x.get_value()),int(y.get_value())
            rectangles.append((px,py,round(width/factor),round(height/factor)))
            fields={'output':monitor['name'],'mode':mode,'position':f'{px}x{py}','scale':factor,'transform':monitor.get('transform',0)}
            lines.append('hl.monitor({'+', '.join(k+' = '+json.dumps(v) for k,v in fields.items())+'})')
        for i,(x,y,w,h) in enumerate(rectangles):
            for xx,yy,ww,hh in rectangles[i+1:]:
                if max(x,xx)<min(x+w,xx+ww) and max(y,yy)<min(y+h,yy+hh):
                    self.message('Экраны перекрываются. Размести их рядом с учётом масштаба.',True);return
        try:
            self.screen_snapshot = MONITORS.read_text() if MONITORS.exists() else ''
            if self.screen_snapshot: atomic(MONITORS.with_suffix('.lua.bak'),self.screen_snapshot)
            atomic(MONITORS,'\n'.join(lines)+'\n')
            run(['hyprctl','reload'])
            errors=run(['hyprctl','configerrors'])
            if errors: raise RuntimeError(errors)
        except Exception as exc:
            self.rollback_display()
            self.message(str(exc),True);return
        self.countdown=15
        dialog=Gtk.MessageDialog(transient_for=self.window,modal=True,message_type=Gtk.MessageType.QUESTION,
                                 text='Сохранить настройки экранов?')
        dialog.get_style_context().add_class('g8d-settings')
        dialog.add_button('Вернуть прежние',Gtk.ResponseType.CANCEL)
        dialog.add_button('Сохранить',Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.CANCEL)
        dialog.connect('response',self.confirm_display)
        self.screen_dialog=dialog
        self.screen_timer=GLib.timeout_add_seconds(1,self.display_tick)
        dialog.format_secondary_text('Автоматический возврат через 15 секунд.')
        dialog.show_all()

    def display_tick(self):
        self.countdown-=1
        if self.countdown<=0:
            self.screen_timer=0
            self.screen_dialog.response(Gtk.ResponseType.CANCEL)
            return False
        self.screen_dialog.format_secondary_text(f'Автоматический возврат через {self.countdown} секунд.')
        return True

    def rollback_display(self):
        if self.screen_snapshot is None: return
        try:
            if self.screen_snapshot: atomic(MONITORS,self.screen_snapshot)
            else: MONITORS.unlink(missing_ok=True)
            run(['hyprctl','reload'])
        finally: self.screen_snapshot=None

    def confirm_display(self, dialog, response):
        if self.screen_timer: GLib.source_remove(self.screen_timer);self.screen_timer=0
        dialog.destroy();self.screen_dialog=None
        if response==Gtk.ResponseType.OK:
            self.screen_snapshot=None
            self.message('Настройки экранов сохранены')
        else:
            try: self.rollback_display();self.message('Прежние настройки экранов восстановлены')
            except Exception as exc:self.message(str(exc),True)
        self.refresh_display()

    def build_defaults(self):
        page=self.pages['defaults']
        page.pack_start(text('Выбор применяется сразу для текущего пользователя.', 'muted', True),False,False,0)
        search_card = column(10)
        search_card.get_style_context().add_class('setting-row')
        search_card.pack_start(text('Найти формат файла'), False, False, 0)
        self.format_entry = Gtk.SearchEntry()
        self.format_entry.set_placeholder_text('Расширение: pdf, .mp4, docx, tar.gz')
        self.format_entry.connect('search-changed', lambda *_: self.lookup_format())
        self.format_entry.connect('activate', lambda *_: self.lookup_format())
        search_card.pack_start(self.format_entry, False, False, 0)
        self.format_status = text('Введи расширение, чтобы узнать приложение по умолчанию.', 'muted', True)
        search_card.pack_start(self.format_status, False, False, 0)
        self.format_info = None
        self.format_button = button('Выбрать другое приложение…', self.choose_format_app)
        self.format_button.set_sensitive(False)
        search_card.pack_start(self.format_button, False, False, 0)
        page.pack_start(search_card, False, False, 0)
        self.default_selectors=[]
        groups=[('Браузер',['x-scheme-handler/http','x-scheme-handler/https','text/html']),
                ('Файловый менеджер',['inode/directory']),('Почта',['x-scheme-handler/mailto']),
                ('Текстовые файлы',['text/plain']),('PDF-документы',['application/pdf']),
                ('Изображения',['image/png','image/jpeg','image/webp']),
                ('Музыка',['audio/mpeg','audio/flac','audio/ogg']),
                ('Видео',['video/mp4','video/x-matroska','video/webm']),('Архивы ZIP',['application/zip'])]
        for title,types in groups:
            apps={a.get_id():a for mime in types for a in Gio.AppInfo.get_all_for_type(mime) if a.get_id() and a.should_show()}
            default=Gio.AppInfo.get_default_for_type(types[0],False)
            if default and default.get_id():apps[default.get_id()]=default
            combo=Gtk.ComboBoxText()
            for ident,app in sorted(apps.items(),key=lambda p:p[1].get_display_name().casefold()):
                combo.append(ident,app.get_display_name())
            if default:combo.set_active_id(default.get_id())
            else:combo.set_active(-1)
            combo.set_size_request(240,-1)
            combo.set_sensitive(bool(apps))
            combo._apps = apps
            combo.connect('changed',self.default_changed,types,apps)
            row(page,title,widget=combo)
            self.default_selectors.append((combo,types))

    def lookup_format(self):
        try:
            self.format_info = file_associations.resolve(self.format_entry.get_text())
        except ValueError as exc:
            self.format_info = None
            self.format_status.set_text(str(exc))
        else:
            info = self.format_info
            if info is None:
                self.format_status.set_text('Введи расширение, чтобы узнать приложение по умолчанию.')
            else:
                current = info['app'].get_display_name() if info['app'] else 'Не выбрано'
                description = '.'+info['extension']+' · '+info['description']+'\nОткрывается: '+current
                if info['custom']:
                    description += '\nНовый формат: выбор приложения создаст ассоциацию для этого расширения.'
                else:
                    description += '\nВыбор применяется к этому типу файлов, включая его другие расширения.'
                self.format_status.set_text(description)
        self.format_button.set_sensitive(self.format_info is not None)

    def choose_format_app(self):
        if not self.format_info: return
        info = dict(self.format_info)
        dialog = Gtk.AppChooserDialog.new_for_content_type(self.window, Gtk.DialogFlags.MODAL, info['mime'])
        dialog.get_style_context().add_class('g8d-settings')
        dialog.set_title('Чем открывать файлы .'+info['extension']+'?')
        chooser = dialog.get_widget()
        chooser.set_show_all(True)
        chooser.set_show_recommended(True)
        chooser.set_show_other(True)
        dialog.connect('response', self.format_app_selected, info)
        dialog.show_all()

    def format_app_selected(self, dialog, response, info):
        selected = dialog.get_app_info() if response == Gtk.ResponseType.OK else None
        dialog.destroy()
        if selected is None: return
        self.format_button.set_sensitive(False)
        def operation():
            return file_associations.associate(info, selected)
        def done(_):
            self.lookup_format()
            self.updating=True
            for combo, types in self.default_selectors:
                current=Gio.AppInfo.get_default_for_type(types[0],False)
                if current:
                    if current.get_id() not in combo._apps:
                        combo._apps[current.get_id()] = current
                        combo.append(current.get_id(),current.get_display_name())
                    combo.set_active_id(current.get_id())
            self.updating=False
        def work():
            try: operation()
            except Exception as exc:
                GLib.idle_add(self.message,str(exc),True)
                GLib.idle_add(self.lookup_format)
            else:
                GLib.idle_add(done,None)
                GLib.idle_add(self.message,'.'+info['extension']+' → '+selected.get_display_name())
        self.pool.submit(work)

    def default_changed(self, combo, types, apps):
        if self.updating:return
        app=apps.get(combo.get_active_id())
        if not app:return
        previous=[Gio.AppInfo.get_default_for_type(mime,False) for mime in types]
        applied=[]
        try:
            for mime in types:
                if not app.set_as_default_for_type(mime):raise RuntimeError('Не удалось сохранить выбор')
                applied.append(mime)
            self.message('По умолчанию: '+app.get_display_name())
            self.lookup_format()
        except Exception as exc:
            for mime,old in zip(types,previous):
                if mime in applied and old: old.set_as_default_for_type(mime)
            self.updating=True
            combo.set_active_id(previous[0].get_id() if previous[0] else None)
            self.updating=False
            self.message(str(exc),True)

    def build_appearance(self):
        page = self.pages['appearance']
        palette = group(page, 'Тема и палитра')
        self.ui_style_combo = Gtk.ComboBoxText()
        self.ui_style_combo.get_accessible().set_name('Стиль интерфейса')
        for key, title in appearance.UI_STYLES.items(): self.ui_style_combo.append(key, title)
        self.ui_style_combo.set_active_id(appearance.interface_style())
        row(palette, 'Стиль интерфейса', 'Material или Nothing · меню, настройки и поиск', self.ui_style_combo)
        self.theme_combo = Gtk.ComboBoxText()
        self.theme_combo.get_accessible().set_name('Стиль таскбара')
        self.theme_combo.append('graphite', 'Graphite')
        self.theme_combo.append('clear', 'Clear')
        self.theme_combo.set_active_id(appearance.theme_name())
        self.mode_combo = Gtk.ComboBoxText()
        self.mode_combo.get_accessible().set_name('Светлая или тёмная тема')
        for key, title in appearance.MODES.items(): self.mode_combo.append(key, title)
        self.mode_combo.set_active_id(appearance.theme_mode())
        self.theme_apply = button('Применить', self.apply_theme)
        self.theme_apply.get_style_context().add_class('suggested-action')
        row(palette, 'Стиль таскбара', 'Graphite — сплошной · Clear — прозрачный', self.theme_combo)
        mode_controls = Gtk.Box(spacing=8)
        mode_controls.pack_start(self.mode_combo, False, False, 0)
        mode_controls.pack_start(self.theme_apply, False, False, 0)
        row(palette, 'Светлый или тёмный режим', 'Оба режима доступны для каждого стиля', mode_controls)
        self.auto_colors = Gtk.Switch()
        self.auto_colors.set_active(bool(appearance.read_selection().get('wallpaper_colors')))
        self.auto_colors.connect('notify::active', lambda switch, *_: self.set_wallpaper_colors(switch.get_active()))
        row(palette, 'Цвета из обоев', 'Подбирать яркость и акцент, сохраняя выбранный стиль', self.auto_colors)
        self.palette_output = Gtk.ComboBoxText()
        self.palette_outputs = set()
        try: outputs = appearance.monitors()
        except Exception: outputs = []
        for monitor in outputs:
            name = monitor['name']
            self.palette_output.append(name, monitor.get('description') or name)
            self.palette_outputs.add(name)
        if outputs: self.palette_output.set_active_id(next((m['name'] for m in outputs if m.get('focused')), outputs[0]['name']))
        self.palette_output.connect('changed', lambda *_: self.set_wallpaper_colors(self.auto_colors.get_active()))
        row(palette, 'Экран-источник', 'Его обои задают общую палитру', self.palette_output)
        self.palette_pick = button('Подобрать', lambda: self.set_wallpaper_colors(True))
        self.palette_edit = button('Настроить', self.edit_theme_colors)
        color_actions = Gtk.Box(spacing=8)
        color_actions.pack_start(self.palette_pick, False, False, 0)
        color_actions.pack_start(self.palette_edit, False, False, 0)
        row(palette, 'Палитра', 'Акцент, поверхности, текст и границы', color_actions)
        self.appearance_status = text('', 'muted', True)
        page.pack_start(self.appearance_status, False, False, 0)

        wallpapers = group(page, 'Обои')
        row(wallpapers, 'Изображение или видео', 'Можно выбрать отдельно для каждого экрана',
            button('Выбрать', lambda: self.launch([str(ROOT/'actions'), 'appearance'])))
        row(wallpapers, 'Моя коллекция', str(Path.home()/'Изображения/wallpaper'),
            button('Открыть', lambda: self.launch(['xdg-open', str(Path.home()/'Изображения/wallpaper')])))

        lock = group(page, 'Экран блокировки')
        lock_actions = Gtk.Box(spacing=8)
        lock_actions.pack_start(button('Выбрать фон', self.choose_lock_background), False, False, 0)
        lock_actions.pack_start(button('Однотонный', lambda: self.save_lock_background('')), False, False, 0)
        row(lock, 'Фон блокировки', 'Часы и пароль на полупрозрачной подложке', lock_actions)
        self.lock_background_status = text('', 'muted', True)
        lock.pack_start(self.lock_background_status, False, False, 0)

        shell = group(page, 'Персонализация')
        self.brand_entry = Gtk.Entry()
        self.brand_entry.get_accessible().set_name('Название оболочки')
        self.brand_entry.set_max_length(32)
        self.brand_entry.set_text(branding.read())
        self.brand_entry.connect('activate', lambda *_: self.save_brand())
        brand_controls = Gtk.Box(spacing=8)
        self.brand_entry.set_width_chars(12)
        brand_controls.pack_start(self.brand_entry, True, True, 0)
        brand_controls.pack_start(button('Сохранить', self.save_brand), False, False, 0)
        row(shell, 'Название оболочки', 'На панели и экране блокировки', brand_controls)
        self.effect_switch = Gtk.Switch()
        self.effect_switch.set_active(read_json(EFFECTS, {}).get('enabled', True))
        self.effect_switch.connect('notify::active', self.effect_changed)
        row(shell, 'Переход курсора', 'Вспышка при перемещении между экранами', self.effect_switch)
        row(shell, 'Игровой режим', 'Приостанавливает обои, анимации и эффекты', button('Переключить', self.toggle_game))
        self.appearance_monitor = Gio.File.new_for_path(str(ROOT / 'appearance.json')).monitor_file(Gio.FileMonitorFlags.NONE, None)
        self.appearance_monitor.connect('changed', self.appearance_changed)

    def choose_lock_background(self):
        dialog = Gtk.FileChooserDialog(title='Фон экрана блокировки', transient_for=self.window,
                                       action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons('Отмена', Gtk.ResponseType.CANCEL, 'Выбрать', Gtk.ResponseType.OK)
        images = Gtk.FileFilter(); images.set_name('Изображения · PNG, JPEG, WebP')
        for mime in ('image/png', 'image/jpeg', 'image/webp'): images.add_mime_type(mime)
        dialog.add_filter(images)
        current = appearance.read_selection().get('lock_background')
        if current: dialog.set_filename(current)
        else: dialog.set_current_folder(str(Path.home() / 'Изображения'))
        response = dialog.run()
        filename = dialog.get_filename()
        dialog.destroy()
        if response == Gtk.ResponseType.OK and filename: self.save_lock_background(filename)

    def save_lock_background(self, filename):
        def operation():
            try:
                run(['python3', str(PLUGINS / 'appearance.py'), 'apply', '--lock-background', filename])
                return None
            except Exception as exc: return str(exc)
        def done(error):
            self.refresh_appearance()
            self.message(error or 'Фон блокировки сохранён', bool(error))
        self.work(operation, done)

    def save_brand(self):
        try:
            value=branding.save(self.brand_entry.get_text())
            self.brand_entry.set_text(value)
            self.brand_label.set_text(value)
            self.message('Название сохранено')
        except (OSError,ValueError) as exc:self.message(str(exc),True)

    def update_shell(self):
        self.launch(['kitty','--title','Обновление hyprland-g8d','python3',str(PLUGINS/'updater.py')])

    def effect_changed(self,switch,_):
        if self.updating:return
        try:
            atomic(EFFECTS,json.dumps({'enabled':switch.get_active()})+'\n')
            panel({'cursor_effect':switch.get_active()})
            self.message('Настройка эффекта сохранена')
        except OSError as exc:self.message(str(exc),True)

    def toggle_game(self):
        if panel({'game':'toggle'}):self.message('Переключаю игровой режим…')
        else:self.message('Панель g8d сейчас не запущена',True)

    def build_audio(self):
        page=self.pages['audio']
        self.volume=Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,0,100,1)
        self.volume.get_accessible().set_name('Громкость вывода')
        self.volume.set_value_pos(Gtk.PositionType.RIGHT)
        self.volume.set_digits(0)
        self.volume.connect('value-changed',self.volume_changed)
        row(page,'Громкость вывода','Устройство воспроизведения по умолчанию')
        page.get_children()[-1].pack_start(self.volume,False,False,16)
        row(page,'Устройства и приложения','Вывод звука, микрофон, громкость отдельных программ',
            button('Настроить звук',lambda:self.launch(['pavucontrol'])))

    def volume_changed(self,scale):
        if self.updating:return
        if self.volume_timer:GLib.source_remove(self.volume_timer)
        def send():
            self.volume_timer=0
            value=round(scale.get_value())
            self.work(lambda:run(['wpctl','set-volume','@DEFAULT_AUDIO_SINK@',f'{value}%']))
            return False
        self.volume_timer=GLib.timeout_add(180,send)

    def build_about(self):
        page=self.pages['about']
        version=(ROOT/'VERSION').read_text().strip() if (ROOT/'VERSION').exists() else 'Локальная сборка'
        row(page,'Обновление hyprland-g8d',version+' · скачивает последний релиз, включая alpha, с GitHub. Настройки сохраняются; системный Hyprland и пакеты не обновляются.',button('Обновить оболочку',self.update_shell))
        self.about_status=text('','muted',True)
        page.pack_start(self.about_status,False,False,0)
        for title,keys in [('Настройки','Win + Ctrl + S'),('Обои и цвет','Win + W'),('Поиск приложений','Win + R'),
                           ('Окна','Alt + Tab'),('Раскладка','Win + Пробел'),('Блокировка','Win + L')]:
            row(page,title,widget=text(keys,'muted'))
        row(page,'Все сочетания клавиш','Памятка сборки',button('Открыть',lambda:self.launch([str(ROOT/'actions'),'help'])))
        row(page,'Файлы конфигурации',str(ROOT),button('Открыть папку',lambda:self.launch(['xdg-open',str(ROOT)])))

    def refresh(self):
        self.refresh_network();self.refresh_bluetooth();self.refresh_display()
        self.lookup_format()
        self.shortcuts_page.refresh()
        self.updating=True
        self.effect_switch.set_active(read_json(EFFECTS,{}).get('enabled',True))
        self.updating=False
        self.refresh_appearance()
        self.about_status.set_text('Сессия: '+os.environ.get('XDG_CURRENT_DESKTOP','Hyprland')+'\n'+
                                   'Конфигурация: hyprland-g8d\nИзменения оформления и экранов относятся к этой сборке.')
        def done(value):
            match=re.search(r'Volume: ([\d.]+)',value)
            if match:
                self.updating=True;self.volume.set_value(min(100,round(float(match[1])*100)));self.updating=False
        self.work(lambda:run(['wpctl','get-volume','@DEFAULT_AUDIO_SINK@']),done)

    def closing(self,*_):
        if self.screen_snapshot is not None:
            if self.screen_dialog:self.screen_dialog.response(Gtk.ResponseType.CANCEL)
            else:self.rollback_display()
        return False

    def shutdown(self,*_):
        if self.screen_snapshot is not None:self.rollback_display()
        self.pool.shutdown(wait=False,cancel_futures=True)


if __name__=='__main__':
    import sys
    app=Settings()
    raise SystemExit(app.run(sys.argv))
