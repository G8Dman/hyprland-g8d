#!/usr/bin/env python3
"""Style/mode/bar independence, migration, profiles, wallpaper auto and rollback."""
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
with tempfile.TemporaryDirectory(prefix='g8d-ui-styles-') as directory:
    root=Path(directory)
    for folder in ['appearance-templates','themes']:shutil.copytree(source/folder,root/folder)
    wallpaper=root/'bright.png';Image.new('RGB',(32,32),'white').save(wallpaper)
    with patch.object(a,'ROOT',root),patch.object(a,'SELECTION',root/'appearance.json'),patch.object(a,'CACHE',root/'cache'):
        a.atomic(a.SELECTION,json.dumps({'theme':'clear','mode':'dark','wallpaper':str(wallpaper),'accent':'#50a0de'}))
        assert a.interface_style()=='material'
        assert set(a.TASKBAR_STYLES)=={'clear','graphite'}
        for bar in a.TASKBAR_STYLES:
            for mode in a.MODES:
                a.change(theme=bar,mode=mode,ui_style='material',live=False)
                material_bar=(root/'waybar.css').read_text()
                a.change(ui_style='nothing',live=False)
                assert (a.interface_style(),a.theme_name(),a.theme_mode())==('nothing',bar,mode)
                assert (root/'waybar.css').read_text()==material_bar,'UI style changed the taskbar design'
                colors=a.theme_colors()
                assert colors['background']==('#000000' if mode=='dark' else '#f5f5f5')
                assert a.contrast(colors['text'],colors['surface'])>=4.5
                assert 'Space Grotesk' in (root/'rofi.rasi').read_text()
                assert 'Doto' in (root/'hyprlock.conf').read_text()
                a.change(colors={'border':'#789abc'},live=False)
                a.change(ui_style='material',live=False)
                assert a.theme_colors()['border']!='#789abc'
                a.change(ui_style='nothing',live=False)
                assert a.theme_colors()['border']=='#789abc'
                a.change(reset_colors=True,live=False)
        a.change(theme='graphite',ui_style='nothing',auto=True,live=False)
        assert (a.interface_style(),a.theme_name(),a.theme_mode())==('nothing','graphite','light')
        assert a.read_selection()['wallpaper_colors']
        a.change(ui_style='material',live=False)
        assert a.read_selection()['wallpaper_colors']
        files=[a.SELECTION,*[root/n for n in a.THEME_FILES],root/'accent.lua']
        snapshot=lambda:{str(p):p.read_bytes() for p in files}
        before=snapshot()
        try:a.change(ui_style='invalid',live=False)
        except ValueError:pass
        else:raise AssertionError('Invalid style accepted')
        assert snapshot()==before
        with patch.object(a,'reload_appearance',side_effect=RuntimeError('reload failed')):
            try:a.change(ui_style='nothing')
            except RuntimeError:pass
            else:raise AssertionError('Failed reload ignored')
        assert snapshot()==before,'UI style transaction was not rolled back'
print('PASS: 8 interface/bar/mode combinations, unchanged taskbar, legacy Material default, isolated palettes, style-preserving auto, rollback')
