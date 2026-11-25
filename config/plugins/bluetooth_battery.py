"""Battery levels exposed by BlueZ, UPower, or a connected Nothing headset."""
import math
import re
import socket
import struct
import threading
import time


BLUEZ = 'org.bluez'
BATTERY = BLUEZ + '.Battery1'
DEVICE = BLUEZ + '.Device1'
NOTHING_UUID = 'aeac4a03-dff5-498f-843a-34487cf133eb'
NOTHING_CHANNELS = {
    'nothing ear': 15, 'nothing ear (1)': 15, 'nothing ear (2)': 15,
    'nothing ear (a)': 15, 'nothing ear (stick)': 15, 'nothing ear (3)': 15,
    'nothing headphone (1)': 15, 'cmf buds 2': 16, 'cmf headphone pro': 28,
}
COMPONENTS = {2: 'left', 3: 'right', 4: 'case', 6: 'total'}
ADDRESS = re.compile(r'[0-9A-F]{2}(?::[0-9A-F]{2}){5}')
FRAME = struct.Struct('<BHHHB')
_detail_lock = threading.Lock()
_details = {}


def address(value):
    if not isinstance(value, str):
        return None
    value = value.replace('_', ':').upper()
    return value if ADDRESS.fullmatch(value) else None


def percentage(value):
    if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 100:
        return round(value)
    return None


def format_charge(levels, *, full=False):
    labels = (('left', 'Левый' if full else 'Л'), ('right', 'Правый' if full else 'П'))
    parts = [f'{label} {levels[key]}%' for key, label in labels if key in levels]
    if not parts and 'total' in levels:
        parts.append(f"{'Заряд ' if full else ''}{levels['total']}%")
    if (full or not parts) and 'case' in levels:
        parts.append(f"Кейс {levels['case']}%")
    return ' · '.join(parts)


def crc16(data):
    result = 0xFFFF
    for byte in data:
        result ^= byte
        for _ in range(8):
            result = (result >> 1) ^ (0xA001 if result & 1 else 0)
    return result


def request(command, sequence):
    packet = FRAME.pack(0x55, 0x0160, command, 0, sequence)
    return packet + struct.pack('<H', crc16(packet))


def parse_levels(body):
    if not body or len(body) != 1 + body[0] * 2:
        return {}
    result = {}
    for identifier, value in zip(body[1::2], body[2::2]):
        percent = percentage(value & 0x7F)
        if identifier in COMPONENTS and percent is not None:
            result[COMPONENTS[identifier]] = percent
    return result


def packets(buffer):
    while len(buffer) >= FRAME.size:
        start = buffer.find(b'\x55')
        if start < 0:
            buffer.clear()
            return
        del buffer[:start]
        if len(buffer) < FRAME.size:
            return
        _, flags, command, size, sequence = FRAME.unpack_from(buffer)
        if size > 2048:
            del buffer[0]
            continue
        end = FRAME.size + size
        crc = bool(flags & 0x20)
        length = end + (2 if crc else 0)
        if len(buffer) < length:
            return
        packet = bytes(buffer[:length])
        del buffer[:length]
        if not crc or crc16(packet[:end]) == int.from_bytes(packet[end:], 'little'):
            yield command, sequence, packet[FRAME.size:end]


def nothing_battery(mac, channel):
    # NT Link read commands only. The first requests device info to open the telemetry session.
    # Protocol: https://github.com/ncr/omarchy-headphones/blob/main/PROTOCOL.md#nothing-nt-link--the-nothing-x-protocol-on-rfcomm-channel-15-or-28
    with socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM) as connection:
        connection.settimeout(1.2)
        connection.connect((mac, channel))
        buffer = bytearray()
        for sequence, command in enumerate((0xC006, 0xC007), 1):
            connection.sendall(request(command, sequence))
            deadline = time.monotonic() + 1
            received = False
            while not received and (remaining := deadline - time.monotonic()) > 0:
                connection.settimeout(remaining)
                try:
                    chunk = connection.recv(4096)
                except TimeoutError:
                    break
                if not chunk:
                    return {}
                buffer.extend(chunk)
                for reply, _, body in packets(buffer):
                    if command == 0xC007 and reply in (0x4007, 0xE001):
                        levels = parse_levels(body)
                        if levels:
                            return levels
                    if reply == (command & 0x7FFF):
                        received = True
        return {}


