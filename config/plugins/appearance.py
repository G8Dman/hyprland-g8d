#!/usr/bin/env python3
"""Wallpaper picker, muted animated renderer and persistent g8d accent palette."""
import argparse
from contextlib import contextmanager
import colorsys
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import time

from PIL import Image
import psutil

ROOT = Path(os.environ.get('G8D_APPEARANCE_ROOT', Path(__file__).resolve().parent.parent))
DIRECTORY = Path.home() / 'Изображения/wallpaper'
SELECTION = ROOT / 'appearance.json'
SIGNATURE = os.environ.get('HYPRLAND_INSTANCE_SIGNATURE', 'offline')
RUNTIME = Path(os.environ.get('XDG_RUNTIME_DIR', '/tmp'))
RENDER_STATE = RUNTIME / f'g8d-wallpaper-{SIGNATURE}.json'
CACHE = Path.home() / '.cache/hyprland-g8d/wallpapers'
STATIC = {'.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff', '.webp', '.avif', '.heic'}
VIDEO = {'.gif', '.mp4', '.webm', '.mkv', '.mov', '.avi', '.m4v', '.mpeg', '.mpg', '.ogv', '.apng'}
PALETTE = {'Графит / бирюзовый': '#8bbfba', 'Лаванда': '#b6a3df', 'Небесный': '#8ab7ed',
           'Мята': '#91cfa4', 'Розовый': '#e7a2ba', 'Янтарный': '#e8bd7f', 'Коралловый': '#e99b8b'}


def read_selection():
    defaults = {'wallpaper': str(ROOT / 'wallpaper.png'), 'accent': '#8bbfba', 'wallpapers': {}}
    try: return {**defaults, **json.loads(SELECTION.read_text())}
    except (OSError, ValueError): return defaults


def monitors():
    return sorted(json.loads(subprocess.check_output(['hyprctl', '-j', 'monitors'], text=True)), key=lambda m: m['x'])


def wallpaper_for(output, selection=None):
    state = selection if selection is not None else read_selection()
    return Path(state.get('wallpapers', {}).get(output, state['wallpaper']))


def mpv_socket(output):
    key = hashlib.sha256(f'{SIGNATURE}:{output}'.encode()).hexdigest()[:20]
    return RUNTIME / f'g8d-mpv-{key}.sock'


def renderer_state():
    try: return json.loads(RENDER_STATE.read_text()).get('outputs', {})
    except (OSError, ValueError): return {}


def atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(content)
    temporary.replace(path)


def animated(path):
    if path.suffix.lower() in VIDEO: return True
    try:
        with Image.open(path) as image: return bool(getattr(image, 'is_animated', False))
    except OSError: return False


def thumbnail(path):
    CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(f'{path}:{path.stat().st_mtime_ns}:{path.stat().st_size}'.encode()).hexdigest()
    target = CACHE / f'{key}.png'
    if target.exists(): return target
    try:
        with Image.open(path) as image:
            image.thumbnail((320, 180))
            image.convert('RGB').save(target)
    except OSError:
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(path), '-frames:v', '1',
                        '-vf', 'scale=320:180:force_original_aspect_ratio=decrease', '-an', '-y', str(target)],
                       check=True, timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return target


def auto_accent(path):
    with Image.open(thumbnail(path)) as image:
        image = image.convert('RGB').resize((64, 64)).quantize(colors=12)
        palette = image.getpalette()
        candidates = []
        for count, index in image.getcolors():
            rgb = palette[index * 3:index * 3 + 3]
            h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
            candidates.append((count * (s + .12) * (.2 < v < .96), h, s))
        _, hue, saturation = max(candidates)
        color = colorsys.hsv_to_rgb(hue, min(.52, max(.20, saturation)), .87)
        return '#' + ''.join(f'{round(c * 255):02x}' for c in color)


def tagged_renderers(output=None):
    for process in psutil.process_iter(['name', 'cmdline']):
        try:
            arguments = process.info['cmdline'] or []
            if process.info['name'] not in ['swaybg', 'mpvpaper']: continue
            environment = process.environ()
            if environment.get('HYPRLAND_INSTANCE_SIGNATURE') != SIGNATURE: continue
            tagged = environment.get('G8D_WALLPAPER') == '1'
            legacy = process.info['name'] == 'swaybg' and str(ROOT / 'wallpaper.png') in arguments
            if (tagged or legacy) and (output is None or environment.get('G8D_WALLPAPER_OUTPUT') == output):
                yield process
        except (psutil.Error, OSError): continue


def suspend(output=None):
    selected = list(tagged_renderers(output))
    for process in selected:
        try: process.terminate()
        except psutil.NoSuchProcess: pass
    _, alive = psutil.wait_procs(selected, timeout=2)
    for process in alive:
        try: process.kill()
        except psutil.NoSuchProcess: pass
    psutil.wait_procs(alive, timeout=2)
    if output is None: RENDER_STATE.unlink(missing_ok=True)
    else:
        records = renderer_state()
        records.pop(output, None)
        atomic(RENDER_STATE, json.dumps({'outputs': records}))


