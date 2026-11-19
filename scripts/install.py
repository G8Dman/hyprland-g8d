#!/usr/bin/env python3
"""Install only g8d-owned paths. Never activate/restart a display manager."""
import argparse
from contextlib import ExitStack
import datetime
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parent.parent
LAUNCHERS = ('hyprland-g8d', 'g8d-settings')

def execute(args, **kwargs):
    subprocess.run([str(a) for a in args], check=True, **kwargs)


def keep_local_files(installed, stage):
    """Copy existing files that the release does not replace."""
    for source in installed.iterdir():
        destination = stage / source.name
        if source.name == '__pycache__':
            continue
        if destination.exists() or destination.is_symlink():
            if source.is_dir() and not source.is_symlink() and destination.is_dir() and not destination.is_symlink():
                keep_local_files(source, destination)
        elif source.is_dir() and not source.is_symlink():
            shutil.copytree(source, destination, symlinks=True, ignore=shutil.ignore_patterns('__pycache__'))
        else:
            shutil.copy2(source, destination, follow_symlinks=False)


def remove_path(path):
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def restore_path(path, previous):
    remove_path(path)
    if previous is not None:
        previous.replace(path)


def preserve_path(path, temporary, rollback):
    if path.exists() or path.is_symlink():
        previous = Path(temporary.enter_context(tempfile.TemporaryDirectory(prefix='.g8d-previous-', dir=path.parent))) / path.name
        path.replace(previous)
    else:
        previous = None
    rollback.callback(restore_path, path, previous)
    return previous


def assemble_config(stage, config, python):
    shutil.copytree(REPO / 'config', stage, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__'))
    if config.exists():
        keep_local_files(config, stage)
    for name in ('actions', 'autostart'):
        (stage / name).chmod(0o755)
    state = stage / 'appearance.json'
    accent = json.loads(state.read_text()).get('accent', '#8bbfba') if state.exists() else '#8bbfba'
    environment = {**os.environ, 'G8D_APPEARANCE_ROOT': str(stage), 'G8D_ACCENT': accent}
    execute([python, '-c', "import os,sys;sys.path.insert(0,os.environ['G8D_APPEARANCE_ROOT']+'/plugins');import appearance;appearance.apply_accent(os.environ['G8D_ACCENT'],live=False)"], env=environment)
    if (stage / 'shortcuts.json').exists():
        execute([python, '-c',
                 "import os,sys;from pathlib import Path;root=Path(os.environ['G8D_APPEARANCE_ROOT']);sys.path.insert(0,str(root/'plugins'));import shortcuts;shortcuts.atomic(root/'shortcuts.lua',shortcuts.render(shortcuts.load(),install_root=Path(sys.argv[1])))",
                 config], env=environment)
    try:
        execute(['Hyprland', '--verify-config', '--config', stage / 'hyprland.lua'],
                env={**os.environ, 'G8D_CONFIG_DIR': str(stage)}, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True)
    except subprocess.CalledProcessError as exc:
        if exc.output:
            print(exc.output, file=sys.stderr, end='')
        raise SystemExit('Hyprland rejected the assembled Lua config. Installed config was not changed.') from exc
    return environment


def desktop_entry(launcher):
    executable = str(launcher).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$')
    return ('[Desktop Entry]\nType=Application\nName=Настройки g8d\nName[en]=g8d Settings\n'
            'Comment=Wi-Fi, Bluetooth, экраны и приложения по умолчанию\nExec="' + executable +
            '"\nIcon=preferences-system\nTerminal=false\nCategories=Settings;DesktopSettings;\n'
            'Keywords=g8d;settings;настройки;экран;wifi;bluetooth;\nStartupWMClass=g8d-settings\n')


def install(target, config, venv, register_session):
    backup = None
    launchers = target / '.local/bin'
    desktop = target / '.local/share/applications/g8d-settings.desktop'
    fonts = target / '.local/share/fonts/g8d-nothing'
    python = venv / 'bin/python'
    with ExitStack() as temporary, ExitStack() as rollback:
        # Keep relative links valid and publish with a same-filesystem rename.
        stage = Path(temporary.enter_context(tempfile.TemporaryDirectory(prefix='.g8d-stage-', dir=config.parent)))
        if not (venv.exists() or venv.is_symlink()):
            rollback.callback(remove_path, venv)
        execute([sys.executable, '-m', 'venv', '--system-site-packages', venv])
        execute([python, '-m', 'pip', 'install', '--disable-pip-version-check', '-r', REPO / 'requirements.txt'])
        execute([python, '-c', "import gi,cairo,psutil,PIL,icalendar,recurring_ical_events; gi.require_version('Gtk','3.0'); gi.require_version('GtkLayerShell','0.1'); from gi.repository import Gtk,GtkLayerShell"])
        environment = assemble_config(stage, config, python)

        if config.exists():
            backup = target / '.local/state/hyprland-g8d/install-backups' / datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
            backup.mkdir(parents=True, mode=0o700)
            shutil.copytree(config, backup / 'config', symlinks=True)
            for path in [*(launchers / name for name in LAUNCHERS), desktop]:
                if path.exists() or path.is_symlink():
                    shutil.copy2(path, backup / path.name, follow_symlinks=False)

        previous_fonts = preserve_path(fonts, temporary, rollback)
        if previous_fonts is not None:
            shutil.copytree(previous_fonts, fonts)
        # The settings updater skips packages, so install the bundled Nothing fonts locally.
        execute([python, '-c',
                 "import os,sys;root=os.environ['G8D_APPEARANCE_ROOT'];sys.path.insert(0,root+'/plugins');import ui_themes;ui_themes.ensure_fonts(root,sys.argv[1])",
                 target], env=environment)

        launchers.mkdir(parents=True, exist_ok=True)
        for name in LAUNCHERS:
            destination = launchers / name
            prepared = Path(temporary.enter_context(tempfile.TemporaryDirectory(prefix='.g8d-stage-', dir=launchers))) / name
            shutil.copy2(REPO / 'bin' / name, prepared)
            prepared.chmod(0o755)
            preserve_path(destination, temporary, rollback)
            prepared.replace(destination)
        desktop.parent.mkdir(parents=True, exist_ok=True)
        prepared = Path(temporary.enter_context(tempfile.TemporaryDirectory(prefix='.g8d-stage-', dir=desktop.parent))) / desktop.name
        prepared.write_text(desktop_entry(launchers / 'g8d-settings'))
        preserve_path(desktop, temporary, rollback)
        prepared.replace(desktop)

        preserve_path(config, temporary, rollback)
        stage.replace(config)
        if register_session:
            execute(['sudo', 'bash', REPO / 'scripts/install-session.sh'])
        rollback.pop_all()

    if shutil.which('update-desktop-database'):
        try:
            execute(['update-desktop-database', desktop.parent])
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f'Could not refresh the desktop application index: {exc}', file=sys.stderr)
    return backup


