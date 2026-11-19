#!/usr/bin/env python3
"""Check theme round trips, preserved preferences and failure rollback off-screen."""
import json
from pathlib import Path
import shutil
import tempfile
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'config/plugins'))

import appearance
import branding


source = (Path(__file__).resolve().parents[2] / 'config')
with tempfile.TemporaryDirectory(prefix='g8d-themes-') as directory:
    root = Path(directory)
    for folder in ['appearance-templates', 'themes']:
        shutil.copytree(source / folder, root / folder)
    state = {'wallpaper': '/keep/image.png', 'wallpapers': {'TEST': '/keep/movie.mp4'},
             'accent': '#6faede', 'extra': {'keep': True}}
    (root / 'appearance.json').write_text(json.dumps(state))
    (root / 'branding.json').write_text('{"label":"Моя оболочка"}')
    (root / 'waybar.json').write_bytes((source / 'waybar.json').read_bytes())
    with patch.object(appearance, 'ROOT', root), patch.object(appearance, 'SELECTION', root / 'appearance.json'):
        assert appearance.theme_name() == 'graphite', 'Legacy selection must default to Graphite'
        appearance.change(theme='graphite', live=False)
        files = [*appearance.THEME_FILES, 'accent.lua', 'waybar.json', 'appearance.json']
        snapshot = lambda: {name: (root / name).read_bytes() for name in files}
        graphite = snapshot()
        appearance.change(theme='clear', mode='light', live=False)
        assert 'background: transparent' in (root / 'waybar.css').read_text()
        assert 'Моя оболочка / clear' in (root / 'hyprlock.conf').read_text()
        branding.save('Другое имя', root, live=False)
        assert 'Другое имя / clear' in (root / 'hyprlock.conf').read_text()
        branding.save('Моя оболочка', root, live=False)
        for key, value in state.items(): assert appearance.read_selection()[key] == value, key
        appearance.change(accent='#e7a2ba', live=False)
        assert appearance.theme_name() == 'clear'
        assert appearance.read_selection()['accent'] == '#e7a2ba'
        assert '#e7a2ba' not in (root / 'plugins/settings.css').read_text(), 'Light accents need darker ink'
        appearance.change(accent=state['accent'], theme='graphite', mode='dark', live=False)
        assert snapshot() == graphite, 'Graphite must be restored without cumulative substitutions'
        before = snapshot()
        for kwargs in [{'theme': '../bad'}, {'accent': 'invalid'}]:
            try: appearance.change(live=False, **kwargs)
            except ValueError: pass
            else: raise AssertionError('Invalid input accepted')
            assert snapshot() == before
        with patch.object(appearance, 'reload_appearance', side_effect=RuntimeError('reload failed')):
            try: appearance.change(theme='clear')
            except RuntimeError: pass
            else: raise AssertionError('Reload error ignored')
        assert snapshot() == before, 'Reload failure must restore files and selection'
        (root / 'themes/clear/kitty.conf').unlink()
        try: appearance.change(theme='clear', mode='light', live=False)
        except FileNotFoundError: pass
        else: raise AssertionError('Incomplete theme accepted')
        assert snapshot() == before, 'Incomplete theme must leave the old theme intact'
print('PASS: legacy state, theme round trip, wallpaper/accent/branding preservation, validation and rollback')
