"""Read-only collectors for g8d panels; missing sensors are reported explicitly."""
import json
import os
from pathlib import Path
import pwd
import re
import socket
import subprocess
import time

import gi
gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib
import psutil
import brightness


def run(args, timeout=2):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                                env={**os.environ, 'LC_ALL': 'C'})
        return result.stdout.strip() if result.returncode == 0 else ''
    except (OSError, subprocess.SubprocessError):
        return ''


def unpack(value):
    if isinstance(value, GLib.Variant): return unpack(value.unpack())
    if isinstance(value, dict): return {k: unpack(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [unpack(v) for v in value]
    return value


def call(bus, name, path, interface, method, parameters=None, timeout=700):
    return unpack(bus.call_sync(name, path, interface, method, parameters, None,
                               Gio.DBusCallFlags.NONE, timeout, None))


def profile():
    user = pwd.getpwuid(os.getuid())
    name, avatar = user.pw_gecos.split(',')[0] or user.pw_name, ''
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        path = call(bus, 'org.freedesktop.Accounts', '/org/freedesktop/Accounts',
                    'org.freedesktop.Accounts', 'FindUserById', GLib.Variant('(x)', (os.getuid(),)))[0]
        properties = call(bus, 'org.freedesktop.Accounts', path, 'org.freedesktop.DBus.Properties',
                          'GetAll', GLib.Variant('(s)', ('org.freedesktop.Accounts.User',)))[0]
        name = properties.get('RealName') or name
        avatar = properties.get('IconFile', '')
    except GLib.Error:
        pass
    for candidate in [avatar, str(Path.home() / '.face'), str(Path.home() / '.face.icon')]:
        if candidate and Path(candidate).is_file():
            avatar = candidate
            break
    else:
        avatar = ''
    try:
        release = dict(line.strip().split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
        distro = release.get('PRETTY_NAME', 'Linux').strip('"')
    except OSError:
        distro = 'Linux'
    return {'name': name, 'user': user.pw_name, 'host': socket.gethostname(),
            'avatar': avatar, 'os': distro}


def media():
    players = []
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        names = call(bus, 'org.freedesktop.DBus', '/org/freedesktop/DBus',
                     'org.freedesktop.DBus', 'ListNames')[0]
        for name in names:
            if not name.startswith('org.mpris.MediaPlayer2.'): continue
            try:
                properties = call(bus, name, '/org/mpris/MediaPlayer2', 'org.freedesktop.DBus.Properties',
                                  'GetAll', GLib.Variant('(s)', ('org.mpris.MediaPlayer2.Player',)))[0]
                metadata = properties.get('Metadata', {})
                try:
                    application = call(bus, name, '/org/mpris/MediaPlayer2', 'org.freedesktop.DBus.Properties',
                                       'GetAll', GLib.Variant('(s)', ('org.mpris.MediaPlayer2',)))[0]
                except GLib.Error:
                    application = {}
                identity = application.get('Identity') or name.removeprefix('org.mpris.MediaPlayer2.')
                app_id = re.sub(r'[^a-zа-я0-9]', '',
                                (identity + application.get('DesktopEntry', '')).lower())
                is_yandex = 'yandexmusic' in app_id or 'яндексмузыка' in app_id
                art = metadata.get('mpris:artUrl', '')
                if name == 'org.mpris.MediaPlayer2.yamusic-cli' and art.startswith('https://'):
                    from yamusic_backend import cover_file
                    art = cover_file(art)
                players.append({'bus': name, 'player': 'Яндекс Музыка' if is_yandex else identity,
                                'yandex': is_yandex,
                                'status': properties.get('PlaybackStatus', 'Stopped'),
                                'title': metadata.get('xesam:title') or 'Без названия',
                                'artist': ', '.join(metadata.get('xesam:artist', [])),
                                'album': metadata.get('xesam:album', ''),
                                'art': art,
                                'length': metadata.get('mpris:length', 0),
                                'position': properties.get('Position', 0),
                                'seek': properties.get('CanSeek', False),
                                'control': properties.get('CanControl', False),
                                'previous': properties.get('CanGoPrevious', False),
                                'next': properties.get('CanGoNext', False),
                                'play': properties.get('CanPlay', False),
                                'pause': properties.get('CanPause', False)})
            except GLib.Error:
                continue
    except GLib.Error:
        pass
    players.sort(key=lambda p: (0 if p['bus'] == 'org.mpris.MediaPlayer2.yamusic-cli' else 1, {'Playing': 0, 'Paused': 1, 'Stopped': 2}.get(p['status'], 3), p['player']))
    return players


def media_control(name, method):
    commands = {'PlayPause': ['play-pause'], 'Play': ['play'], 'Pause': ['pause'],
                'Next': ['next'], 'Previous': ['previous'],
                'SeekBack': ['position', '10-'], 'SeekForward': ['position', '10+']}
    if method not in commands or not name.startswith('org.mpris.MediaPlayer2.'):
        raise ValueError('Неизвестная команда плеера')
    if name == 'org.mpris.MediaPlayer2.yamusic-cli':
        from yamusic_backend import command
        native = {'PlayPause': ['toggle'], 'Play': ['play'], 'Pause': ['pause'],
                  'Next': ['next'], 'Previous': ['prev'],
                  'SeekBack': ['seek', '--', '-10'], 'SeekForward': ['seek', '+10']}
        command(*native[method])
        return
    # Target this exact instance: a browser/video player must not steal a click.
    result = subprocess.run(['playerctl', '--player=' + name.removeprefix('org.mpris.MediaPlayer2.'),
                             *commands[method]], capture_output=True, text=True, timeout=3)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'Плеер недоступен')


def radio():
    wifi = run(['nmcli', '-t', '-f', 'WIFI', 'general'])
    devices = run(['nmcli', '-t', '-f', 'DEVICE,TYPE,STATE,CONNECTION', 'device'])
    connections = []
    for line in devices.splitlines():
        fields = re.split(r'(?<!\\):', line)
        if len(fields) >= 4 and fields[1] == 'wifi':
            connections.append({'interface': fields[0], 'state': fields[2],
                                'connection': ':'.join(fields[3:]).replace('\\:', ':')})
    bluetooth = run(['bluetoothctl', 'show'])
    connected = run(['bluetoothctl', 'devices', 'Connected']) if bluetooth else ''
    return {'wifi': wifi or 'unavailable', 'connections': connections,
            'bluetooth': ('on' if 'Powered: yes' in bluetooth else 'off') if bluetooth else 'unavailable',
            'bluetooth_devices': [' '.join(line.split()[2:]) for line in connected.splitlines() if line.startswith('Device ')]}


def gpu():
    rows = run(['nvidia-smi', '--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw',
                '--format=csv,noheader,nounits'])
    result = []
    for row in rows.splitlines():
        columns = [v.strip() for v in row.split(',')]
        if len(columns) != 6: continue
        def number(value):
            try: return float(value)
            except ValueError: return None
        name, load, used, total, temp, watts = columns
        result.append({'name': name, 'load': number(load), 'used': number(used),
                       'total': number(total), 'temp': number(temp), 'watts': number(watts)})
    # AMD/Intel sensors may expose a utilization counter; never replace absent data with 0%.
    for card in sorted(Path('/sys/class/drm').glob('card[0-9]*')):
        if '-' in card.name: continue
        device = card / 'device'
        try:
            vendor = (device / 'vendor').read_text().strip()
            if vendor == '0x10de': continue
            driver = (device / 'driver').resolve().name
            def sensor(name):
                try: return float((device / name).read_text().strip())
                except (OSError, ValueError): return None
            used, total = sensor('mem_info_vram_used'), sensor('mem_info_vram_total')
            result.append({'name': f'{card.name} · {driver}', 'load': sensor('gpu_busy_percent'),
                           'used': used / 1048576 if used is not None else None,
                           'total': total / 1048576 if total is not None else None,
                           'temp': None, 'watts': None})
        except OSError:
            pass
    return result


class Collector:
    def __init__(self):
        self.user = profile()
        self.processes = {}
        psutil.cpu_percent()

    def collect(self, kind):
        if kind == 'profile':
            ram = psutil.virtual_memory()
            return {**self.user, **radio(), 'uptime': int(time.time() - psutil.boot_time()),
                    'ram_used': (ram.total - ram.available) / 1073741824, 'brightness': brightness.read()}
        cpu = psutil.cpu_percent(interval=0.15)
        ram = psutil.virtual_memory()
        swap = psutil.swap_memory()
        processes, current = [], {}
        for process in psutil.process_iter(['pid', 'name', 'memory_info']):
            try:
                info = process.info
                if not info['memory_info']: continue
                key = (process.pid, process.create_time())
                handle = self.processes.get(key, process)
                load = handle.cpu_percent()
                current[key] = handle
                processes.append({'pid': process.pid, 'name': info['name'] or str(process.pid),
                                  'cpu': load, 'ram': info['memory_info'].rss / 1048576})
            except (psutil.Error, OSError):
                continue
        self.processes = current
        stats = psutil.net_if_stats()
        interfaces = []
        for name, addresses in psutil.net_if_addrs().items():
            ips = [a.address for a in addresses if a.family in (socket.AF_INET, socket.AF_INET6)]
            if ips:
                interfaces.append({'name': name, 'up': bool(stats.get(name) and stats[name].isup), 'ips': ips})
        return {'cpu': cpu, 'ram_used': (ram.total - ram.available) / 1073741824,
                'ram_total': ram.total / 1073741824, 'ram_percent': ram.percent,
                'swap_used': swap.used / 1073741824, 'swap_total': swap.total / 1073741824,
                'gpu': gpu(), 'interfaces': interfaces, 'media': media(),
                'processes_cpu': sorted(processes, key=lambda p: p['cpu'], reverse=True)[:3],
                'processes_ram': sorted(processes, key=lambda p: p['ram'], reverse=True)[:3]}


if __name__ == '__main__':
    import sys
    print(json.dumps(Collector().collect(sys.argv[1] if len(sys.argv) > 1 else 'dashboard'), ensure_ascii=False, indent=2))
