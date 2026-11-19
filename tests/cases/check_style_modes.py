#!/usr/bin/env python3
"""Exercise four appearance variants, migration, lock backgrounds and rollback."""
import json
from pathlib import Path
import shutil
import tempfile
from unittest.mock import patch
from PIL import Image
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'config/plugins'))

import appearance as a

source = (Path(__file__).resolve().parents[2] / 'config')
with tempfile.TemporaryDirectory(prefix='g8d-style-modes-') as directory:
    root = Path(directory)
    for name in ['appearance-templates', 'themes']: shutil.copytree(source/name, root/name)
    wallpaper = root/'bright фон.png'
    Image.new('RGB', (100, 100), 'white').save(wallpaper)
    with patch.object(a, 'ROOT', root), patch.object(a, 'SELECTION', root/'appearance.json'), patch.object(a, 'CACHE', root/'cache'):
        for legacy, mode in [('clear', 'light'), ('graphite', 'dark')]:
            a.atomic(a.SELECTION, json.dumps({'theme': legacy}))
            assert a.theme_mode() == mode
        for theme in a.THEMES:
            for mode in a.MODES:
                a.change(theme=theme, mode=mode, lock_background=str(wallpaper), live=False)
                assert a.theme_name() == theme and a.theme_mode() == mode
                palette = a.theme_colors()
                assert a.contrast(palette['text'], palette['surface']) >= 4.5
                css = (root/'plugins/settings.css').read_text()
                assert 'md_surface ' + palette['background'] in css
                lock = (root/'hyprlock.conf').read_text()
                assert 'path = ' + str(wallpaper) in lock
                assert 'shape {' in lock and 'zindex = -2' in lock and 'zindex = -1' in lock
                assert palette['surface'][1:]+'eb' in lock
                a.change(colors={'border': '#789abc'}, live=False)
                assert a.theme_colors()['border'] == '#789abc'
                a.change(reset_colors=True, live=False)
                assert a.theme_colors()['border'] != '#789abc'
        # Auto changes brightness and accent; changing style keeps auto enabled.
        a.change(theme='graphite', path=wallpaper, auto=True, live=False)
        assert a.theme_name() == 'graphite' and a.theme_mode() == 'light'
        a.change(theme='clear', live=False)
        assert a.read_selection()['wallpaper_colors']
        a.change(mode='dark', colors={'border': '#abcdef'}, live=False)
        a.change(mode='light', live=False)
        assert a.theme_colors()['border'] != '#abcdef'
        a.change(mode='dark', live=False)
        assert a.theme_colors()['border'] == '#abcdef'
        files = [a.SELECTION, *[root/n for n in a.THEME_FILES], root/'accent.lua']
        snapshot = lambda: {str(p): p.read_bytes() for p in files}
        before = snapshot()
        for kwargs in [{'mode':'bad'}, {'lock_background':'/missing.png'}, {'lock_background':str(source/'plugins/settings.py')}]:
            try: a.change(live=False, **kwargs)
            except ValueError: pass
            else: raise AssertionError('Invalid selection accepted')
            assert snapshot() == before
        with patch.object(a, 'reload_appearance', side_effect=RuntimeError('unavailable')):
            try: a.change(lock_background='')
            except RuntimeError: pass
            else: raise AssertionError('Reload error ignored')
        assert snapshot() == before
        a.change(lock_background='', live=False)
        assert a.read_selection()['lock_background'] == ''
print('PASS: four variants, legacy migration, independent palettes, style-preserving auto, lock image/reset and transactional rollback')
