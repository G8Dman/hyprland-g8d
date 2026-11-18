"""Persistent display label, separate from the immutable session/config names."""
import json
import os
from pathlib import Path
import re
import signal
import socket
import psutil

ROOT=Path(__file__).resolve().parent.parent

def read(root=ROOT):
    try:return validate(json.loads((root/'branding.json').read_text()).get('label','g8d'))
    except (OSError,ValueError,TypeError):return 'g8d'

def validate(value):
    value=value.strip()
    if not 1<=len(value)<=32 or not all(c.isalnum() or c in ' -_.·' for c in value):
        raise ValueError('От 1 до 32 символов: буквы, цифры, пробелы, - _ . ·')
    return value

def atomic(path,text):
    temporary=path.with_suffix(path.suffix+'.tmp');temporary.write_text(text);temporary.replace(path)

def apply(root=ROOT,live=True):
    label=read(root)
    waybar=root/'waybar.json'
    if waybar.exists():
        data=json.loads(waybar.read_text());data['custom/brand']['format']=label
        atomic(waybar,json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    lock=root/'hyprlock.conf'
    if lock.exists():
        atomic(lock,re.sub(r'(?m)^(\s*text\s*=\s*).*/ (graphite|clear)\s*$',lambda m:m[1]+label+' / '+m[2],lock.read_text()))
    if live:
        runtime=Path(os.environ.get('XDG_RUNTIME_DIR','/tmp'))
        address=runtime/f"g8d-panels-{os.getuid()}-{os.environ.get('HYPRLAND_INSTANCE_SIGNATURE','default')}.sock"
        try:
            with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as connection:connection.sendto(b'{"branding":"reload"}',str(address))
        except OSError:pass
        for process in psutil.process_iter(['name','cmdline']):
            try:
                if process.info['name']=='waybar' and str(waybar) in (process.info['cmdline'] or []) and process.environ().get('HYPRLAND_INSTANCE_SIGNATURE')==os.environ.get('HYPRLAND_INSTANCE_SIGNATURE'):
                    process.send_signal(signal.SIGUSR2)
            except psutil.Error:pass
    return label

def save(value,root=ROOT,live=True):
    label=validate(value)
    atomic(root/'branding.json',json.dumps({'label':label},ensure_ascii=False)+'\n')
    return apply(root,live)
