#!/usr/bin/env python3
"""Read only compositor keyboard LED state; never read password input."""
import json
import subprocess

try:
    keyboards = json.loads(subprocess.check_output(
        ['hyprctl', '-j', 'devices'], timeout=1, stderr=subprocess.DEVNULL))['keyboards']
    main = next((keyboard for keyboard in keyboards if keyboard.get('main')), None)
    enabled = main.get('capsLock', False) if main else any(k.get('capsLock', False) for k in keyboards)
    print('<span foreground="#e5b566"><b>Caps Lock: ВКЛ</b></span>' if enabled else 'Caps Lock: выкл')
except (OSError, ValueError, KeyError, subprocess.SubprocessError):
    print('Caps Lock: —')