def main():
    parser=argparse.ArgumentParser(description='Install hyprland-g8d (experimental Arch/CachyOS session).')
    parser.add_argument('--dry-run',action='store_true',help='Show planned paths, do not change anything')
    parser.add_argument('--no-packages',action='store_true',help='Dependencies are already installed')
    parser.add_argument('--no-session',action='store_true',help='Skip system-wide session registration')
    parser.add_argument('--target-home',type=Path,default=Path.home(),help='Staging/test home; requires --no-packages --no-session')
    args=parser.parse_args()
    target=args.target_home.expanduser().resolve()
    config=target/'.config/hyprland-g8d'
    share=target/'.local/share/hyprland-g8d'
    packages=[p for p in (REPO/'packages.txt').read_text().splitlines() if p and not p.startswith('#')]
    if target!=Path.home().resolve() and not (args.no_packages and args.no_session):
        parser.error('--target-home requires --no-packages --no-session')
    if args.dry_run:
        print(json.dumps({'config':str(config),'launchers':str(target/'.local/bin'),'session':'skipped' if args.no_session else '/usr/share/wayland-sessions/hyprland-g8d.desktop','packages':[] if args.no_packages else packages,'preserved':['~/.config/hypr','existing sessions','display-manager.service','account credentials']},ensure_ascii=False,indent=2))
        return
    if os.geteuid()==0:
        parser.error('Run as your regular user, without sudo. Root is requested only for packages/session entry.')
    if not args.no_packages:
        if not shutil.which('pacman'):parser.error('Automatic packages are supported only on Arch/CachyOS.')
        execute(['sudo','pacman','-S','--needed',*packages])
    for name in ['Hyprland','start-hyprland','waybar','rofi','kitty','hyprlock','hypridle','swaybg','mpvpaper']:
        if not shutil.which(name):parser.error('Missing dependency: '+name)
    config.parent.mkdir(parents=True, exist_ok=True)
    share.mkdir(parents=True, exist_ok=True)
    # Serialise manual installs and updates targeting the same home.
    lock = os.open(config.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        backup = install(target, config, share / 'venv', not args.no_session)
    finally:
        os.close(lock)
    print('\nInstalled hyprland-g8d (ALPHA). Log out and choose hyprland-g8d at your login screen.')
    print('Settings: Win+Ctrl+S. Help: Win+F1. Existing ~/.config/hypr was not changed.')
    if backup:print('Previous g8d config backup:',backup)
    print('The current desktop and display manager were not restarted.')

if __name__=='__main__':main()
