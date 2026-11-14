#!/usr/bin/env python3
"""Install only g8d-owned paths. Never activate/restart a display manager."""
import argparse
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parent.parent

def execute(args, **kwargs):
    subprocess.run([str(a) for a in args], check=True, **kwargs)

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
    backup=None
    if config.exists():
        backup=target/'.local/state/hyprland-g8d/install-backups'/datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        backup.mkdir(parents=True,mode=0o700)
        shutil.copytree(config,backup/'config',symlinks=True)
        for name in ['hyprland-g8d','g8d-settings']:
            path=target/'.local/bin'/name
            if path.exists():shutil.copy2(path,backup/name)
    # Prepare Python before touching the currently installed configuration.
    share.mkdir(parents=True,exist_ok=True)
    venv=share/'venv'
    execute([sys.executable,'-m','venv','--system-site-packages',venv])
    execute([venv/'bin/python','-m','pip','install','--disable-pip-version-check','-r',REPO/'requirements.txt'])
    execute([venv/'bin/python','-c',"import gi,cairo,psutil,PIL,icalendar,recurring_ical_events; gi.require_version('Gtk','3.0'); gi.require_version('GtkLayerShell','0.1'); from gi.repository import Gtk,GtkLayerShell"])
    stage=share/'config-stage'
    if stage.exists():shutil.rmtree(stage)
    shutil.copytree(REPO/'config',stage)
    environment={**os.environ,'G8D_CONFIG_DIR':str(stage)}
    try:execute(['Hyprland','--verify-config','--config',stage/'hyprland.lua'],env=environment,stdout=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        shutil.rmtree(stage)
        raise SystemExit('Hyprland rejected the bundled Lua config. Requires compatible Lua API (tested 0.56/0.57). Installed config was not changed.')
    config.mkdir(parents=True,exist_ok=True)
    try:
        shutil.copytree(stage,config,dirs_exist_ok=True)
        launchers=target/'.local/bin';launchers.mkdir(parents=True,exist_ok=True)
        for name in ['hyprland-g8d','g8d-settings']:
            shutil.copy2(REPO/'bin'/name,launchers/name);(launchers/name).chmod(0o755)
        for name in ['actions','autostart']:(config/name).chmod(0o755)
        desktop=target/'.local/share/applications/g8d-settings.desktop';desktop.parent.mkdir(parents=True,exist_ok=True)
        executable=str(launchers/'g8d-settings').replace('\\','\\\\').replace('"','\\"').replace('`','\\`').replace('$','\\$')
        desktop.write_text('[Desktop Entry]\nType=Application\nName=Настройки g8d\nName[en]=g8d Settings\nComment=Wi-Fi, Bluetooth, экраны и приложения по умолчанию\nExec="'+executable+'"\nIcon=preferences-system\nTerminal=false\nCategories=Settings;DesktopSettings;\nKeywords=g8d;settings;настройки;экран;wifi;bluetooth;\nStartupWMClass=g8d-settings\n')
        # Reapply this user's saved accent, never copy another user's appearance.json.
        state=config/'appearance.json'
        accent=json.loads(state.read_text()).get('accent','#8bbfba') if state.exists() else '#8bbfba'
        environment={**os.environ,'G8D_APPEARANCE_ROOT':str(config),'G8D_ACCENT':accent}
        execute([venv/'bin/python','-c',"import os,sys;sys.path.insert(0,os.environ['G8D_APPEARANCE_ROOT']+'/plugins');import appearance;appearance.apply_accent(os.environ['G8D_ACCENT'],live=False)"],env=environment)
        if not args.no_session:execute(['sudo','bash',REPO/'scripts/install-session.sh'])
    except Exception:
        if backup:
            shutil.rmtree(config);shutil.copytree(backup/'config',config,symlinks=True)
            for name in ['hyprland-g8d','g8d-settings']:
                if (backup/name).exists():shutil.copy2(backup/name,target/'.local/bin'/name)
        raise
    finally:
        shutil.rmtree(stage,ignore_errors=True)
    if shutil.which('update-desktop-database'):execute(['update-desktop-database',target/'.local/share/applications'])
    print('\nInstalled hyprland-g8d (ALPHA). Log out and choose hyprland-g8d at your login screen.')
    print('Settings: Win+Ctrl+S. Help: Win+F1. Existing ~/.config/hypr was not changed.')
    if backup:print('Previous g8d config backup:',backup)
    print('The current desktop and display manager were not restarted.')

if __name__=='__main__':main()
