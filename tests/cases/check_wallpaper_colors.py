#!/usr/bin/env python3
"""Wallpaper classification, neutral accents, isolated profiles and transactional edits."""
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
with tempfile.TemporaryDirectory(prefix='g8d-wallpaper-colors-') as directory:
    root = Path(directory)
    for folder in ['appearance-templates', 'themes']: shutil.copytree(source/folder, root/folder)
    images = {}
    for name, color in {'black': (0,0,0), 'white': (255,255,255), 'gray': (70,70,70),
                        'red-dark': (100,20,20), 'red-light': (255,180,180)}.items():
        path = root/(name+'.png');Image.new('RGB',(96,96),color).save(path);images[name] = path
    with patch.object(a,'ROOT',root), patch.object(a,'SELECTION',root/'appearance.json'), patch.object(a,'CACHE',root/'cache'):
        for name, expected in [('black','graphite'),('white','clear'),('gray','graphite'),('red-dark','graphite'),('red-light','clear')]:
            result = a.analyze_wallpaper(images[name]);assert result['mode']==('light' if expected == 'clear' else 'dark'),(name,result)
        assert a.analyze_wallpaper(images['black'])['accent']=='#9ba7b3'
        assert a.analyze_wallpaper(images['white'])['accent']=='#587083'
        assert a.analyze_wallpaper(images['red-light'])==a.analyze_wallpaper(images['red-light'])
        a.atomic(a.SELECTION,json.dumps({'wallpaper':str(images['white']),'wallpapers':{'A':str(images['white']),'B':str(images['black'])},'accent':'#8bbfba','theme':'clear'}))
        a.change(accent='auto',output='A',live=False)
        assert a.read_selection()['wallpaper_colors'] and a.theme_name()=='clear'
        a.change(path=images['black'],output='B',live=False)
        assert a.theme_name()=='clear','Other monitor must not change the chosen source palette'
        a.change(path=images['black'],output='A',live=False)
        assert a.theme_name()=='clear' and a.theme_mode()=='dark'
        assert a.read_selection()['wallpapers']['B']==str(images['black'])
        a.change(path=images['white'],output='A',live=False)
        assert a.theme_name()=='clear'
        custom={'background':'#f3f6ff','surface':'#f9faff','control':'#e8eefa','text':'#1e2b43','muted':'#53627a','border':'#bcc8dc','selection':'#dbe6fb','bar_text':'#203040'}
        a.change(colors=custom,live=False)
        state=a.read_selection();assert not state['wallpaper_colors']
        assert a.theme_colors()['background']=='#f3f6ff'
        for name in ['plugins/style.css','plugins/settings.css','rofi.rasi','mako.conf','hyprlock.conf','kitty.conf']:
            content=(root/name).read_text();assert 'f3f6ff' in content or '243, 246, 255' in content,name
        assert '#203040' in (root/'waybar.css').read_text()
        assert '#bcc8dc' in (root/'plugins/style.css').read_text()
        a.change(theme='graphite',live=False)
        assert a.theme_colors()['background']==a.default_colors('graphite', 'light')['background']
        a.change(theme='clear',live=False)
        assert a.theme_colors()['background']=='#f3f6ff'
        a.change(auto=True,output='B',live=False);assert a.theme_name()=='clear' and a.theme_mode()=='dark'
        a.change(auto=True,output='A',live=False);assert a.theme_name()=='clear'
        assert a.theme_colors()['background']=='#f3f6ff','Auto mode must preserve custom profiles'
        files=[a.SELECTION,*[root/n for n in a.THEME_FILES],root/'accent.lua']
        snapshot=lambda:{str(p):p.read_bytes() for p in files}
        before=snapshot()
        for colors in [{'text':'#ffffff'},{'background':'bad'},{'typo':'#123456'}]:
            try:a.change(colors=colors,live=False)
            except ValueError:pass
            else:raise AssertionError('Invalid colors accepted')
            assert snapshot()==before,'Rejected edit changed state or files'
        with patch.object(a,'reload_appearance',side_effect=RuntimeError('reload failed')):
            try:a.change(accent='#446688',colors={'border':'#aabbcc'})
            except RuntimeError:pass
            else:raise AssertionError('Reload failure ignored')
        assert snapshot()==before,'Failed transaction did not restore the palette'
        a.change(reset_colors=True,live=False)
        assert a.theme_colors()==a.DEFAULT_COLORS['clear']
        assert not a.read_selection()['wallpaper_colors']
print('PASS: brightness/neutral/color analysis, stable results, selected monitor, auto wallpaper changes, manual overrides, independent profiles, validation, rollback, reset')
