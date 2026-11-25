"""Compact Wi-Fi network picker and inline password prompt."""
from gi.repository import GLib, Gtk

from quick_settings import accessible, icon_button, image, text
from wifi_networks import valid_password


LIST_HEIGHT = 244


class WifiPanel:
    def __init__(self, controller, go_back, edit_connections):
        self.controller = controller
        self.source = 0
        self.auto_scan = False
        self.selected = None
        self.signature = None
        self.root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.root.get_style_context().add_class('quick-wifi')
        header = Gtk.Box(spacing=6)
        self.back = icon_button('chevron-right', 'Назад к быстрым настройкам', go_back, size=44)
        self.back.get_child().set_from_icon_name('go-previous-symbolic', Gtk.IconSize.BUTTON)
        header.pack_start(self.back, False, False, 0)
        header.pack_start(text('Wi-Fi', 'quick-name'), True, True, 0)
        header.pack_end(icon_button('settings', 'Сохранённые и корпоративные сети', edit_connections, size=44), False, False, 0)
        self.scan = icon_button('refresh', 'Обновить список сетей', self.rescan, size=44)
        header.pack_end(self.scan, False, False, 0)
        self.root.pack_start(header, False, False, 0)

        self.search = Gtk.SearchEntry(placeholder_text='Найти сеть')
        self.search.get_accessible().set_name('Найти сеть Wi-Fi')
        self.search.set_no_show_all(True)
        self.search.connect('search-changed', lambda *_: self.update())
        self.root.pack_start(self.search, False, False, 0)
        self.status = text('', 'quick-wifi-status')
        self.status.set_line_wrap(True)
        self.status.set_no_show_all(True)
        self.root.pack_start(self.status, False, False, 0)
        self.enable = Gtk.Button(label='Включить Wi-Fi')
        self.enable.get_style_context().add_class('quick-wifi-primary')
        self.enable.set_size_request(-1, 44)
        self.enable.set_no_show_all(True)
        self.enable.connect('clicked', self.enable_clicked)
        self.root.pack_start(self.enable, False, False, 0)

        self.prompt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.prompt.get_style_context().add_class('quick-wifi-prompt')
        self.prompt.set_no_show_all(True)
        self.prompt_title = text('', 'quick-wifi-name', 30)
        self.prompt.pack_start(self.prompt_title, False, False, 0)
        self.password = Gtk.Entry(placeholder_text='Пароль', visibility=False,
                                  input_purpose=Gtk.InputPurpose.PASSWORD)
        self.password.get_accessible().set_name('Пароль Wi-Fi')
        self.prompt.pack_start(self.password, False, False, 0)
        controls = Gtk.Box(spacing=6)
        cancel = Gtk.Button(label='Отмена')
        cancel.set_size_request(74, 44)
        cancel.connect('clicked', lambda *_: self.clear_prompt())
        controls.pack_start(cancel, False, False, 0)
        self.join = Gtk.Button(label='Подключить')
        self.join.set_size_request(118, 44)
        self.join.get_style_context().add_class('quick-wifi-primary')
        self.join.connect('clicked', lambda *_: self.submit_password())
        controls.pack_end(self.join, False, False, 0)
        self.password.connect('activate', lambda *_: self.submit_password())
        self.password.connect('changed', lambda *_: self.join.set_sensitive(self.can_join()))
        self.prompt.pack_start(controls, False, False, 0)
        for child in self.prompt.get_children():
            child.show_all()
        self.root.pack_start(self.prompt, False, False, 0)

        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.list.show()
        self.scroll = Gtk.ScrolledWindow(propagate_natural_height=True, max_content_height=LIST_HEIGHT)
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_no_show_all(True)
        self.scroll.add(self.list)
        self.root.pack_start(self.scroll, True, True, 0)

    def open(self):
        self.auto_scan = True
        self.controller.start()
        self.update()
        self.source = GLib.timeout_add(400, self.update)

    def close(self):
        self.auto_scan = False
        if self.source:
            GLib.source_remove(self.source)
            self.source = 0
        self.clear_prompt()
        self.search.set_text('')

    def holds_pointer(self):
        return bool(self.selected or self.controller.operation or self.search.has_focus())

    def rescan(self):
        self.controller.scan()
        self.update()

    def enable_clicked(self, _):
        self.controller.enable()
        self.update()

    def update(self):
        if not self.source and not self.auto_scan:
            return GLib.SOURCE_CONTINUE
        controller = self.controller
        state = controller.state()
        online = state == 'on'
        if online and self.auto_scan and not controller.operation:
            self.auto_scan = not (controller.scanning or controller.scan())
        if not online and self.selected:
            self.clear_prompt()
        self.scan.set_sensitive(online and not controller.scanning and not controller.operation and not self.selected)
        self.enable.set_visible(state == 'off')
        self.enable.set_sensitive(not controller.operation)
        self.search.set_visible(online and not self.selected)
        query = self.search.get_text().strip().casefold()
        networks = controller.networks() if online else []
        networks = tuple(net for net in networks if query in net.name.casefold())
        if controller.error:
            self.status.get_style_context().add_class('quick-error')
        else:
            self.status.get_style_context().remove_class('quick-error')
        message = controller.error or controller.operation or {
            'loading': 'Проверяю адаптер…',
            'unavailable': 'Управление Wi-Fi через NetworkManager недоступно.',
            'blocked': 'Wi-Fi заблокирован аппаратно. Проверьте режим полёта.',
            'off': 'Wi-Fi выключен.',
        }.get(state, '')
        if not message and online and not self.selected:
            if controller.scanning:
                message = 'Ищу сети поблизости…'
            elif not networks:
                message = 'Нет совпадений.' if query else 'Сети поблизости не найдены.'
        self.status.set_text(message)
        self.status.set_visible(bool(message))
        signature = (networks, bool(controller.operation))
        if self.signature != signature:
            self.signature = signature
            self.render_networks(*signature)
        self.scroll.set_visible(bool(networks and not self.selected))
        return GLib.SOURCE_CONTINUE

    def render_networks(self, networks, busy):
        focused = next((row.network_path for row in self.list.get_children() if row.has_focus()), None)
        for row in self.list.get_children():
            row.destroy()
        for net in networks:
            row = Gtk.Button()
            row.network_path = net.path
            row.set_size_request(-1, 50)
            row.get_style_context().add_class('quick-wifi-row')
            if net.active:
                row.get_style_context().add_class('quick-wifi-active')
            row.set_sensitive(not busy and not net.active)
            content = Gtk.Box(spacing=10)
            content.pack_start(image('wifi', 20), False, False, 0)
            labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1, valign=Gtk.Align.CENTER)
            labels.pack_start(text(net.name, 'quick-wifi-name', 24), False, False, 0)
            security = {'open': 'Открытая сеть', 'wpa-psk': 'WPA/WPA2', 'sae': 'WPA3',
                        'owe': 'Enhanced Open', 'managed': 'Особые настройки'}[net.security]
            labels.pack_start(text(security + (' · Сохранена' if net.saved else ''), 'quick-wifi-detail'), False, False, 0)
            content.pack_start(labels, True, True, 0)
            if net.active:
                content.pack_end(image('check-circle', 18), False, False, 0)
            else:
                content.pack_end(text(f'{net.strength}%', 'quick-wifi-detail'), False, False, 0)
            row.add(content)
            accessible(row, ('Подключено к ' if net.active else 'Подключиться к ') + net.name,
                       f'{net.name} · {security} · {net.strength}%')
            row.connect('clicked', lambda _, choice=net: self.choose(choice))
            self.list.pack_start(row, False, False, 0)
            row.show_all()
            if focused == net.path and row.get_sensitive():
                row.grab_focus()
        self.scroll.set_min_content_height(min(LIST_HEIGHT, self.list.get_preferred_height()[1]))

    def choose(self, network):
        self.controller.error = ''
        if network.saved or network.security in ('open', 'owe'):
            self.controller.connect(network)
        elif network.security == 'managed':
            self.controller.error = 'Добавьте эту сеть через настройки подключений (шестерёнка).'
        else:
            self.selected = network
            self.prompt_title.set_text(network.name)
            self.join.set_sensitive(False)
            self.prompt.show()
            self.password.grab_focus()
        self.update()

    def can_join(self):
        return bool(self.selected and valid_password(self.selected.security, self.password.get_text()))

    def submit_password(self):
        if self.can_join():
            self.controller.connect(self.selected, self.password.get_text())
            self.clear_prompt()

    def clear_prompt(self):
        self.selected = None
        self.password.set_text('')
        self.prompt.hide()
        if self.source:
            self.update()
