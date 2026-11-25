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
import sys
import time

from PIL import Image
import psutil
import ui_themes

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
TASKBAR_STYLES = {'graphite': 'Graphite', 'clear': 'Clear'}
THEMES = TASKBAR_STYLES  # Legacy API: --theme selects the taskbar, never the interface.
UI_STYLES = ui_themes.STYLES
MODES = {'light': 'Светлая', 'dark': 'Тёмная'}
THEME_FILES = ['plugins/style.css', 'plugins/settings.css', 'waybar.css',
               'rofi.rasi', 'mako.conf', 'hyprlock.conf', 'kitty.conf']
COLOR_LABELS = {'background': 'Фон', 'surface': 'Поверхности', 'control': 'Кнопки',
                'text': 'Основной текст', 'muted': 'Вторичный текст', 'border': 'Границы',
                'selection': 'Выделение', 'bar_text': 'Текст верхней панели'}
DEFAULT_COLORS = {
    'graphite': dict(zip(COLOR_LABELS, ['#161b20', '#1b232a', '#222c32', '#dbe1e5', '#80909c', '#35454b', '#263638', '#c2ccd3'])),
    'clear': dict(zip(COLOR_LABELS, ['#f9fbfd', '#ffffff', '#edf2f7', '#263544', '#64778a', '#d4dee7', '#e2edf7', '#ffffff']))}


def read_selection():
    defaults = {'wallpaper': str(ROOT / 'wallpaper.png'), 'accent': '#8bbfba', 'wallpapers': {}, 'theme': 'graphite'}
    try: state = {**defaults, **json.loads(SELECTION.read_text())}
    except (OSError, ValueError): state = defaults
    state.setdefault('ui_style', 'material')
    state.setdefault('mode', 'light' if state['theme'] == 'clear' else 'dark')
    return state


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


def luminance(rgb):
    values = [v / 255 / 12.92 if v / 255 <= .04045 else ((v / 255 + .055) / 1.055) ** 2.4 for v in rgb]
    return sum(v * weight for v, weight in zip(values, [.2126, .7152, .0722]))


def rgb(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def contrast(first, second):
    a, b = sorted((luminance(rgb(first)), luminance(rgb(second))))
    return (b + .05) / (a + .05)


def analyze_wallpaper(path):
    """One deterministic analysis per image/video selection; never per animation frame."""
    with Image.open(thumbnail(path)) as image:
        sample = image.convert('RGB').resize((96, 96))
        lightness = []
        for pixel in sample.getdata():
            y = luminance(pixel)
            lightness.append((116 * y ** (1 / 3) - 16 if y > .008856 else 903.3 * y) / 100)
        lightness.sort()
        brightness = .7 * sum(lightness) / len(lightness) + .3 * lightness[len(lightness) // 2]
        theme = 'clear' if brightness >= .55 else 'graphite'
        image = sample.quantize(colors=24)
        palette = image.getpalette()
        candidates = []
        for count, index in image.getcolors():
            channels = palette[index * 3:index * 3 + 3]
            h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in channels))
            if s >= .15 and v >= .12:
                candidates.append((count * (.2 + s) ** 1.5, h, s))
        if candidates:
            _, hue, saturation = max(candidates)
            color = colorsys.hsv_to_rgb(hue, min(.65, saturation), .87 if theme == 'graphite' else .68)
            accent = '#' + ''.join(f'{round(c * 255):02x}' for c in color)
        else:
            accent = '#9ba7b3' if theme == 'graphite' else '#587083'
        return {'mode': 'light' if theme == 'clear' else 'dark', 'accent': accent, 'brightness': round(brightness, 3)}


def auto_accent(path):
    return analyze_wallpaper(path)['accent']


def theme_mode(state=None):
    state = read_selection() if state is None else state
    mode = state.get('mode', 'light' if theme_name(state) == 'clear' else 'dark')
    return mode if mode in MODES else 'dark'


def interface_style(state=None):
    state = read_selection() if state is None else state
    value = state.get('ui_style', 'material')
    return value if value in UI_STYLES else 'material'


def palette_key(theme, mode, ui_style='material'):
    return ('' if ui_style == 'material' else ui_style + ':') + theme + ':' + mode


