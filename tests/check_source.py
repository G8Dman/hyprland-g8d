#!/usr/bin/env python3
"""Release audit: personal state must never enter a distributable artifact."""
import ast
import json
from pathlib import Path
import re
import subprocess

root=Path(__file__).resolve().parent.parent
for path in root.rglob('*.py'):
    if '.git' in path.parts:continue
    ast.parse(path.read_text(),filename=str(path))
for path in [root/'install.sh',root/'bootstrap.sh',root/'uninstall.sh',*list((root/'scripts').glob('*.sh')),*list((root/'bin').iterdir()),root/'config/actions',root/'config/autostart']:
    subprocess.run(['bash','-n',str(path)],check=True)
for path in (root/'config').rglob('*.json'):json.loads(path.read_text())
for base in [root/'config',root/'extras']:
    for path in base.rglob('*'):
        if not path.is_file() or '__pycache__' in path.parts:continue
        assert path.name not in {'calendar.json','appearance.json','monitors.lua','state.conf','branding.json','shortcuts.json','shortcuts.lua'},path
        assert 'backups' not in path.parts and 'calendar_vendor' not in path.parts,path
        if path.suffix == '.ttf':
            assert path.is_relative_to(root/'config/themes/nothing/fonts'), path
            assert path.read_bytes()[:4] == b'\x00\x01\x00\x00', path
            assert (path.parent/'OFL.txt').is_file(), path
            continue
        if path.suffix in {'.png','.svg'}:continue
        text=path.read_text()
        assert not re.search(r'/home/[\w.-]+',text),path
        assert not re.search(r'\bgh[pousr]_[A-Za-z0-9]{24,}',text),path
        assert not re.search(r'private-[a-f0-9]{24,}',text),path
        assert not re.search(r'\b192\.168\.\d+\.\d+',text),path
        assert not re.search(r'(?i)Bearer\s+[A-Za-z0-9._-]{24,}',text),path
lua=(root/'config/hyprland.lua').read_text()
assert 'HDMI-A-1' not in lua and 'eDP-1' not in lua
assert 'preferred' in lua and 'monitors.lua' in lua
assert (root/'VERSION').read_text()==(root/'config/VERSION').read_text()
assert (root/'VERSION').read_text().strip() in (root/'bootstrap.sh').read_text()
for name in ['quick_settings.py','quick-settings.css','settings-material.css','shortcuts.py','shortcuts_ui.py',
             'ui_themes.py','nothing.css','dashboard-material.css','music_view.py','screenshot.py']:
    assert (root/'config/plugins'/name).is_file(),name
for theme in ['appearance-templates','themes/clear']:
    assert (root/'config'/theme/'plugins/settings.css').is_file(),theme
print('PASS: Python/shell/JSON syntax, release privacy audit, portable monitor defaults')
