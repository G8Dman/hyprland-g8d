"""The Bluetooth page inside the quick settings surface."""
from gi.repository import Gtk

from bluetooth_battery import format_charge
from quick_settings import accessible, icon_button, image, text


GROUPS = ('Подключены', 'Сохранённые устройства', 'Найденные устройства')
LIST_HEIGHT = 296
ICONS = {'audio-headphones': 'volume-up', 'audio-headset': 'volume-up',
         'audio-handsfree': 'volume-up', 'audio-card': 'volume-up',
         'input-keyboard': 'keyboard', 'computer': 'desktop-windows'}
HEADSETS = {'audio-headphones', 'audio-headset', 'audio-handsfree'}
ERRORS = {
    'AuthenticationCanceled': 'Сопряжение отменено.',
    'AuthenticationRejected': 'Подтверждение отклонено.',
    'AuthenticationFailed': 'Проверьте код и повторите сопряжение.',
    'AuthenticationTimeout': 'Включите режим сопряжения и попробуйте ещё раз.',
    'ConnectionAttemptFailed': 'Поднесите устройство ближе и убедитесь, что оно доступно.',
    'NotReady': 'Убедитесь, что Bluetooth включён.',
    'NotAuthorized': 'Система не разрешила эту операцию.',
}


def widget_name(device):
    return device.get('Alias') or device.get('Name') or device.get('Address') or 'Устройство Bluetooth'


def group_index(device):
    return 0 if device.get('Connected') else 1 if device.get('Paired') else 2