def default_colors(theme, mode, ui_style='material'):
    palette = dict(ui_themes.NOTHING_COLORS[mode] if ui_style == 'nothing' else DEFAULT_COLORS['clear' if mode == 'light' else 'graphite'])
    palette['bar_text'] = '#ffffff' if theme == 'clear' else DEFAULT_COLORS['clear' if mode == 'light' else 'graphite']['text']
    return palette


def color_overrides(theme, mode, state):
    profiles = state.get('theme_colors', {})
    style = interface_style(state)
    legacy = profiles.get(theme, {}) if style == 'material' and mode == ('light' if theme == 'clear' else 'dark') else {}
    return profiles.get(palette_key(theme, mode, style), legacy)


def theme_colors(theme=None, state=None, mode=None):
    state = read_selection() if state is None else state
    theme = theme_name(state) if theme is None else theme
    mode = theme_mode(state) if mode is None else mode
    return {**default_colors(theme, mode, interface_style(state)), **color_overrides(theme, mode, state)}


def validate_colors(colors, theme, mode=None, ui_style='material'):
    if not isinstance(colors, dict): raise ValueError('Цвета должны быть объектом JSON')
    for key, value in colors.items():
        if key not in COLOR_LABELS: raise ValueError('Неизвестный цвет: ' + key)
        if not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
            raise ValueError(COLOR_LABELS[key] + ': нужен цвет #RRGGBB')
    merged = {**default_colors(theme, theme_mode() if mode is None else mode, ui_style), **colors}
    for role in ['background', 'surface', 'control', 'selection']:
        if contrast(merged['text'], merged[role]) < 4.5:
            raise ValueError('Основной текст плохо читается на цвете «' + COLOR_LABELS[role] + '». Измени текст или фон.')
    if any(contrast(merged['muted'], merged[role]) < 3 for role in ['background', 'surface']):
        raise ValueError('Вторичный текст плохо читается. Измени его цвет или фон.')
    return {key: value.lower() for key, value in colors.items()}


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


def start(force=False, output=None, *, fallback=True):
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
    bundled = ROOT / 'wallpaper.png'
    outputs = [name for name in connected if output is None or name == output]
    failures = []
    for name in outputs:
        if not fallback:
            start_output(name, wallpaper_for(name))
            continue
        try:
            path = wallpaper_for(name)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            print(f'Wallpaper selection on {name}: {exc}', file=sys.stderr)
            path = bundled
        candidates = (bundled, None) if path == bundled else (path, bundled, None)
        for candidate in candidates:
            try:
                start_output(name, candidate)
                break
            except (RuntimeError, OSError, ValueError, Image.DecompressionBombError, psutil.Error) as exc:
                print(f'Wallpaper on {name} ({candidate or "solid background"}): {exc}', file=sys.stderr)
        else:
            failures.append(name)
    if failures and len(failures) == len(outputs):
        raise RuntimeError('Не удалось запустить фон на экранах: ' + ', '.join(failures))


def start_output(output, path):
    if path is not None and not path.is_file():
        raise FileNotFoundError(path)
    source = str(path) if path is not None else None
    current = renderer_state().get(output, {})
    if current.get('file') == source:
        try:
            process = psutil.Process(current['pid'])
            if process.is_running() and process.create_time() == current.get('created') and process.environ().get('G8D_WALLPAPER_OUTPUT') == output:
                return
        except (psutil.Error, OSError, KeyError): pass
    is_animated = path is not None and animated(path)
    suspend(output)
    if path is None:
        arguments = ['swaybg', '-o', output, '-c', '#161b20']
    elif is_animated:
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
    try:
        records = renderer_state()
        records[output] = {'pid': process.pid, 'created': psutil.Process(process.pid).create_time(),
                           'file': source, 'animated': is_animated, 'argv': arguments,
                           'socket': str(mpv_socket(output)) if is_animated else None}
        atomic(RENDER_STATE, json.dumps({'outputs': records}))
    except (OSError, psutil.Error):
        process.terminate()
        raise


def theme_name(state=None):
    name = (read_selection() if state is None else state).get('theme', 'graphite')
    return name if name in THEMES else 'graphite'


