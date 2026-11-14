import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import types
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'config/plugins'))
with patch.dict(sys.modules,{'psutil':types.SimpleNamespace()}):import branding
import updater

class Features(unittest.TestCase):
 def test_label_persistence_and_theme_regeneration(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory)
   (root/'waybar.json').write_text(json.dumps({'custom/brand':{'format':'g8d'},'other':'preserve'}))
   (root/'hyprlock.conf').write_text('label {\n text = g8d / graphite\n}\n')
   branding.save('Мой стол',root,live=False)
   self.assertEqual(json.loads((root/'waybar.json').read_text())['custom/brand']['format'],'Мой стол')
   self.assertEqual(json.loads((root/'waybar.json').read_text())['other'],'preserve')
   self.assertIn('Мой стол / graphite',(root/'hyprlock.conf').read_text())
   (root/'hyprlock.conf').write_text(' text = g8d / graphite\n')
   branding.apply(root,live=False)
   self.assertIn('Мой стол / graphite',(root/'hyprlock.conf').read_text())
   for invalid in ['','hello\nworld','<b>hi</b>','$TIME','x'*33]:
    with self.assertRaises(ValueError):branding.save(invalid,root,live=False)
   self.assertEqual(branding.read(root),'Мой стол')
 def test_release_order_includes_alpha_and_ignores_drafts(self):
  releases=[{'tag_name':'v0.1.0-alpha.1'},{'tag_name':'v0.1.0-alpha.2'},{'tag_name':'v9.0.0','draft':True}]
  self.assertEqual(updater.latest(releases)['tag_name'],'v0.1.0-alpha.2')
  self.assertGreater(updater.version('v0.1.0'),updater.version('v0.1.0-alpha.99'))
 def test_tar_rejects_traversal_and_symlinks(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory)
   for name,link in [('../escape',False),('project/link',True)]:
    archive=root/'a.tar.gz'
    with tarfile.open(archive,'w:gz') as stream:
     item=tarfile.TarInfo(name)
     if link:item.type=tarfile.SYMTYPE;item.linkname='/tmp/outside'
     stream.addfile(item)
    destination=root/'out';destination.mkdir(exist_ok=True)
    with self.assertRaises(RuntimeError):updater.unpack(archive,destination)
 def test_verified_download_runs_only_user_update_and_bad_hash_blocks_it(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);installed=root/'installed';installed.mkdir();(installed/'VERSION').write_text('v0.1.0-alpha.1')
   source=io.BytesIO()
   with tarfile.open(fileobj=source,mode='w:gz') as stream:
    item=tarfile.TarInfo('project/install.sh');content=b'#!/bin/bash\n';item.size=len(content);stream.addfile(item,io.BytesIO(content))
   archive=source.getvalue();tag='v0.1.0-alpha.2';name='hyprland-g8d-'+tag+'.tar.gz'
   prefix='https://github.com/'+updater.REPO+'/releases/download/'+tag+'/'
   release={'tag_name':tag,'assets':[{'name':n,'browser_download_url':prefix+n} for n in [name,'SHA256SUMS']]}
   def fetch(url,path=None,limit=0):
    data=json.dumps([release]).encode() if url==updater.API else ((hashlib.sha256(archive).hexdigest()+'  '+name+'\n').encode() if url.endswith('SHA256SUMS') else archive)
    if path:path.write_bytes(data)
    return data
   with patch.object(updater,'ROOT',installed),patch.object(updater.Path,'home',return_value=root/'home'),patch.object(updater,'fetch',side_effect=fetch),patch.object(updater.subprocess,'run') as run:
    updater.update();self.assertEqual(run.call_count,1)
    self.assertEqual(run.call_args.args[0][-2:],['--no-packages','--no-session'])
   def bad_fetch(url,path=None,limit=0):
    if url.endswith('SHA256SUMS'):return ('0'*64+'  '+name+'\n').encode()
    return fetch(url,path,limit)
   with patch.object(updater,'ROOT',installed),patch.object(updater.Path,'home',return_value=root/'home'),patch.object(updater,'fetch',side_effect=bad_fetch),patch.object(updater.subprocess,'run') as run:
    with self.assertRaises(RuntimeError):updater.update()
    run.assert_not_called()

if __name__=='__main__':unittest.main()
