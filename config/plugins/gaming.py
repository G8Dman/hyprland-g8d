"""Reversible, per-session memory reduction for g8d-owned desktop components."""
import json
import os
from pathlib import Path
import subprocess
import time

import psutil
import appearance

ROOT = Path(__file__).resolve().parent.parent
SIGNATURE = os.environ['HYPRLAND_INSTANCE_SIGNATURE']
STATE = Path(os.environ['XDG_RUNTIME_DIR']) / f'g8d-game-{SIGNATURE}.json'


def ctl(*arguments):
    return subprocess.check_output(['hyprctl', *arguments], text=True, timeout=5)


def read_state():
    try: return json.loads(STATE.read_text())
    except (OSError, ValueError): return {'enabled': False}


def save(state):
    temporary = STATE.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    temporary.chmod(0o600)
    temporary.replace(STATE)


def components():
    selected = []
    for process in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            arguments = process.info['cmdline'] or []
            name = process.info['name']
            if name not in ['waybar', 'swaybg', 'mpvpaper', 'python3', 'python']: continue
            environment = process.environ()
            eligible = ((name == 'waybar' and str(ROOT / 'waybar.json') in arguments)
                        or (name == 'swaybg' and str(ROOT / 'wallpaper.png') in arguments)
                        or (name in ['swaybg', 'mpvpaper'] and environment.get('G8D_WALLPAPER') == '1')
                        or str(ROOT / 'workspaces.py') in arguments)
            if not eligible or environment.get('HYPRLAND_INSTANCE_SIGNATURE') != SIGNATURE: continue
            try: memory = process.memory_full_info().pss / 1048576
            except (psutil.Error, OSError): memory = 0
            selected.append((process, arguments, name, memory))
        except (psutil.Error, OSError): continue
    return selected


def options():
    result = {}
    for name in ['animations:enabled', 'decoration:shadow:enabled']:
        option = json.loads(ctl('-j', 'getoption', name))
        result[name] = bool(option.get('bool', option.get('int', 0)))
    return result


def configure(animations, shadows):
    value = lambda enabled: 'true' if enabled else 'false'
    result = ctl('eval', 'hl.config({ animations = { enabled = ' + value(animations)
                 + ' }, decoration = { shadow = { enabled = ' + value(shadows) + ' } } })')
    if result.strip() != 'ok': raise RuntimeError(result)


def set_enabled(enabled):
    with appearance.locked(): return set_enabled_locked(enabled)


def set_enabled_locked(enabled):
    previous = read_state()
    if bool(previous.get('enabled')) == enabled: return previous
    if enabled:
        selected = components()
        state = {'enabled': True, 'options': options(), 'restore': [],
                 'wallpaper_active': any(p[2] in ['swaybg', 'mpvpaper'] for p in selected),
                 'released_component_pss_mib': round(sum(p[3] for p in selected), 1),
                 'stopped_count': len(selected),
                 'available_before_mib': psutil.virtual_memory().available / 1048576}
        for process, arguments, name, memory in selected:
            if name == 'waybar': state['restore'].append(arguments)
        save(state)
        try:
            configure(False, False)
            for process, _, _, _ in selected:
                try: process.terminate()
                except psutil.NoSuchProcess: pass
            _, alive = psutil.wait_procs([p[0] for p in selected], timeout=2)
            for process in alive:
                try: process.kill()
                except psutil.NoSuchProcess: pass
            psutil.wait_procs(alive, timeout=2)
            state['available_after_mib'] = psutil.virtual_memory().available / 1048576
            save(state)
            return state
        except Exception:
            set_enabled_locked(False)
            raise
    else:
        original = previous.get('options', {})
        configure(original.get('animations:enabled', True), original.get('decoration:shadow:enabled', True))
        running = [tuple(p[1]) for p in components()]
        logfile = Path.home() / '.local/state/hyprland-g8d/game-mode.log'
        logfile.parent.mkdir(parents=True, exist_ok=True)
        with logfile.open('a') as log:
            for arguments in previous.get('restore', []):
                if Path(arguments[0]).name in ['swaybg', 'mpvpaper']: continue
                if tuple(arguments) not in running:
                    subprocess.Popen(arguments, stdout=log, stderr=log, start_new_session=True)
        if previous.get('wallpaper_active', any(Path(a[0]).name in ['swaybg', 'mpvpaper'] for a in previous.get('restore', []))):
            appearance.start(force=True)
        state = {**previous, 'enabled': False}
        save(state)
        return state