def recolor_template(text, theme, replacements, overrides, relative):
    """Replace source color tokens once, preserving CSS/Hyprlock alpha channels."""
    groups = {
        'graphite': {
            'background': '111519 161b20 11171c', 'surface': '1b232a 1c252d 1c2329',
            'control': '222c32 26333e 283b4a 304252 273239',
            'text': 'dbe1e5 c2ccd3 c9d1d8', 'muted': '80909c 8e9ba6 7a8792 74838f 65737e',
            'border': '35454b 303e46 3b4b57 2c3943 2b363e 303b43 263039',
            'selection': '263638 263746 27384a'},
        'clear': {
            'background': 'f9fbfd f5f8fb f7fafc eff4f8 edf3f8', 'surface': 'ffffff',
            'control': 'edf2f7 f6f9fc e2ecf5 eaf1f8 dce5ed edf1f5',
            'text': '263544 475d70', 'muted': '64778a 667889 8694a1 8593a0',
            'border': 'd4dee7 d6e0e9 d1dce6 e2e9f0 dde5ec',
            'selection': 'e2edf7 e0ebf5 dae8f3'}}
    mapping = {key.lstrip('#'): value for key, value in replacements.items() if key.startswith('#')}
    for role, value in overrides.items():
        for original in groups[theme].get(role, '').split():
            if relative == 'waybar.css' and original == 'ffffff': continue
            mapping[original] = value
    def replace(match):
        token = match[0]
        if token.startswith('#'):
            key = token[1:7].lower()
            return mapping.get(key, token[:7]) + token[7:] if key in mapping else token
        inner = token[5:-1]
        if ',' not in inner:
            key = inner[:6].lower()
            return 'rgba(' + mapping[key][1:] + inner[6:] + ')' if key in mapping else token
        parts = inner.split(',')
        key = ''.join(f'{int(v.strip()):02x}' for v in parts[:3])
        return 'rgba(' + ', '.join(str(c) for c in rgb(mapping[key])) + ',' + parts[3] + ')' if key in mapping else token
    text = re.sub(r'rgba\([0-9a-fA-F]{8}\)|rgba\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*[\d.]+\s*\)|#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?\b', replace, text)
    if relative == 'waybar.css' and 'bar_text' in overrides:
        text += '\nwindow#waybar, window#waybar label { color: ' + overrides['bar_text'] + '; }\n'
    return text