class BluetoothPanel:
    def __init__(self, controller, go_back):
        self.controller = controller
        self.root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.root.get_style_context().add_class('quick-bluetooth')
        self.device_rows = {}
        self.row_signature = None

        header = Gtk.Box(spacing=4)
        self.back = icon_button('chevron-right', 'Назад к быстрым настройкам', go_back, size=44)
        self.back.get_child().set_from_icon_name('go-previous-symbolic', Gtk.IconSize.BUTTON)
        header.pack_start(self.back, False, False, 0)
        title = text('Bluetooth', 'quick-name')
        header.pack_start(title, True, True, 0)
        self.scan = Gtk.Button(label='Поиск')
        self.scan.set_size_request(92, 44)
        self.scan.get_style_context().add_class('quick-bt-primary')
        self.scan.connect('clicked', self.scan_clicked)
        header.pack_end(self.scan, False, False, 0)
        self.root.pack_start(header, False, False, 0)

        self.status = text('', 'quick-bt-status')
        self.status.set_line_wrap(True)
        self.root.pack_start(self.status, False, False, 0)
        self.notice = text('', 'quick-bt-error')
        self.notice.set_line_wrap(True)
        self.notice.set_no_show_all(True)
        self.root.pack_start(self.notice, False, False, 0)

        self.confirmation = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.confirmation.get_style_context().add_class('quick-bt-confirm')
        self.confirmation.set_no_show_all(True)
        self.root.pack_start(self.confirmation, False, False, 0)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_max_content_height(LIST_HEIGHT)
        self.scroll.set_propagate_natural_height(True)
        self.scroll.set_no_show_all(True)
        self.scroll.add(self.list)
        self.root.pack_start(self.scroll, True, True, 0)

    def open(self):
        self.notice.hide()
        self.controller.open(self)

    def close(self):
        self.controller.close(self)

    def scan_clicked(self, _):
        self.notice.hide()
        if self.power == 'off':
            self.controller.power_on()
        else:
            self.controller.toggle_scan()

    def update(self, power, devices, scanning, scan_pending, operation):
        self.power = power
        off = power == 'off'
        self.scan.set_label('Включить' if off else 'Стоп' if scanning else 'Поиск')
        accessible(self.scan, 'Включить Bluetooth' if off else 'Остановить поиск' if scanning else 'Поиск устройств Bluetooth')
        self.scan.set_sensitive((power == 'on' and not scan_pending) or (off and not operation))
        if power == 'loading':
            message = 'Проверяю адаптер…'
        elif power == 'unavailable':
            message = 'Bluetooth-адаптер недоступен.'
        elif off:
            message = 'Bluetooth выключен.'
        elif scanning:
            message = 'Ищу устройства поблизости…'
        elif not any(group_index(device) == 2 for device in devices):
            message = 'Включите режим сопряжения на устройстве и нажмите «Поиск».'
        else:
            message = ''
        self.status.set_text(message)
        self.status.set_no_show_all(not message)
        self.status.set_visible(bool(message))
        devices = devices if power == 'on' else []
        devices.sort(key=lambda device: (group_index(device), device.get('Icon') not in HEADSETS,
                                         widget_name(device).casefold(), device['path']))
        signature = tuple((device['path'], group_index(device), widget_name(device), device.get('Icon'), operation,
                           format_charge(device.get('battery', {}), full=True))
                          for device in devices)
        if signature != self.row_signature:
            self.row_signature = signature
            self.render_devices(devices, operation)

    def render_devices(self, devices, operation):
        focused = next((path for path, row in self.device_rows.items() if row.has_focus()), None)
        self.device_rows.clear()
        for child in self.list.get_children():
            child.destroy()
        group = None
        for device in devices:
            index = group_index(device)
            if index != group:
                self.list.pack_start(text(GROUPS[index], 'quick-bt-group'), False, False, 0)
                group = index
            path = device['path']
            name = widget_name(device)
            action = ('Отключить', 'Подключить', 'Сопрячь')[index]
            description = ('Подключено', 'Сопряжено', 'Рядом')[index]
            charge = format_charge(device.get('battery', {}), full=True)
            button = Gtk.Button()
            button.set_size_request(-1, 48)
            button.get_style_context().add_class('quick-bt-device')
            tooltip = name + ' · ' + description
            accessible(button, action + ' · ' + name, tooltip + ('\n' + charge if charge else ''))
            if charge:
                button.get_accessible().set_description(charge)
            button.set_sensitive(not operation)
            row = Gtk.Box(spacing=8)
            row.pack_start(image(ICONS.get(device.get('Icon'), 'bluetooth'), 18), False, False, 0)
            labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.CENTER)
            labels.pack_start(text(name, 'quick-bt-name', 18), False, False, 0)
            if charge:
                labels.pack_start(text(charge, 'quick-bt-battery', 27), False, False, 0)
            row.pack_start(labels, True, True, 0)
            status = text('Подождите…' if operation == path else action, 'quick-bt-action')
            row.pack_end(status, False, False, 0)
            button.add(row)
            button.connect('clicked', self.device_clicked, device)
            self.list.pack_start(button, False, False, 0)
            self.device_rows[path] = button
        self.list.show_all()
        self.scroll.set_min_content_height(min(LIST_HEIGHT, self.list.get_preferred_height()[1]))
        self.scroll.set_visible(bool(devices))
        if focused in self.device_rows and not operation:
            self.device_rows[focused].grab_focus()

    def device_clicked(self, _, device):
        self.notice.hide()
        self.controller.activate(device)

    def error(self, title, code):
        detail = ERRORS.get(code.rsplit('.', 1)[-1], 'Проверьте устройство и повторите попытку.')
        self.notice.set_text(f'{title}. {detail}')
        self.notice.set_tooltip_text(code)
        self.notice.show()

    def clear_prompt(self):
        for child in self.confirmation.get_children():
            child.destroy()
        self.confirmation.hide()

    def ask(self, method, args, reply):
        self.clear_prompt()
        code = f'{args[0]:06d}' if args and isinstance(args[0], int) else args[0] if args else ''
        instructions = {
            'RequestPinCode': 'Введите PIN с другого устройства.',
            'RequestPasskey': 'Введите код с другого устройства.',
            'RequestConfirmation': f'Совпадает ли код {code} на обоих устройствах?',
            'DisplayPasskey': f'Наберите {code} на устройстве и нажмите Enter.',
            'DisplayPinCode': f'Наберите {code} на устройстве и нажмите Enter.',
            'AuthorizeService': 'Разрешить запрошенное подключение?',
            'RequestAuthorization': 'Подтвердить сопряжение с устройством?',
        }
        label = text(instructions[method], 'quick-bt-name')
        label.set_line_wrap(True)
        self.confirmation.pack_start(label, False, False, 0)
        controls = Gtk.Box(spacing=8)
        self.confirmation.pack_start(controls, False, False, 0)
        cancel = Gtk.Button(label='Отмена')
        cancel.set_size_request(80, 44)
        controls.pack_start(cancel, False, False, 0)
        cancel.connect('clicked', lambda *_: reply(False, '') if reply else self.controller.cancel_pairing())
        if reply:
            confirm = Gtk.Button(label='Подтвердить')
            confirm.set_size_request(120, 44)
            confirm.get_style_context().add_class('quick-bt-primary')
            controls.pack_end(confirm, False, False, 0)
            entry = None
            if method in ('RequestPinCode', 'RequestPasskey'):
                entry = Gtk.Entry()
                numeric = method == 'RequestPasskey'
                entry.set_max_length(6 if numeric else 16)
                entry.set_placeholder_text('Код' if numeric else 'PIN')
                entry.get_accessible().set_name(entry.get_placeholder_text())
                self.confirmation.pack_start(entry, False, False, 0)
                self.confirmation.reorder_child(entry, 1)
                confirm.set_sensitive(False)
                entry.connect('changed', lambda field: confirm.set_sensitive(
                    bool(field.get_text()) and (not numeric or (field.get_text().isascii() and field.get_text().isdigit()))))
                entry.connect('activate', lambda *_: confirm.clicked() if confirm.get_sensitive() else None)
            confirm.connect('clicked', lambda *_: reply(True, entry.get_text() if entry else ''))
        else:
            entry = None
        for child in self.confirmation.get_children():
            child.show_all()
        self.confirmation.show()
        (entry or cancel).grab_focus()