def game_enabled():
    try: return json.loads((RUNTIME / f'g8d-game-{SIGNATURE}.json').read_text()).get('enabled', False)
    except (OSError, ValueError): return False


def start(force=False, output=None):
    if game_enabled() and not force: return
    connected = [monitor['name'] for monitor in monitors()]
    # Migrate a previous renderer spanning all outputs while keeping its image.
    legacy = False
    for process in tagged_renderers():
        try:
            if not process.environ().get('G8D_WALLPAPER_OUTPUT'): legacy = True
        except psutil.Error: pass
    if legacy:
        suspend()
        output = None
    for name in list(renderer_state()):
        if name not in connected: suspend(name)
    for name in connected:
        if output is None or name == output: start_output(name)


def start_output(output):
    path = wallpaper_for(output)
    if not path.is_file(): path = ROOT / 'wallpaper.png'
    current = renderer_state().get(output, {})
    if current.get('file') == str(path):
        try:
            process = psutil.Process(current['pid'])
            if process.is_running() and process.create_time() == current.get('created') and process.environ().get('G8D_WALLPAPER_OUTPUT') == output:
                return
        except (psutil.Error, OSError, KeyError): pass
    suspend(output)
    if animated(path):
        arguments = ['mpvpaper', '-p', '-a', 'FULL', '-o',
                     'no-config no-audio aid=no mute=yes volume=0 loop-file=inf panscan=1 osc=no osd-level=0 hwdec=auto-safe terminal=no msg-level=all=warn '
                     f'input-ipc-server={mpv_socket(output)}', output, str(path)]
    else:
        # Convert less common image formats to a cached PNG for swaybg.
        display_path = path
        if path.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.bmp'}:
            CACHE.mkdir(parents=True, exist_ok=True)
            key = hashlib.sha256(f'{path}:{path.stat().st_mtime_ns}'.encode()).hexdigest()
            display_path = CACHE / f'{key}-full.png'
            if not display_path.exists():
                with Image.open(path) as image: image.convert('RGB').save(display_path)
        arguments = ['swaybg', '-o', output, '-i', str(display_path), '-m', 'fill']
    logdir = Path.home() / '.local/state/hyprland-g8d'
    logdir.mkdir(parents=True, exist_ok=True)
    with (logdir / 'wallpaper.log').open('a') as log:
        process = subprocess.Popen(arguments, env={**os.environ, 'G8D_WALLPAPER': '1', 'G8D_WALLPAPER_OUTPUT': output},
                                   stdout=log, stderr=log, start_new_session=True)
    time.sleep(.35)
    if process.poll() is not None: raise RuntimeError('Обои не запустились; см. ~/.local/state/hyprland-g8d/wallpaper.log')
    records = renderer_state()
    records[output] = {'pid': process.pid, 'created': psutil.Process(process.pid).create_time(),
                       'file': str(path), 'animated': animated(path), 'argv': arguments,
                       'socket': str(mpv_socket(output)) if animated(path) else None}
    atomic(RENDER_STATE, json.dumps({'outputs': records}))


