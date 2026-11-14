"""Map every connected monitor to its actual backlight or DDC brightness control."""
import json
from pathlib import Path
import re
import subprocess
import threading
import time

CACHE = {}
LOCK = threading.Lock()


def command(arguments):
    process = subprocess.run(arguments, text=True, capture_output=True, timeout=8)
    if process.returncode:
        raise RuntimeError(process.stderr.strip() or process.stdout.strip() or 'Нет ответа от монитора')
    return process.stdout.strip()


def device(output):
    for path in Path('/sys/class/backlight').glob('*'):
        if f'-{output}/' in str(path.resolve()) + '/':
            return {'backend': 'backlight', 'device': path.name}
    for path in Path('/sys/class/drm').glob(f'card*-{output}/ddc'):
        match = re.fullmatch(r'i2c-(\d+)', path.resolve().name)
        if match: return {'backend': 'ddc', 'bus': int(match[1])}
    raise RuntimeError('Управление подсветкой не найдено')


def read_device(info):
    if info['backend'] == 'backlight':
        path = Path('/sys/class/backlight') / info['device']
        current = int((path / 'brightness').read_text())
        maximum = int((path / 'max_brightness').read_text())
    else:
        text = command(['ddcutil', '--bus', str(info['bus']), 'getvcp', '10', '--terse'])
        match = re.search(r'VCP\s+10\s+C\s+(\d+)\s+(\d+)', text)
        if not match: raise RuntimeError('Яркость DDC/CI недоступна')
        current, maximum = map(int, match.groups())
    if maximum <= 0: raise RuntimeError('Монитор сообщил некорректный диапазон яркости')
    return {**info, 'current': current, 'maximum': maximum, 'percent': round(100 * current / maximum), 'enabled': True}


def read():
    monitors = json.loads(command(['hyprctl', '-j', 'monitors']))
    result = []
    for monitor in sorted(monitors, key=lambda m: m['x']):
        output = monitor['name']
        title = monitor.get('description') or output
        with LOCK: cached = CACHE.get(output)
        if cached and time.monotonic() - cached[0] < 5:
            value = dict(cached[1])
        else:
            try: value = read_device(device(output))
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                value = {'enabled': False, 'percent': 100, 'error': str(exc)}
            with LOCK: CACHE[output] = (time.monotonic(), value)
        result.append({**value, 'output': output, 'title': title})
    return result


def set_value(output, percent):
    percent = max(1, min(100, round(percent)))
    info = device(output)
    if info['backend'] == 'backlight':
        command(['brightnessctl', '--device', info['device'], '--quiet', 'set', f'{percent}%'])
    else:
        with LOCK: cached = CACHE.get(output)
        value = cached[1] if cached and cached[1].get('enabled') else read_device(info)
        native = round(percent * value['maximum'] / 100)
        command(['ddcutil', '--bus', str(info['bus']), 'setvcp', '10', str(native)])
    actual = read_device(info)
    with LOCK: CACHE[output] = (time.monotonic(), actual)
    return actual['percent']


class Writer:
    """Coalesce fast slider updates; allow at most one hardware operation at a time."""
    def __init__(self, callback):
        self.callback = callback
        self.pending = {}
        self.condition = threading.Condition()
        self.stopped = False
        self.thread = threading.Thread(target=self.work, name='g8d-brightness', daemon=True)
        self.thread.start()

    def request(self, output, percent):
        with self.condition:
            self.pending[output] = percent
            self.condition.notify()

    def work(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.pending or self.stopped)
                if self.stopped: return
                output = next(iter(self.pending))
                percent = self.pending.pop(output)
            try:
                actual, error = set_value(output, percent), None
            except Exception as exc:
                actual, error = None, str(exc)
            with self.condition: superseded = output in self.pending
            if not superseded: self.callback(output, actual, error)

    def close(self):
        with self.condition:
            self.stopped = True
            self.pending.clear()
            self.condition.notify()
