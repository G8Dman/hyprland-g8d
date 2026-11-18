"""Filesystem upgrade/rollback with external package and compositor steps isolated."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('g8d_install',Path(__file__).resolve().parents[1]/'scripts/install.py')
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)

class InstallUpgrade(unittest.TestCase):
    def fixture(self, home):
        config=home/'.config/hyprland-g8d';config.mkdir(parents=True)
        data={'accent':'#8c6fca','theme':'clear','wallpaper':'keep.png','wallpapers':{'EXTERNAL':'custom.webp'},
              'wallpaper_colors':True,'palette_output':'EXTERNAL','theme_colors':{'clear':{'background':'#f5f1fa'}}}
        saved={'appearance.json':json.dumps(data),'branding.json':'{"label":"My desktop"}',
               'calendar.json':'{"enabled":false}', 'monitors.lua':'-- existing monitor preferences\n',
               'shortcuts.json':'[]', 'cursor-effects.json':'{"enabled":false}', 'VERSION':'v0.1.0-alpha.2\n'}
        for name,content in saved.items():(config/name).write_text(content)
        ordinary=home/'.config/hypr/hyprland.conf';ordinary.parent.mkdir(parents=True);ordinary.write_text('keep ordinary session')
        return config,saved,ordinary

    def execute(self,args,**kwargs):
        args=list(map(str,args))
        if args[1:3]==['-m','venv']:
            binary=Path(args[-1])/'bin/python';binary.parent.mkdir(parents=True,exist_ok=True);binary.symlink_to(sys.executable)
        elif '-c' in args and "G8D_APPEARANCE_ROOT" in args[-1]:
            subprocess.run([sys.executable,'-c',args[-1]],check=True,env=kwargs['env'])

    def test_saved_preferences_survive_and_new_ui_is_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);config,saved,ordinary=self.fixture(home)
            argv=['install.py','--target-home',str(home),'--no-packages','--no-session']
            with patch.object(sys,'argv',argv),patch.object(installer.os,'geteuid',return_value=1000),patch.object(installer.shutil,'which',return_value='/usr/bin/available'),patch.object(installer,'execute',side_effect=self.execute):
                installer.main()
            for name,content in saved.items():
                if name!='VERSION':self.assertEqual((config/name).read_text(),content,name)
            self.assertEqual(ordinary.read_text(),'keep ordinary session')
            self.assertEqual((config/'VERSION').read_text(),(installer.REPO/'VERSION').read_text())
            self.assertIn('f5f1fa',(config/'plugins/settings.css').read_text())
            self.assertIn('md_on_primary',(config/'plugins/settings.css').read_text())
            self.assertIn('My desktop / clear',(config/'hyprlock.conf').read_text())
            for name in ['quick_settings.py','settings-material.css','quick-settings.css','shortcuts_ui.py']:
                self.assertTrue((config/'plugins'/name).exists(),name)
            self.assertTrue((config/'plugins/icons/hicolor/scalable/actions/g8d-wifi-symbolic.svg').exists())
            self.assertTrue((config/'themes/clear/plugins/settings.css').exists())
            self.assertTrue((config/'shortcuts.lua').exists())
            self.assertTrue(list((home/'.local/state/hyprland-g8d/install-backups').glob('*/config/appearance.json')))

    def test_render_failure_restores_previous_config(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);config,saved,ordinary=self.fixture(home)
            def fail(args,**kwargs):
                if '-c' in list(map(str,args)) and 'import appearance' in str(args[-1]):raise RuntimeError('render failed')
                return self.execute(args,**kwargs)
            argv=['install.py','--target-home',str(home),'--no-packages','--no-session']
            with patch.object(sys,'argv',argv),patch.object(installer.os,'geteuid',return_value=1000),patch.object(installer.shutil,'which',return_value='/usr/bin/available'),patch.object(installer,'execute',side_effect=fail):
                with self.assertRaises(RuntimeError):installer.main()
            self.assertEqual({p.name:p.read_text() for p in config.iterdir()},saved)
            self.assertEqual(ordinary.read_text(),'keep ordinary session')