def apply_accent(accent, live=True):
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', accent): raise ValueError('Нужен цвет в формате #RRGGBB')
    accent = accent.lower()
    rgb = tuple(int(accent[i:i + 2], 16) for i in (1, 3, 5))
    def blend(factor):
        base = (17, 21, 25)
        return '#' + ''.join(f'{round(b + (c - b) * factor):02x}' for b, c in zip(base, rgb))
    replacements = {'#8bbfba': accent, '#a5d2cd': accent, '#b6d8d4': accent,
                    '#263638': blend(.17), '#304647': blend(.25), '#355653': blend(.32),
                    'rgba(8bbfbaff)': f'rgba({accent[1:]}ff)'}
    for relative in ['plugins/style.css', 'waybar.css', 'rofi.rasi', 'mako.conf', 'hyprlock.conf', 'kitty.conf']:
        text = (ROOT / 'appearance-templates' / relative).read_text()
        # Match once so replacements cannot be modified by later substitutions.
        expression = '|'.join(re.escape(k) for k in sorted(replacements, key=len, reverse=True))
        atomic(ROOT / relative, re.sub(expression, lambda match: replacements[match[0]], text, flags=re.I))
    lua = 'hl.config({ general = { col = { active_border = "rgba(' + accent[1:] + 'ff)" } } })\n'
    atomic(ROOT / 'accent.lua', lua)
    import branding
    branding.apply(ROOT,live=False)
    if not live: return
    subprocess.run(['hyprctl', 'eval', lua.strip()], check=True, capture_output=True)
    for process in psutil.process_iter(['name', 'cmdline']):
        try:
            if process.info['name'] == 'waybar' and str(ROOT / 'waybar.json') in (process.info['cmdline'] or []) and process.environ().get('HYPRLAND_INSTANCE_SIGNATURE') == SIGNATURE:
                process.send_signal(signal.SIGUSR2)
        except (psutil.Error, OSError): pass
    subprocess.run(['makoctl', 'reload'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    panel_socket = RUNTIME / f'g8d-panels-{os.getuid()}-{SIGNATURE}.sock'
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as connection:
            connection.sendto(b'{"appearance":"reload"}', str(panel_socket))
    except OSError: pass


@contextmanager
def locked():
    with (RUNTIME / f'g8d-appearance-{SIGNATURE}.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def change(path=None, accent=None, output=None):
    with locked(): change_locked(path, accent, output)


def change_locked(path=None, accent=None, output=None):
    state = read_selection()
    if path is not None:
        path = Path(path).expanduser().resolve()
        if not path.is_file() or path.suffix.lower() not in STATIC | VIDEO:
            raise ValueError('Файл не найден или формат не поддерживается')
        thumbnail(path)  # Validate before replacing the current wallpaper.
        if output is None:
            state['wallpaper'] = str(path)
            state['wallpapers'] = {}
        else:
            state['wallpapers'][output] = str(path)
    if accent == 'auto':
        if output is None:
            active = next((m['name'] for m in monitors() if m.get('focused')), '')
            accent = auto_accent(wallpaper_for(active, state))
        else: accent = auto_accent(wallpaper_for(output, state))
    if accent is not None:
        apply_accent(accent)
        state['accent'] = accent.lower()
    old = read_selection()
    atomic(SELECTION, json.dumps(state, ensure_ascii=False, indent=2))
    try:
        if path is not None and not game_enabled(): start(output=output)
    except Exception:
        atomic(SELECTION, json.dumps(old, ensure_ascii=False, indent=2))
        apply_accent(old['accent'])
        start(output=output)
        raise


def menu(entries, prompt, indices=False, grid=True):
    command = ['rofi', '-no-config', '-theme', str(ROOT / 'rofi.rasi'), '-dmenu', '-i',
               '-show-icons', '-p', prompt, '-format', 'i' if indices else 's']
    theme = 'entry { placeholder: "Поиск…"; } '
    if indices and grid:
        theme += ('window { width: 800px; } listview { columns: 3; lines: 3; } '
                    'element { orientation: vertical; } element-icon { size: 120px; } '
                    'element-text { horizontal-align: 0.5; }')
    command += ['-theme-str', theme]
    process = subprocess.run(command,
                             input='\n'.join(entries) + '\n', text=True, capture_output=True)
    if process.returncode != 0: return None
    return process.stdout.strip()


def picker():
    action = menu(['Обои', 'Акцентный цвет', 'Обои + цвет из изображения'], 'g8d / оформление')
    if action is None: return
    if action in ['Обои', 'Обои + цвет из изображения']:
        connected = monitors()
        labels = ['Все экраны — одинаковые обои']
        outputs = [None]
        for monitor in connected:
            name = monitor['name']
            title = monitor.get('description', name)
            labels.append(f'{title} [{name}] · {wallpaper_for(name).name}')
            outputs.append(name)
        selected = menu(labels, 'На какой экран?', indices=True, grid=False)
        if selected is None or not selected.isdigit() or not 0 <= int(selected) < len(outputs): return
        output = outputs[int(selected)]
        DIRECTORY.mkdir(parents=True, exist_ok=True)
        files = sorted((p for p in DIRECTORY.rglob('*') if p.is_file() and p.suffix.lower() in STATIC | VIDEO), key=lambda p: str(p).casefold())
        if not files:
            subprocess.run(['notify-send', 'g8d / обои', f'Нет поддерживаемых файлов в {DIRECTORY}'])
            return
        entries = []
        for path in files:
            text = str(path.relative_to(DIRECTORY)).replace('\n', ' ')
            try: text += '\0icon\x1f' + str(thumbnail(path))
            except (OSError, subprocess.SubprocessError): pass
            entries.append(text)
        index = menu(entries, 'Выбери обои', indices=True)
        if index is None: return
        if not index.isdigit() or not 0 <= int(index) < len(files): return
        change(files[int(index)], 'auto' if action == 'Обои + цвет из изображения' else None, output)
    elif action == 'Акцентный цвет':
        choice = menu(['Цвет из текущих обоев', *PALETTE, 'Свой цвет #RRGGBB'], 'Акцент')
        if choice is None: return
        accent = 'auto' if choice == 'Цвет из текущих обоев' else PALETTE.get(choice)
        if choice == 'Свой цвет #RRGGBB': accent = menu([], 'Введи #RRGGBB')
        if accent is not None: change(accent=accent)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', nargs='?', default='picker', choices=['picker', 'start', 'suspend', 'resume', 'apply'])
    parser.add_argument('--file')
    parser.add_argument('--accent')
    parser.add_argument('--output', help='Monitor name; omit to apply to every output')
    arguments = parser.parse_args()
    try:
        if arguments.action == 'picker': picker()
        elif arguments.action == 'apply': change(arguments.file, arguments.accent, arguments.output)
        else:
            with locked():
                if arguments.action in ['start', 'resume']: start(force=arguments.action == 'resume')
                else: suspend()
    except Exception as exc:
        subprocess.run(['notify-send', 'g8d / оформление', str(exc)])
        raise
