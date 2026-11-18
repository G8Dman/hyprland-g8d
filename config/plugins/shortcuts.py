#!/usr/bin/env python3
"""Persistent user shortcuts and their launcher; commands never enter generated Lua."""
import ctypes
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
MODS = {'SUPER':64, 'CTRL':4, 'ALT':8, 'SHIFT':1}
ALIASES = {'WIN':'SUPER','CONTROL':'CTRL','ESC':'Escape','ENTER':'Return','SPACE':'space'}
PREFIX = 'g8d-custom:'
STANDARD_PREFIX = 'g8d-standard:'
CATALOG = ROOT / 'standard-shortcuts.json'


def normalize(value):
    parts = [p.strip() for p in value.split('+')]
    if not parts or any(not p for p in parts):
        raise ValueError('Укажи сочетание, например SUPER + CTRL + K.')
    key = ALIASES.get(parts[-1].upper(), parts[-1])
    mods = [ALIASES.get(p.upper(),p.upper()) for p in parts[:-1]]
    if any(p not in MODS for p in mods) or len(set(mods)) != len(mods):
        raise ValueError('Модификаторы: SUPER, CTRL, ALT, SHIFT.')
    mouse = bool(re.fullmatch(r'mouse:(27[2-9]|28[0-9])|mouse_up|mouse_down', key))
    if (not mouse and not re.fullmatch(r'[A-Za-z0-9_]+', key)) or key.upper() in MODS:
        raise ValueError('Укажи одну клавишу после модификаторов.')
    if mouse:
        return ' + '.join([m for m in MODS if m in mods]+[key])
    lib = ctypes.CDLL('libxkbcommon.so.0')
    lib.xkb_keysym_from_name.argtypes = [ctypes.c_char_p,ctypes.c_int]
    lib.xkb_keysym_from_name.restype = ctypes.c_uint
    sym = lib.xkb_keysym_from_name(key.encode(),1)
    if not sym: raise ValueError('Неизвестная клавиша: '+key)
    lib.xkb_keysym_get_name.argtypes = [ctypes.c_uint,ctypes.c_char_p,ctypes.c_size_t]
    buf = ctypes.create_string_buffer(128)
    lib.xkb_keysym_get_name(sym,buf,len(buf))
    key=buf.value.decode()
    if len(key)==1: key=key.upper()
    if not any(m in mods for m in ('SUPER','CTRL','ALT')) and not re.fullmatch(r'F\d+|XF86\w+|Print|Pause',key):
        raise ValueError('Добавь SUPER, CTRL или ALT, чтобы сочетание не мешало печатать.')
    return ' + '.join([m for m in MODS if m in mods]+[key])


def signature(combo):
    parts=normalize(combo).split(' + ')
    return sum(MODS[m] for m in parts[:-1]),parts[-1].casefold()


def load():
    try: data=json.loads((ROOT/'shortcuts.json').read_text())
    except FileNotFoundError: return []
    if not isinstance(data,list): raise ValueError('Повреждён файл shortcuts.json: ожидается список.')
    return data


def standards():
    return json.loads(CATALOG.read_text())


def effective(items=None):
    items=load() if items is None else items
    overrides={i['builtin']:i for i in items if i.get('builtin')}
    return [{**base, **overrides.get(base['builtin'],{}), 'default_combo':base['combo'],
             'default_name':base['name']} for base in standards()] + [i for i in items if not i.get('builtin')]


def validate(items, include_defaults=True):
    catalog={i['builtin']:i for i in standards()}
    ids=set(); keys=set()
    for item in items:
        if not re.fullmatch(r'[0-9a-f]{32}',item.get('id','')) or item['id'] in ids:
            raise ValueError('Некорректный идентификатор сочетания.')
        ids.add(item['id'])
        if not item.get('name','').strip(): raise ValueError('Укажи название.')
        item['combo']=normalize(item.get('combo',''))
        key=signature(item['combo'])
        if key in keys: raise ValueError('Это сочетание уже используется в списке.')
        keys.add(key)
        builtin=item.get('builtin')
        if builtin:
            if builtin not in catalog or item['id']!=catalog[builtin]['id']:
                raise ValueError('Неизвестное стандартное действие.')
            if item.get('kind')=='standard' and builtin in ('drag-window','resize-window') and 'mouse:' not in item['combo']:
                raise ValueError('Для перетаскивания и размера окна выбери кнопку мыши, например SUPER + mouse:272.')
            if item.get('kind')=='standard' and builtin in ('switch-next','switch-prev') and not any(m+' + ' in item['combo'] for m in ('CTRL','ALT','SUPER')):
                raise ValueError('Для переключения окон нужен CTRL, ALT или SUPER: отпускание завершает выбор.')
        if item.get('kind')=='standard' and builtin:
            pass
        elif item.get('kind')=='app':
            if not item.get('desktop_id'): raise ValueError('Выбери приложение.')
        elif item.get('kind')=='command':
            if not item.get('command','').strip() or '\0' in item['command']:
                raise ValueError('Введи команду.')
            if not isinstance(item.get('terminal'),bool): raise ValueError('Выбери режим терминала.')
        else: raise ValueError('Неизвестное действие.')
    if include_defaults:
        assigned={}
        for item in effective(items):
            key=signature(item['combo'])
            if key in assigned:
                raise ValueError(item['combo']+' уже используется: '+assigned[key]+'.')
            assigned[key]=item['name']
    return items


