"""Isolated palette regressions included in the published source tree."""
from pathlib import Path
import subprocess
import sys
import unittest

class Palettes(unittest.TestCase):
    def test_theme_round_trip_and_rollback(self):
        subprocess.run([sys.executable,str(Path(__file__).parent/'cases/check_theme_state.py')],check=True)

    def test_wallpaper_detection_and_custom_profiles(self):
        subprocess.run([sys.executable,str(Path(__file__).parent/'cases/check_wallpaper_colors.py')],check=True)
