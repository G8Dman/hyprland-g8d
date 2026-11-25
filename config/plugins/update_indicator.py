"""One GitHub release check per local clock hour, shared by all Waybar outputs."""
import fcntl
import json
import os
from pathlib import Path
import time

import updater


def hour(now):
    local = time.localtime(now)
    return int(now) - 60 * local.tm_min - local.tm_sec


def check(cache, now):
    bucket = hour(now)
    with cache.open('a+') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.seek(0)
        try:
            state = json.load(stream)
        except ValueError:
            state = {}
        if not isinstance(state, dict):
            state = {}
        if state.get('hour') != bucket:
            try:
                release = updater.latest(json.loads(updater.fetch(updater.API, timeout=12)))
                updater.release_assets(release)
                state['tag'] = release['tag_name']
            except (OSError, RuntimeError, ValueError):
                pass
            state['hour'] = bucket
            stream.seek(0)
            stream.truncate()
            json.dump(state, stream)
        return state.get('tag')


def indicator(current, tag):
    current, candidate = updater.version(current), updater.version(tag) if isinstance(tag, str) else None
    if not candidate or not current or candidate <= current:
        return {'text': ''}
    return {'text': '↻', 'tooltip': f'Доступно обновление g8d {tag}\nОткрыть «О системе»'}


def main():
    runtime = os.environ.get('XDG_RUNTIME_DIR')
    state = Path(runtime) if runtime else Path.home() / '.cache' / 'hyprland-g8d'
    state.mkdir(parents=True, exist_ok=True)
    cache = state / 'g8d-update-indicator.json'
    last = None
    while True:
        try:
            current = (updater.ROOT / 'VERSION').read_text().strip()
        except OSError:
            current = ''
        value = indicator(current, check(cache, time.time()))
        if value != last:
            print(json.dumps(value, ensure_ascii=False), flush=True)
            last = value
        now = time.time()
        time.sleep(min(10, max(0.1, hour(now) + 3600 - now)))


if __name__ == '__main__':
    main()
