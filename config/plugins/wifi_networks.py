"""NetworkManager-backed Wi-Fi discovery and activation for quick settings."""
from dataclasses import dataclass

import gi
from gi.repository import GLib

try:
    gi.require_version('NM', '1.0')
    from gi.repository import NM
except (ImportError, ValueError):
    NM = None


@dataclass(frozen=True)
class Network:
    path: str
    name: str
    security: str
    strength: int
    active: bool
    saved: bool


def network_rank(network):
    return network.active, network.saved, network.strength


def security_type(ap):
    flags = ap.get_rsn_flags() | ap.get_wpa_flags()
    security = getattr(NM, '80211ApSecurityFlags')
    if flags & security.KEY_MGMT_PSK:
        return 'wpa-psk'
    if flags & security.KEY_MGMT_SAE:
        return 'sae'
    if flags & security.KEY_MGMT_OWE:
        return 'owe'
    if ap.get_flags() & getattr(NM, '80211ApFlags').PRIVACY or flags:
        return 'managed'
    return 'open'


def valid_password(security, password):
    size = len(password.encode('utf-8'))
    if security == 'sae':
        return 1 <= size <= 63
    return 8 <= size <= 63 or (size == 64 and all(c in '0123456789abcdefABCDEF' for c in password))


class Wifi:
    def __init__(self):
        self.client = None
        self.loading = False
        self.scanning = False
        self.operation = ''
        self.error = ''
        self.targets = {}

    def start(self):
        self.error = ''
        if NM is not None and not self.client and not self.loading:
            self.loading = True
            NM.Client.new_async(None, self.ready)

    def ready(self, _, result):
        self.loading = False
        try:
            self.client = NM.Client.new_finish(result)
        except GLib.Error:
            self.error = 'Не удалось связаться с NetworkManager.'

    def devices(self):
        return [device for device in self.client.get_devices()
                if isinstance(device, NM.DeviceWifi) and device.get_managed()]

    def state(self):
        if self.loading:
            return 'loading'
        if not self.client or not self.client.get_nm_running() or not self.devices():
            return 'unavailable'
        if not self.client.wireless_hardware_get_enabled():
            return 'blocked'
        return 'on' if self.client.wireless_get_enabled() else 'off'

    def networks(self):
        self.targets = {}
        strongest = {}
        connections = self.client.get_connections()
        for device in self.devices():
            active = device.get_active_access_point() if device.get_state() == NM.DeviceState.ACTIVATED else None
            available = [connection for connection in connections if device.connection_valid(connection)]
            for ap in device.get_access_points():
                ssid = ap.get_ssid()
                if not ssid or not ssid.get_size():
                    continue
                key = (bytes(ssid.get_data()), security_type(ap))
                saved = next((connection for connection in available if ap.connection_valid(connection)), None)
                path = ap.get_path()
                network = Network(path, (NM.utils_ssid_to_utf8(key[0]) or 'Неизвестная сеть').replace('\n', ' '),
                                  key[1], ap.get_strength(), bool(active and active.get_path() == path), bool(saved))
                current = strongest.get(key)
                if current is None or network_rank(network) > network_rank(current):
                    strongest[key] = network
                    self.targets[path] = (device, ap, saved)
        return sorted(strongest.values(), key=lambda net: (not net.active, not net.saved, -net.strength, net.name.casefold()))

    def enable(self):
        if self.state() != 'off' or self.operation:
            return
        self.error = ''
        self.operation = 'Включаю Wi-Fi…'
        self.client.dbus_set_property('/org/freedesktop/NetworkManager', 'org.freedesktop.NetworkManager',
                                      'WirelessEnabled', GLib.Variant('b', True), 5000, None, self.enabled)

    def enabled(self, client, result):
        self.operation = ''
        try:
            client.dbus_set_property_finish(result)
        except GLib.Error:
            self.error = 'Не удалось включить Wi-Fi. Проверьте разрешения NetworkManager.'

    def scan(self):
        if self.state() != 'on' or self.scanning or self.operation:
            return False
        scans = {device: device.get_last_scan() for device in self.devices()
                 if device.get_state() >= NM.DeviceState.DISCONNECTED}
        if not scans:
            return False
        self.error = ''
        self.scanning = True
        remaining = set(scans)
        accepted = set()

        def finished(device, result):
            remaining.discard(device)
            try:
                device.request_scan_finish(result)
                accepted.add(device)
            except GLib.Error:
                pass

        def update():
            if not remaining and not accepted:
                if not self.networks():
                    self.error = 'Не удалось начать поиск. Попробуйте ещё раз через несколько секунд.'
            elif remaining or any(device.get_last_scan() == scans[device] for device in accepted):
                return GLib.SOURCE_CONTINUE
            self.scanning = False
            GLib.source_remove(timeout)
            return GLib.SOURCE_REMOVE

        def expired():
            GLib.source_remove(poll)
            self.scanning = False
            if not self.error and not self.networks():
                self.error = 'Поиск не завершился. Попробуйте ещё раз.'
            return GLib.SOURCE_REMOVE

        poll = GLib.timeout_add(300, update)
        timeout = GLib.timeout_add_seconds(12, expired)
        for device in scans:
            device.request_scan_async(None, finished)
        return True

    def connect(self, network, password=None):
        if self.operation:
            return
        target = self.targets.get(network.path)
        if target is None:
            self.error = 'Эта сеть больше не видна. Повторите поиск.'
            return
        device, ap, saved = target
        self.error = ''
        self.operation = 'Подключаюсь…'

        def started(client, result):
            try:
                if saved:
                    active = client.activate_connection_finish(result)
                else:
                    active, _ = client.add_and_activate_connection2_finish(result)
            except GLib.Error:
                self.operation = ''
                self.error = 'Не удалось начать подключение. Проверьте настройки сети.'
                return
            self.watch_activation(active, not saved)

        if saved:
            self.client.activate_connection_async(saved, device, ap.get_path(), None, started)
        else:
            options = GLib.Variant('a{sv}', {'persist': GLib.Variant('s', 'volatile')})
            self.client.add_and_activate_connection2(connection_settings(network.security, password), device,
                                                     ap.get_path(), options, None, started)

    def watch_activation(self, active, save):
        def state_changed(*_):
            state = active.get_state()
            if state == NM.ActiveConnectionState.ACTIVATED:
                cleanup()
                if save and active.get_connection():
                    active.get_connection().save_async(None, self.saved)
            elif state == NM.ActiveConnectionState.DEACTIVATED:
                cleanup()
                self.error = 'Не удалось подключиться. Проверьте пароль или выберите другую сеть.'

        def cleanup():
            active.disconnect(handler)
            GLib.source_remove(timeout)
            self.operation = ''

        def expired():
            active.disconnect(handler)
            self.operation = ''
            self.error = 'Подключение занимает слишком много времени.'
            return GLib.SOURCE_REMOVE

        handler = active.connect('notify::state', state_changed)
        timeout = GLib.timeout_add_seconds(45, expired)
        state_changed()

    def saved(self, connection, result):
        try:
            connection.save_finish(result)
        except GLib.Error:
            self.error = 'Wi-Fi подключён, но сохранить профиль не удалось.'


def connection_settings(security, password):
    if security == 'open':
        return None
    setting = NM.SettingWirelessSecurity.new()
    setting.set_property('key-mgmt', security)
    if password is not None:
        setting.set_property('psk', password)
    partial = NM.SimpleConnection.new()
    partial.add_setting(setting)
    return partial