def apply_accent(accent, live=True, theme=None, colors=None, mode=None, lock_background=None, ui_style=None):
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', accent): raise ValueError('Нужен цвет в формате #RRGGBB')
    accent = accent.lower()
    theme = theme_name() if theme is None else theme
    if theme not in THEMES: raise ValueError('Неизвестная тема: ' + theme)
    state = read_selection()
    mode = theme_mode(state) if mode is None else mode
    if mode not in MODES: raise ValueError('Неизвестный режим: ' + mode)
    ui_style = interface_style(state) if ui_style is None else ui_style
    if ui_style not in UI_STYLES: raise ValueError('Неизвестный стиль интерфейса: ' + ui_style)
    colors = color_overrides(theme, mode, {**state, 'ui_style':ui_style}) if colors is None else colors
    colors = validate_colors(colors, theme, mode, ui_style)
    palette = {**default_colors(theme, mode, ui_style), **colors}
    lock_background = state.get('lock_background', '') if lock_background is None else lock_background
    channels = rgb(accent)
    ink = list(channels)
    surfaces = [palette[key] for key in ['background', 'surface', 'control', 'selection']]
    weakest = lambda color: min(contrast(color, bg) for bg in surfaces)
    target = (0, 0, 0) if weakest('#000000') >= weakest('#ffffff') else (255, 255, 255)
    for _ in range(128):
        color = '#' + ''.join(f'{c:02x}' for c in ink)
        if weakest(color) >= 4.5: break
        ink = [round(c * .9 + end * .1) if abs(end - c) > 9 else end for c, end in zip(ink, target)]
    surface_accent = '#' + ''.join(f'{c:02x}' for c in ink)
    quick_accent = surface_accent
    bar_palette = {**default_colors(theme, mode), **{key:value for key,value in colors.items() if key == 'bar_text'}}
    bar_ink = list(channels)
    bar_surfaces = [bar_palette[key] for key in ['background','surface','control','selection']]
    for _ in range(128):
        bar_accent = '#' + ''.join(f'{c:02x}' for c in bar_ink)
        if min(contrast(bar_accent, bg) for bg in bar_surfaces) >= 4.5: break
        end = 0 if mode == 'light' else 255
        bar_ink = [round(c*.9 + end*.1) if abs(end-c)>9 else end for c in bar_ink]
    if ui_style == 'nothing': surface_accent = palette['text']
    def blend(factor):
        base = (17, 21, 25)
        return '#' + ''.join(f'{round(b + (c - b) * factor):02x}' for b, c in zip(base, channels))
    replacements = {'#8bbfba': surface_accent, '#a5d2cd': surface_accent, '#b6d8d4': surface_accent,
                    '#263638': blend(.17), '#304647': blend(.25), '#355653': blend(.32),
                    '#ef9e9e': '#ef9e9e' if mode == 'dark' else '#b33543',
                    '#b33543': '#ef9e9e' if mode == 'dark' else '#b33543',
                    }
    source = ROOT / ('appearance-templates' if theme == 'graphite' else 'themes/' + theme)
    rendered = {}
    for relative in THEME_FILES:
        text = (source / relative).read_text()
        if relative == 'waybar.css' and ui_style == 'nothing':
            bar_replacements = {**replacements, '#8bbfba':bar_accent, '#a5d2cd':bar_accent, '#b6d8d4':bar_accent}
            rendered[relative] = recolor_template(text, theme, bar_replacements, bar_palette, relative)
        else:
            rendered[relative] = recolor_template(text, theme, replacements, palette, relative)
        if relative == 'plugins/settings.css':
            on_primary = '#000000' if contrast(surface_accent, '#000000') > contrast(surface_accent, '#ffffff') else '#ffffff'
            rendered[relative] += '\n@define-color md_on_primary ' + on_primary + ';\n'
    lock = rendered['hyprlock.conf'].replace('font_family = DejaVu Sans', 'font_family = Roboto')
    lock = lock.replace('background {', 'background {\n    path = ' + lock_background)
    card_color = palette['surface'][1:] + 'eb'
    lock += ('\nshape {\n    monitor =\n    size = 430, 430\n    color = rgba(' + card_color + ')\n'
             '    rounding = 28\n    border_size = 1\n    border_color = rgba(' + palette['border'][1:] + '99)\n'
             '    position = 0, -10\n    halign = center\n    valign = center\n    zindex = -1\n}\n')
    lock = lock.replace('background {\n', 'background {\n    zindex = -2\n', 1)
    rendered['hyprlock.conf'] = lock
    rendered['plugins/style.css'] += '\n@define-color md_surface ' + palette['background'] + ';\n'
    if mode == 'light':
        rendered['plugins/style.css'] = rendered['plugins/style.css'].replace('#ef9e9e', '#b33543')
    if theme == 'graphite':
        rendered['waybar.css'] += ('\nwindow#waybar { background: ' + (bar_palette if ui_style == 'nothing' else palette)['background'] + '; color: ' + palette['bar_text'] + '; }\n')
    if ui_style == 'nothing':
        ui_themes.render(rendered, palette, mode)
        rendered['plugins/style.css'] += '\n@define-color nd_quick_accent ' + quick_accent + ';\n'
    inactive = palette['border'][1:] + 'aa'
    rounding = 8 if ui_style == 'nothing' else 12 if theme == 'clear' else 8
    lua = ('hl.config({ general = { col = { active_border = "rgba(' + (surface_accent if ui_style == 'nothing' else accent)[1:] + 'ff)", '
           'inactive_border = "rgba(' + inactive + ')" } }, decoration = { rounding = ' + str(rounding) + ' } })\n')
    # Finish reading and validating every source before replacing generated files.
    for relative, content in rendered.items(): atomic(ROOT / relative, content)
    atomic(ROOT / 'accent.lua', lua)
    import branding
    branding.apply(ROOT,live=False)
    if live:
        if ui_style == 'nothing': ui_themes.ensure_fonts(ROOT)
        reload_appearance(lua)


