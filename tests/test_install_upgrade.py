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
               'shortcuts.json':json.dumps([{'id': 'a' * 32, 'name': 'Test', 'combo': 'CTRL + ALT + SHIFT + Space + X + E',
                                            'kind': 'command', 'command': 'true', 'terminal': False}]),
               'cursor-effects.json':'{"enabled":false}', 'VERSION':'v0.1.0-alpha.2\n'}
        for name,content in saved.items():(config/name).write_text(content)
        ordinary=home/'.config/hypr/hyprland.conf';ordinary.parent.mkdir(parents=True);ordinary.write_text('keep ordinary session')
        return config,saved,ordinary

    def execute(self,args,**kwargs):
        args=list(map(str,args))
        if args[1:3]==['-m','venv']:
            binary=Path(args[-1])/'bin/python';binary.parent.mkdir(parents=True,exist_ok=True);binary.symlink_to(sys.executable)
        elif '-c' in args and "G8D_APPEARANCE_ROOT" in args[args.index('-c') + 1]:
            subprocess.run([sys.executable,*args[args.index('-c'):]],check=True,env=kwargs['env'])

    def test_saved_preferences_survive_and_new_ui_is_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);config,saved,ordinary=self.fixture(home)
            argv=['install.py','--target-home',str(home),'--no-packages','--no-session']
            def verify_staged(args, **kwargs):
                if args[:2] == ['Hyprland', '--verify-config']:
                    stage = Path(kwargs['env']['G8D_CONFIG_DIR'])
                    self.assertNotEqual(stage, config)
                    self.assertEqual((config / 'VERSION').read_text(), saved['VERSION'])
                    self.assertIn('f5f1fa', (stage / 'plugins/settings.css').read_text())
                    self.assertIn(str(config / 'plugins/shortcuts.py'), (stage / 'shortcuts.lua').read_text())
                return self.execute(args, **kwargs)

            with patch.object(sys,'argv',argv),patch.object(installer.os,'geteuid',return_value=1000),patch.object(installer.shutil,'which',return_value='/usr/bin/available'),patch.object(installer,'execute',side_effect=verify_staged):
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
            shortcuts = (config / 'shortcuts.lua').read_text()
            self.assertIn(str(config / 'plugins/shortcuts.py'), shortcuts)
            self.assertNotIn('.g8d-stage-', shortcuts)
            self.assertEqual(len(list((home/'.local/share/fonts/g8d-nothing').glob('*.ttf'))),3)
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

    def test_fresh_render_failure_leaves_no_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)

            def fail(args, **kwargs):
                if 'import appearance' in str(args[-1]):
                    raise RuntimeError('render failed')
                return self.execute(args, **kwargs)

            argv = ['install.py', '--target-home', str(home), '--no-packages', '--no-session']
            with patch.object(sys, 'argv', argv), patch.object(installer.os, 'geteuid', return_value=1000), patch.object(installer.shutil, 'which', return_value='/usr/bin/available'), patch.object(installer, 'execute', side_effect=fail):
                with self.assertRaisesRegex(RuntimeError, 'render failed'):
                    installer.main()
            artifacts = ['.config/hyprland-g8d', '.local/bin/hyprland-g8d', '.local/bin/g8d-settings',
                         '.local/share/applications/g8d-settings.desktop', '.local/share/fonts/g8d-nothing',
                         '.local/share/hyprland-g8d/venv']
            self.assertEqual([path for path in artifacts if (home / path).exists()], [])

    def test_late_failure_restores_previous_files_and_removes_new_ones(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config, saved, ordinary = self.fixture(home)
            launcher = home / '.local/bin/g8d-settings'
            desktop = home / '.local/share/applications/g8d-settings.desktop'
            fonts = home / '.local/share/fonts/g8d-nothing'
            for path in (launcher, desktop, fonts / 'previous.ttf'):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('old ' + path.name)

            def fail(args, **kwargs):
                if args[0] == 'sudo':
                    self.assertNotEqual((config / 'VERSION').read_text(), saved['VERSION'])
                    self.assertTrue((launcher.parent / 'hyprland-g8d').exists())
                    self.assertIn('[Desktop Entry]', desktop.read_text())
                    raise subprocess.CalledProcessError(1, args)
                return self.execute(args, **kwargs)

            with patch.object(installer, 'execute', side_effect=fail):
                with self.assertRaises(subprocess.CalledProcessError):
                    installer.install(home, config, home / '.local/share/hyprland-g8d/venv', register_session=True)
            self.assertEqual({p.name: p.read_text() for p in config.iterdir()}, saved)
            self.assertEqual(ordinary.read_text(), 'keep ordinary session')
            self.assertEqual(launcher.read_text(), 'old g8d-settings')
            self.assertEqual(desktop.read_text(), 'old g8d-settings.desktop')
            self.assertEqual([path.name for path in fonts.iterdir()], ['previous.ttf'])
            self.assertEqual((fonts / 'previous.ttf').read_text(), 'old previous.ttf')
            self.assertFalse((launcher.parent / 'hyprland-g8d').exists())
            self.assertFalse((home / '.local/share/hyprland-g8d/venv').exists())
