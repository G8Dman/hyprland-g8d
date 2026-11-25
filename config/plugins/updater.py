#!/usr/bin/env python3
"""Update g8d from a published GitHub release, without sudo or package upgrades."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import urllib.request

REPO='G8Dman/hyprland-g8d'
ROOT=Path(__file__).resolve().parent.parent
API='https://api.github.com/repos/'+REPO+'/releases?per_page=100'

def version(tag):
    match=re.fullmatch(r'v(\d+)\.(\d+)\.(\d+)(?:-alpha\.(\d+))?',tag)
    if not match:return None
    major,minor,patch,alpha=match.groups()
    return int(major),int(minor),int(patch),int(alpha) if alpha else 1000000000

def latest(releases):
    eligible=[r for r in releases if not r.get('draft') and version(r.get('tag_name',''))]
    if not eligible:raise RuntimeError('Опубликованные релизы не найдены')
    return max(eligible,key=lambda r:version(r['tag_name']))

def fetch(url,path=None,limit=16*1024*1024,timeout=45):
    request=urllib.request.Request(url,headers={'User-Agent':'hyprland-g8d-updater','Accept':'application/vnd.github+json' if url==API else '*/*'})
    with urllib.request.urlopen(request,timeout=timeout) as response:
        data=response.read(limit+1)
    if len(data)>limit:raise RuntimeError('Ответ сервера превышает допустимый размер')
    if path:path.write_bytes(data)
    return data

def release_assets(release):
    tag = release['tag_name']
    base = f'https://github.com/{REPO}/releases/download/{tag}/'
    assets = {item['name']: item['browser_download_url'] for item in release.get('assets', [])}
    for name in (f'hyprland-g8d-{tag}.tar.gz', 'SHA256SUMS'):
        if not assets.get(name, '').startswith(base):
            raise RuntimeError('Релиз ещё не готов: отсутствует архив или контрольная сумма')
    return assets

def unpack(archive,destination):
    with tarfile.open(archive,'r:gz') as source:
        members=source.getmembers()
        if len(members)>10000 or sum(m.size for m in members)>128*1024*1024:raise RuntimeError('Архив слишком большой')
        for member in members:
            if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                raise RuntimeError('Недопустимый объект в архиве')
            resolved=(destination/member.name).resolve()
            if not resolved.is_relative_to(destination.resolve()):raise RuntimeError('Недопустимый путь в архиве')
        source.extractall(destination,filter='data')
    entries=list(destination.iterdir())
    if len(entries)!=1 or not (entries[0]/'install.sh').is_file():raise RuntimeError('Некорректная структура релиза')
    return entries[0]

def update():
    state=Path.home()/'.local/state/hyprland-g8d';state.mkdir(parents=True,exist_ok=True)
    with (state/'update.lock').open('w') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('Обновление уже выполняется')
        print('Проверяю релизы hyprland-g8d на GitHub…',flush=True)
        release=latest(json.loads(fetch(API)))
        tag=release['tag_name']
        current=(ROOT/'VERSION').read_text().strip() if (ROOT/'VERSION').exists() else ''
        if version(current) and version(tag)<=version(current):
            print('Установлена актуальная версия: '+current);return
        name='hyprland-g8d-'+tag+'.tar.gz'
        assets=release_assets(release)
        with tempfile.TemporaryDirectory(prefix='g8d-update-') as directory:
            work=Path(directory);archive=work/name
            checks=fetch(assets['SHA256SUMS'],limit=65536).decode()
            wanted=next((line.split()[0] for line in checks.splitlines() if len(line.split())==2 and line.split()[1]==name),None)
            if not wanted or not re.fullmatch('[0-9a-f]{64}',wanted):raise RuntimeError('Контрольная сумма не найдена')
            print('Скачиваю '+tag+'…',flush=True);fetch(assets[name],archive)
            if hashlib.sha256(archive.read_bytes()).hexdigest()!=wanted:raise RuntimeError('Контрольная сумма архива не совпадает')
            source=work/'source';source.mkdir();tree=unpack(archive,source)
            print('Сохраняю настройки и устанавливаю обновление…',flush=True)
            subprocess.run(['bash',str(tree/'install.sh'),'--no-packages','--no-session'],check=True)
        print('\nОбновление установлено: '+tag+'\nВыйди из сессии и выбери hyprland-g8d снова, чтобы применить все изменения.')

if __name__=='__main__':
    try:update()
    except Exception as exc:print('Обновление не выполнено: '+str(exc))
    try:input('\nНажми Enter, чтобы закрыть окно…')
    except EOFError:pass