def cached_nothing(mac, profile):
    if not _detail_lock.acquire(blocking=False):
        return {}
    try:
        now = time.monotonic()
        for old in tuple(_details):
            if _details[old][0] < now:
                del _details[old]
        if mac in _details:
            return _details[mac][1]
        try:
            levels = nothing_battery(mac, profile)
        except (OSError, AttributeError):
            levels = {}
        _details[mac] = (now + 40, levels)
        return levels
    finally:
        _detail_lock.release()


def read_batteries(addresses):
    from gi.repository import Gio, GLib

    def get(name, path, interface, method, args=None):
        return bus.call_sync(name, path, interface, method, args, None,
                             Gio.DBusCallFlags.NO_AUTO_START, 800, None).unpack()[0]

    wanted = set(addresses)
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)
        objects = get(BLUEZ, '/', 'org.freedesktop.DBus.ObjectManager', 'GetManagedObjects')
    except GLib.Error:
        return {}
    result, detail_devices = {}, {}
    for interfaces in objects.values():
        device = interfaces.get(DEVICE, {})
        mac = address(device.get('Address'))
        if mac not in wanted or not device.get('Connected'):
            continue
        value = percentage(interfaces.get(BATTERY, {}).get('Percentage'))
        result[mac] = {} if value is None else {'total': value}
        name = (device.get('Name') or device.get('Alias') or '').casefold().strip()
        if name in NOTHING_CHANNELS and NOTHING_UUID in device.get('UUIDs', ()):
            detail_devices[mac] = NOTHING_CHANNELS[name]
    if any(not levels for levels in result.values()):
        service = 'org.freedesktop.UPower'
        interface = service + '.Device'
        try:
            devices = get(service, '/org/freedesktop/UPower', service, 'EnumerateDevices')
            for path in devices:
                fields = get(service, path, 'org.freedesktop.DBus.Properties', 'GetAll',
                             GLib.Variant('(s)', (interface,)))
                mac = address(fields.get('Serial')) or address(fields.get('NativePath', '').rsplit('dev_', 1)[-1])
                value = percentage(fields.get('Percentage'))
                if mac in result and not result[mac] and fields.get('IsPresent', True) and value is not None:
                    result[mac] = {'total': value}
        except GLib.Error:
            pass
    for mac, channel in detail_devices.items():
        result[mac].update(cached_nothing(mac, channel))
    return result


class BatteryMonitor:
    """Poll only while a visible menu has connected devices to show."""
    def __init__(self, pool, changed):
        from gi.repository import GLib
        self.glib, self.pool, self.changed = GLib, pool, changed
        self.addresses = ()
        self.values = {}
        self.timer = 0
        self.pending = False

    def watch(self, addresses=()):
        addresses = tuple(sorted({item for raw in addresses if (item := address(raw))}))
        if addresses == self.addresses:
            return
        self.addresses = addresses
        self.values = {key: value for key, value in self.values.items() if key in addresses}
        if not addresses and self.timer:
            self.glib.source_remove(self.timer)
            self.timer = 0
        elif addresses:
            if not self.timer:
                self.timer = self.glib.timeout_add_seconds(20, self.refresh)
            self.refresh()

    def refresh(self):
        if self.addresses and not self.pending:
            requested = self.addresses
            self.pending = True
            future = self.pool.submit(read_batteries, requested)
            future.add_done_callback(lambda done: self.glib.idle_add(self.finished, requested, done))
        return self.glib.SOURCE_CONTINUE

    def finished(self, requested, future):
        self.pending = False
        if requested != self.addresses:
            self.refresh()
        elif not future.cancelled():
            self.values = future.result()
            self.changed()
        return self.glib.SOURCE_REMOVE