def live_binds():
    result=subprocess.run(['hyprctl','-j','binds'],capture_output=True,text=True,timeout=5)
    if result.returncode: raise RuntimeError('Не удалось проверить занятые сочетания: '+result.stderr.strip())
    return json.loads(result.stdout)


def check_conflicts(items, binds):
    for item in effective(items):
        mask,key=signature(item['combo'])
        for bind in binds:
            if str(bind.get('description','')).startswith((PREFIX,STANDARD_PREFIX)): continue
            # An ignore_mods binding also receives the key with these modifiers.
            if (bind.get('modmask')==mask or bind.get('ignore_mods',False)) and str(bind.get('key','')).casefold()==key:
                # Non-consuming switcher observers do not reserve the shortcut.
                if bind.get('non_consuming',False): continue
                raise ValueError(item['combo']+' уже занято оболочкой или другим приложением.')


def lua_string(value):
    # JSON and Lua share this string subset; Unicode stays literal.
    return json.dumps(value,ensure_ascii=False)


def render(items):
    lines=['-- Generated by settings. Edit shortcuts.json through the shortcut editor.', 'g8d_shortcut_overrides = {}']
    for item in validate(items):
        if item.get('builtin'):
            fields='combo = '+lua_string(item['combo'])
            if item['kind']!='standard':
                command=shlex.join([sys.executable,str(ROOT/'plugins/shortcuts.py'),'run',item['id']])
                fields+=', command = '+lua_string(command)
            lines.append('g8d_shortcut_overrides['+lua_string(item['builtin'])+'] = { '+fields+' }')
            continue
        command=shlex.join([sys.executable,str(ROOT/'plugins/shortcuts.py'),'run',item['id']])
        lines.append('hl.bind('+lua_string(item['combo'])+', hl.dsp.exec_cmd('+lua_string(command)+'), { description = '+lua_string(PREFIX+item['id'])+(', mouse = true' if 'mouse:' in item['combo'] else '')+' })')
    return '\n'.join(lines)+'\n'


def atomic(path,data):
    fd,name=tempfile.mkstemp(prefix=path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as out: out.write(data)
        os.replace(name,path)
    finally:
        if os.path.exists(name): os.unlink(name)


def save(items):
    items=validate(items)
    check_conflicts(items,live_binds())
    paths=[ROOT/'shortcuts.json',ROOT/'shortcuts.lua']
    previous=[p.read_text() if p.exists() else None for p in paths]
    try:
        atomic(paths[0],json.dumps(items,ensure_ascii=False,indent=2)+'\n')
        atomic(paths[1],render(items))
        reload_config()
    except Exception:
        for path,content in zip(paths,previous):
            if content is None: path.unlink(missing_ok=True)
            else: atomic(path,content)
        try: reload_config()
        except Exception: pass
        raise


def reload_config():
    result=subprocess.run(['hyprctl','reload','config-only'],capture_output=True,text=True,timeout=8)
    if result.returncode: raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    result=subprocess.run(['hyprctl','configerrors'],capture_output=True,text=True,timeout=5)
    if result.returncode or result.stdout.strip():
        raise RuntimeError('Hyprland не принял настройки: '+(result.stdout or result.stderr).strip())


def execute(item):
    validate([item], include_defaults=False)
    if item['kind']=='app':
        import gi
        from gi.repository import Gio
        app=Gio.DesktopAppInfo.new(item['desktop_id'])
        if app is None: raise RuntimeError('Приложение удалено: '+item['desktop_id'])
        if not app.launch([],None): raise RuntimeError('Не удалось открыть приложение.')
    else:
        args=['/bin/sh','-lc',item['command']]
        if item['terminal']:
            args=['kitty','--config',str(ROOT/'kitty.conf'),'--hold']+args
        subprocess.Popen(args,start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


def main():
    if len(sys.argv)!=3 or sys.argv[1]!='run': raise ValueError('Usage: shortcuts.py run ID')
    item=next((i for i in load() if i['id']==sys.argv[2]),None)
    if item is None: raise ValueError('Сочетание удалено.')
    execute(item)


if __name__=='__main__':
    try: main()
    except Exception as exc:
        subprocess.run(['notify-send','-u','critical','Горячие клавиши',str(exc)],check=False)
        raise SystemExit(1)
