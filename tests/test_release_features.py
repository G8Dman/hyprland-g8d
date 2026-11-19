"""Isolated palette regressions included in the published source tree."""
from pathlib import Path
import subprocess
import sys
import unittest

class Chords(unittest.TestCase):
    def test_chord_order_is_preserved_in_generated_lua(self):
        plugins = Path(__file__).resolve().parents[1] / 'config/plugins'
        code = """
import sys
sys.path.insert(0, sys.argv[1])
import shortcuts
first = {'id': 'a'*32, 'name': 'First', 'combo': 'ctrl + alt + shift + Space + x + e',
         'kind': 'command', 'command': 'true', 'terminal': False}
second = {**first, 'id':'b'*32, 'combo':'CTRL + ALT + SHIFT + Space + E + X'}
lua = shortcuts.render([first, second])
assert 'hl.bind("CTRL + ALT + SHIFT + space + X + E"' in lua
assert 'hl.bind("CTRL + ALT + SHIFT + space + E + X"' in lua
"""
        subprocess.run([sys.executable, '-c', code, str(plugins)], check=True)


class Palettes(unittest.TestCase):
    def test_theme_round_trip_and_rollback(self):
        subprocess.run([sys.executable,str(Path(__file__).parent/'cases/check_theme_state.py')],check=True)

    def test_wallpaper_detection_and_custom_profiles(self):
        subprocess.run([sys.executable,str(Path(__file__).parent/'cases/check_wallpaper_colors.py')],check=True)

    def test_light_dark_lock_background_and_rollback(self):
        subprocess.run([sys.executable,str(Path(__file__).parent/'cases/check_style_modes.py')],check=True)

    def test_interface_style_independent_of_taskbar(self):
        subprocess.run([sys.executable,str(Path(__file__).parent/'cases/check_ui_styles.py')],check=True)
