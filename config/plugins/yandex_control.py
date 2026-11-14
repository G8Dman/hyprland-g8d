"""Hyprland helpers for the optional official desktop application.

Playback and collection selection live in yamusic_backend, without DevTools.
"""
import json
import subprocess


def windows():
    return [w for w in json.loads(subprocess.check_output(['hyprctl', '-j', 'clients'], timeout=2))
            if w.get('class', '').lower() == 'yandexmusic']


def lua(code):
    result = subprocess.run(['hyprctl', 'eval', code], capture_output=True, text=True, timeout=3)
    if result.returncode or result.stdout.strip() not in ('', 'ok'):
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'Ошибка управления окном')
