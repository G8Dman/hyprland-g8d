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
        if not path.is_file():continue
        assert path.name not in {'calendar.json','appearance.json','monitors.lua','state.conf'},path
        assert 'backups' not in path.parts and 'calendar_vendor' not in path.parts,path
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
print('PASS: Python/shell/JSON syntax, release privacy audit, portable monitor defaults')
