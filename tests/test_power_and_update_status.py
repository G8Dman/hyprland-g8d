import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'config/plugins'))
from power_profiles import profile_state
import update_indicator


class PowerAndUpdateStatusTests(unittest.TestCase):
    def test_hardware_can_omit_or_inhibit_performance(self):
        system = {'ActiveProfile': 'balanced', 'Profiles': [{'Profile': 'balanced'}, {'Profile': 'power-saver'}]}
        self.assertEqual(profile_state(system), ('balanced', ('power-saver', 'balanced'), ''))
        system['Profiles'].append({'Profile': 'performance'})
        system['PerformanceInhibited'] = 'platform'
        self.assertNotIn('performance', profile_state(system)[1])
        system['PerformanceInhibited'] = ''
        self.assertIn('performance', profile_state(system)[1])

    def test_two_consumers_share_hourly_check_and_hide_after_installation(self):
        tag = 'v0.3.0-alpha.1'
        base = f'https://github.com/{update_indicator.updater.REPO}/releases/download/{tag}/'
        release = {'tag_name': tag, 'assets': [{'name': name, 'browser_download_url': base + name}
                   for name in (f'hyprland-g8d-{tag}.tar.gz', 'SHA256SUMS')]}
        with tempfile.TemporaryDirectory() as directory, patch.object(update_indicator.updater, 'fetch') as fetch:
            fetch.side_effect = [json.dumps([release]), OSError('offline')]
            cache = Path(directory) / 'indicator.json'
            start = update_indicator.hour(1764000000)
            self.assertEqual(update_indicator.check(cache, start), tag)
            self.assertEqual(update_indicator.check(cache, start + 3599), tag)
            fetch.assert_called_once()
            self.assertEqual(update_indicator.check(cache, start + 3600), tag)
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(update_indicator.indicator('v0.2.0', tag)['text'], '↻')
            self.assertEqual(update_indicator.indicator(tag, tag), {'text': ''})
