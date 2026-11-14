"""g8d integration for the standalone yamusic-cli background player."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.parse
import urllib.request

BINARY = Path.home() / '.local/bin/yamusic-cli'
CONFIG = Path.home() / '.config/yamusic-cli/config.toml'
SERVICE = 'g8d-yamusic.service'
BUS = 'org.mpris.MediaPlayer2.yamusic-cli'
_failed_covers = {}


def command(*args, timeout=45):
    result = subprocess.run([str(BINARY), '--json', *args], capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'Команда Яндекс Музыки не выполнена')
    return json.loads(result.stdout or '{}')


def ensure_running():
    if not CONFIG.is_file():
        raise RuntimeError('Подключите аккаунт Яндекса к yamusic-cli')
    try:
        command('status', timeout=2)
        return
    except (OSError, RuntimeError, subprocess.SubprocessError):
        pass
    result = subprocess.run(['systemctl', '--user', 'start', SERVICE], capture_output=True, text=True, timeout=5)
    if result.returncode:
        raise RuntimeError('Не удалось запустить фоновый плеер: ' + result.stderr.strip())
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline:
        try:
            command('status', timeout=2)
            return
        except (OSError, RuntimeError, subprocess.SubprocessError):
            time.sleep(.2)
    raise RuntimeError('Плеер не подключился к Яндексу. Проверьте сеть и аккаунт.')


def pause_official():
    # Do not leave two independent players making sound after migration.
    from data import media, media_control
    for player in media():
        if player.get('yandex') and player['bus'] != BUS and player['status'] == 'Playing':
            media_control(player['bus'], 'Pause')


def run(action):
    if action in ('open', 'show'):
        show_official()
        return {'shown': True}
    if action not in ('background', 'wave', 'favorites'):
        raise ValueError('Команды: background, show, wave, favorites')
    ensure_running()
    if action == 'background':
        return {'running': True}
    pause_official()
    result = command('wave' if action == 'wave' else 'liked', timeout=45)
    # The upstream audio thread accepts files asynchronously. Verify actual progress,
    # rather than reporting success just because the source loaded.
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        status = command('status', timeout=2)
        if status.get('state', '').lower() == 'playing' and status.get('position_ms', 0) > 100:
            return result
        time.sleep(.15)
    raise RuntimeError('Подборка загружена, но звук не запустился. Повторите запуск.')


def show_official():
    # The desktop app is optional now and does not provide the CLI's playback.
    from yandex_control import windows, lua
    if not windows():
        subprocess.Popen(['/usr/bin/yandex-music'], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        window = next(iter(windows()), None)
        if window:
            target = json.dumps('address:' + window['address'])
            try:
                lua(f'local w = hl.get_active_workspace(); if w then '
                    f'hl.dispatch(hl.dsp.window.move({{window = {target}, workspace = w.id, follow = false}})); '
                    f'hl.dispatch(hl.dsp.focus({{window = {target}}})); end')
                return
            except RuntimeError:
                # Electron can replace its initial window during startup.
                pass
        time.sleep(.1)
    raise RuntimeError('Не удалось показать приложение')


def cover_file(uri):
    """Fetch a public album image on the collector thread, never the GTK thread."""
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme != 'https' or parsed.hostname != 'avatars.yandex.net' and parsed.hostname != 'avatars.mds.yandex.net':
        return ''
    folder = Path.home() / '.cache/hyprland-g8d/music-covers'
    path = folder / (hashlib.sha256(uri.encode()).hexdigest() + '.jpg')
    if path.is_file():
        return path.as_uri()
    if _failed_covers.get(uri, 0) > time.monotonic():
        return ''
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(uri, timeout=2) as response:
            content = response.read(6 * 1024 * 1024 + 1)
        if len(content) > 6 * 1024 * 1024:
            raise ValueError('Cover too large')
        temporary = path.with_suffix('.tmp')
        temporary.write_bytes(content)
        temporary.replace(path)
        return path.as_uri()
    except (OSError, ValueError):
        _failed_covers[uri] = time.monotonic() + 30
        return ''
