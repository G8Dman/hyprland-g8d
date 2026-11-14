"""Resolve extensions without reading a file; isolate unknown suffix associations."""
import hashlib
import os
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET
from gi.repository import Gio


def resolve(value):
    suffix = value.strip().lower()
    if suffix.startswith('*.'): suffix = suffix[2:]
    else: suffix = suffix.lstrip('.')
    if not suffix: return None
    if len(suffix) > 64 or not re.fullmatch(r'[\w+\-]+(?:\.[\w+\-]+)*', suffix):
        raise ValueError('Введи расширение без пути к файлу, например pdf, .mp4 или tar.gz.')
    mime, uncertain = Gio.content_type_guess('file.' + suffix, None)
    custom = uncertain or Gio.content_type_is_unknown(mime)
    if custom:
        mime = 'application/x-g8d-extension-' + hashlib.sha256(suffix.encode()).hexdigest()[:20]
    description = 'Файлы .' + suffix if custom else Gio.content_type_get_description(mime)
    current = Gio.AppInfo.get_default_for_type(mime, False)
    return {'extension':suffix, 'mime':mime, 'custom':custom, 'description':description, 'app':current}


def associate(info, app):
    package = None
    previous = None
    if info['custom']:
        mime_root = Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local/share')) / 'mime'
        packages = mime_root / 'packages'
        packages.mkdir(parents=True, exist_ok=True)
        package = packages / (info['mime'].split('/')[-1] + '.xml')
        previous = package.read_bytes() if package.exists() else None
        namespace = 'http://www.freedesktop.org/standards/shared-mime-info'
        ET.register_namespace('', namespace)
        root = ET.Element('{'+namespace+'}mime-info')
        kind = ET.SubElement(root, '{'+namespace+'}mime-type', {'type':info['mime']})
        ET.SubElement(kind, '{'+namespace+'}comment').text = info['description']
        ET.SubElement(kind, '{'+namespace+'}glob', {'pattern':'*.'+info['extension']})
        temporary = package.with_suffix('.xml.tmp')
        temporary.write_bytes(ET.tostring(root, encoding='utf-8', xml_declaration=True))
        temporary.replace(package)
    try:
        if package:
            subprocess.run(['update-mime-database', str(mime_root)], check=True, capture_output=True, timeout=15)
        if not app.set_as_default_for_type(info['mime']):
            raise RuntimeError('Не удалось сохранить приложение по умолчанию')
    except Exception:
        if package:
            if previous is None: package.unlink(missing_ok=True)
            else: package.write_bytes(previous)
            subprocess.run(['update-mime-database',str(mime_root)],capture_output=True,timeout=15)
        raise
