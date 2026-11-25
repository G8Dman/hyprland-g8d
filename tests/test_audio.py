from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'config/plugins'))
import audio


class AudioTests(unittest.TestCase):
    def test_groups_streams_with_mixed_outputs_and_unwritable_levels(self):
        outputs = [{'index': 1, 'name': 'headphones'}, {'index': 2, 'name': 'speakers'}]
        streams = [
            {'index': 10, 'sink': 1, 'properties': {'application.id': 'browser', 'application.name': 'Browser'},
             'volume': {'left': {'value': 65536}, 'right': {'value': 32768}}},
            {'index': 11, 'sink': 2, 'properties': {'application.id': 'browser', 'application.name': 'Browser'},
             'volume': {'mono': {'value': 65536}}, 'volume_writable': False},
            {'index': 12, 'sink': 2, 'properties': {'application.name': 'Player'}},
        ]

        browser, player = audio.applications(streams, outputs)

        self.assertEqual(browser['streams'], [10, 11])
        self.assertEqual(browser['writable'], [10])
        self.assertEqual(browser['volume'], 75)
        self.assertTrue(browser['mixed'])
        self.assertIsNone(browser['output'])
        self.assertEqual(player['output'], 'speakers')
        self.assertIsNone(player['volume'])

    def test_failed_stream_edit_allows_remaining_commands_and_refresh(self):
        edits = [('Не удалось изменить выход.',
                  [('move-sink-input', '10', 'headphones'), ('move-sink-input', '11', 'headphones')])]
        expired = subprocess.CalledProcessError(1, 'pactl', stderr='No such entity')
        with (patch.object(audio, 'pactl', side_effect=[expired, '']) as pactl,
              patch.object(audio, 'snapshot', return_value=(None, [], [])) as snapshot):
            state, errors = audio.apply(edits, True)

        self.assertEqual([call.args for call in pactl.call_args_list], edits[0][1])
        self.assertEqual(state, (None, [], []))
        self.assertEqual(errors, [(edits[0][0], 'No such entity')])
        snapshot.assert_called_once_with(True)