def reload_appearance(lua=None):
    lua = (ROOT / 'accent.lua').read_text() if lua is None else lua
    result = subprocess.run(['hyprctl', 'eval', lua.strip()], check=True, capture_output=True, text=True, timeout=8)
    if result.stdout.strip() != 'ok': raise RuntimeError(result.stdout.strip() or 'Hyprland не применил оформление')
    reload_mako = False
    for process in psutil.process_iter(['name', 'cmdline']):
        try:
            if process.info['name'] == 'mako' and process.environ().get('HYPRLAND_INSTANCE_SIGNATURE') == SIGNATURE:
                reload_mako = True
            if process.info['name'] == 'waybar' and str(ROOT / 'waybar.json') in (process.info['cmdline'] or []) and process.environ().get('HYPRLAND_INSTANCE_SIGNATURE') == SIGNATURE:
                process.send_signal(signal.SIGUSR2)
        except (psutil.Error, OSError): pass
    if reload_mako:
        try: subprocess.run(['makoctl', 'reload'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
        except (OSError, subprocess.TimeoutExpired): pass
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


def change(path=None, accent=None, output=None, theme=None, live=True, colors=None, reset_colors=False, auto=None, mode=None, lock_background=None, ui_style=None):
    with locked(): change_locked(path, accent, output, theme, live, colors, reset_colors, auto, mode, lock_background, ui_style)


def change_locked(path=None, accent=None, output=None, theme=None, live=True, colors=None, reset_colors=False, auto=None, mode=None, lock_background=None, ui_style=None):
    state = read_selection()
    if ui_style is not None:
        if ui_style not in UI_STYLES: raise ValueError('Неизвестный стиль интерфейса: ' + ui_style)
        state['ui_style'] = ui_style
    if theme is not None:
        if theme not in THEMES: raise ValueError('Неизвестная тема: ' + theme)
        state['theme'] = theme
    if mode is not None:
        if mode not in MODES: raise ValueError('Неизвестный режим: ' + mode)
        state['mode'] = mode
    if lock_background is not None:
        if lock_background:
            candidate = Path(lock_background).expanduser().resolve()
            if not candidate.is_file() or candidate.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
                raise ValueError('Для блокировки выбери PNG, JPEG или WebP')
            if any(c in str(candidate) for c in ['\n', '\r', '#', '$']): raise ValueError('В пути есть символы конфигурации Hyprlock')
            with Image.open(candidate) as image: image.verify()
            lock_background = str(candidate)
        state['lock_background'] = lock_background
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
    explicit_auto = accent == 'auto' or auto is True
    if auto is not None: state['wallpaper_colors'] = bool(auto)
    if auto is False and output is not None: state['palette_output'] = output
    if not explicit_auto and (mode is not None or accent is not None or colors is not None or reset_colors):
        if state.get('wallpaper_colors'): state['wallpaper_colors'] = False
    automatic = explicit_auto or (path is not None and state.get('wallpaper_colors') and
                                  (output is None or output == state.get('palette_output')))
    if automatic:
        source = output if explicit_auto and output is not None else state.get('palette_output')
        if source is None:
            source = next((m['name'] for m in monitors() if m.get('focused')), '') if live else ''
        image = wallpaper_for(source, state)
        analysis = analyze_wallpaper(image)
        state.update(mode=analysis['mode'], wallpaper_colors=True, palette_output=source,
                     palette_source=str(image), wallpaper_brightness=analysis['brightness'])
        accent = analysis['accent']
    if accent is not None: state['accent'] = accent.lower()
    active_theme = theme_name(state)
    if colors is not None or reset_colors:
        values = {} if reset_colors else validate_colors(colors, active_theme, theme_mode(state), interface_style(state))
        state.setdefault('theme_colors', {})[palette_key(active_theme, theme_mode(state), interface_style(state))] = values
    styled = ui_style is not None or mode is not None or lock_background is not None or automatic or accent is not None or theme is not None or colors is not None or reset_colors
    affected = [SELECTION]
    if styled:
        affected += [ROOT / name for name in [*THEME_FILES, 'accent.lua', 'waybar.json']]
    previous = {p: p.read_bytes() if p.exists() else None for p in affected}
    try:
        if styled:
            apply_accent(state['accent'], live=False, theme=active_theme,
                         colors=color_overrides(active_theme, theme_mode(state), state),
                         mode=theme_mode(state), lock_background=state.get('lock_background', ''), ui_style=interface_style(state))
        atomic(SELECTION, json.dumps(state, ensure_ascii=False, indent=2))
        if live and styled:
            if interface_style(state) == 'nothing': ui_themes.ensure_fonts(ROOT)
            reload_appearance()
        if live and path is not None and not game_enabled(): start(output=output, fallback=False)
    except Exception:
        for target, content in previous.items():
            if content is None: target.unlink(missing_ok=True)
            else: atomic(target, content.decode())
        if live:
            try:
                if styled: reload_appearance()
                if path is not None and not game_enabled(): start(output=output)
            except Exception: pass
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
    action = menu(['Обои', 'Акцентный цвет', 'Обои + цвет из изображения', 'Стиль интерфейса', 'Стиль таскбара'], 'g8d / оформление')
    if action is None: return
    if action in ['Обои', 'Обои + цвет из изображения']:
        connected = monitors()
        labels = ['Все экраны — одинаковые обои']
        outputs = [None]
        for monitor in connected:
            name = monitor['name']
            title = monitor.get('description') or name
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
    elif action == 'Стиль интерфейса':
        styles = list(UI_STYLES)
        choice = menu([UI_STYLES[key] for key in styles], 'Стиль интерфейса', indices=True, grid=False)
        if choice is not None and choice.isdigit() and 0 <= int(choice) < len(styles):
            change(ui_style=styles[int(choice)])
    elif action == 'Стиль таскбара':
        current = theme_name()
        styles = list(TASKBAR_STYLES)
        descriptions = {'graphite': 'сплошная панель', 'clear': 'прозрачная панель'}
        choice = menu([TASKBAR_STYLES[key] + ' · ' + descriptions[key] +
                       (' · текущий' if key == current else '') for key in styles],
                      'Стиль таскбара', indices=True, grid=False)
        if choice is not None and choice.isdigit() and 0 <= int(choice) < len(styles):
            change(theme=styles[int(choice)])
    elif action == 'Акцентный цвет':
        choice = menu(['Яркость и цвет из текущих обоев', *PALETTE, 'Свой цвет #RRGGBB'], 'Акцент')
        if choice is None: return
        accent = 'auto' if choice == 'Яркость и цвет из текущих обоев' else PALETTE.get(choice)
        if choice == 'Свой цвет #RRGGBB': accent = menu([], 'Введи #RRGGBB')
        if accent is not None: change(accent=accent)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', nargs='?', default='picker', choices=['picker', 'start', 'suspend', 'resume', 'apply'])
    parser.add_argument('--file')
    parser.add_argument('--accent')
    parser.add_argument('--theme', '--taskbar-style', dest='theme', choices=list(TASKBAR_STYLES), help='Taskbar style: Graphite or Clear')
    parser.add_argument('--ui-style', choices=list(UI_STYLES), help='Interface design: Material or Nothing')
    parser.add_argument('--mode', choices=list(MODES))
    parser.add_argument('--lock-background', help='PNG/JPEG/WebP path, empty string restores a solid background')
    parser.add_argument('--no-live', action='store_true', help='Generate and save without touching the running session')
    parser.add_argument('--colors', help='JSON object of custom theme color roles')
    parser.add_argument('--reset-colors', action='store_true', help='Restore the active theme palette')
    parser.add_argument('--auto-theme', choices=['on', 'off'], help='Choose light/dark theme and accent from wallpaper')
    parser.add_argument('--output', help='Monitor name; omit to apply to every output')
    arguments = parser.parse_args()
    try:
        if arguments.action == 'picker': picker()
        elif arguments.action == 'apply':
            change(arguments.file, arguments.accent, arguments.output, arguments.theme, not arguments.no_live,
                   json.loads(arguments.colors) if arguments.colors is not None else None, arguments.reset_colors,
                   arguments.auto_theme == 'on' if arguments.auto_theme is not None else None,
                   arguments.mode, arguments.lock_background, arguments.ui_style)
        else:
            with locked():
                if arguments.action in ['start', 'resume']: start(force=arguments.action == 'resume')
                else: suspend()
    except Exception as exc:
        subprocess.run(['notify-send', 'g8d / оформление', str(exc)])
        raise
