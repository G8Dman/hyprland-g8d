"""Run the session startup against failing or delayed wallpaper commands."""
from contextlib import redirect_stderr
from io import StringIO
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


CONFIG = Path(__file__).resolve().parents[1] / 'config'


class Autostart(unittest.TestCase):
    def run_session(self, wallpaper):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            events = home / 'events'
            events.touch()
            stub = home / 'stub'
            stub.write_text("""#!/bin/bash
name=${0##*/}
case "$name" in
    hyprctl)
        for job in waybar panels.py mako hypridle "$G8D_TEST_LAST_EVENT"; do
            for attempt in {1..40}; do
                if grep -Fqx "$job" "$G8D_TEST_EVENTS"; then break; fi
                sleep .05
            done
        done
        exit 1;;
    python3)
        name=${1##*/}
        if [[ "$name" == appearance.py ]]; then
            if [[ "$G8D_TEST_WALLPAPER" == slow ]]; then
                printf '%s\n' wallpaper-started >>"$G8D_TEST_EVENTS"
                exec sleep 6
            fi
            exit 17
        fi;;
esac
printf '%s\n' "$name" >>"$G8D_TEST_EVENTS"
""")
            stub.chmod(0o755)
            for name in ('hyprctl', 'python3', 'waybar', 'mako', 'hypridle', 'swaybg'):
                (home / name).symlink_to(stub)
            environment = {**os.environ, 'HOME': str(home), 'PATH': f'{home}:{os.environ["PATH"]}',
                           'G8D_CONFIG_DIR': str(CONFIG), 'G8D_PREVIEW': '1',
                           'G8D_TEST_EVENTS': str(events), 'G8D_TEST_WALLPAPER': wallpaper,
                           'G8D_TEST_LAST_EVENT': 'swaybg' if wallpaper == 'fail' else 'wallpaper-started'}
            result = subprocess.run(['bash', CONFIG / 'autostart'], env=environment, timeout=4)
            return result.returncode, set(events.read_text().splitlines())

    def test_failed_wallpaper_keeps_services_and_starts_fallback(self):
        self.assertEqual(self.run_session('fail'), (0, {'waybar', 'panels.py', 'mako', 'hypridle', 'swaybg'}))

    def test_slow_wallpaper_does_not_delay_services(self):
        self.assertEqual(self.run_session('slow'), (0, {'waybar', 'panels.py', 'mako', 'hypridle', 'wallpaper-started'}))


class WallpaperFallback(unittest.TestCase):
    def test_failing_output_uses_bundled_image_then_solid_and_other_output_keeps_selection(self):
        with patch.object(sys, 'path', [str(CONFIG / 'plugins'), *sys.path]):
            import appearance

        for bundled_fails in (False, True):
            with self.subTest(bundled_fails=bundled_fails), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state = root / 'renderers.json'
                bundled = root / 'wallpaper.png'
                selected = {'first': root / 'broken.mp4', 'second': root / 'selected.png'}
                selected['first'].touch()
                shutil.copyfile(CONFIG / 'wallpaper.png', bundled)
                shutil.copyfile(bundled, selected['second'])

                def renderer(arguments, **kwargs):
                    failed = arguments[0] == 'mpvpaper' or (bundled_fails and str(bundled) in arguments)
                    return SimpleNamespace(pid=12345, poll=lambda: 17 if failed else None)

                with (patch.object(appearance, 'ROOT', root),
                      patch.object(appearance, 'RENDER_STATE', state),
                      patch.object(appearance.Path, 'home', return_value=root),
                      patch.object(appearance, 'game_enabled', return_value=False),
                      patch.object(appearance, 'monitors', return_value=[{'name': 'first'}, {'name': 'second'}]),
                      patch.object(appearance, 'tagged_renderers', return_value=[]),
                      patch.object(appearance, 'wallpaper_for', side_effect=selected.get),
                      patch.object(appearance.time, 'sleep'),
                      patch.object(appearance.psutil, 'Process') as process,
                      patch.object(appearance.subprocess, 'Popen', side_effect=renderer) as attempts,
                      redirect_stderr(StringIO())):
                    process.return_value.create_time.return_value = 10
                    appearance.start()
                    self.assertEqual([call.args[0][0] for call in attempts.call_args_list],
                                     ['mpvpaper', 'swaybg'] + (['swaybg'] if bundled_fails else []) + ['swaybg'])
                    records = appearance.renderer_state()
                    self.assertEqual(records['first']['file'], None if bundled_fails else str(bundled))
                    if bundled_fails:
                        self.assertEqual(records['first']['argv'], ['swaybg', '-o', 'first', '-c', '#161b20'])
                    self.assertEqual(records['second']['file'], str(selected['second']))

                    attempts.reset_mock()
                    with self.assertRaises(RuntimeError):
                        appearance.start(output='first', fallback=False)
                    self.assertEqual(attempts.call_count, 1)
                    self.assertEqual(attempts.call_args.args[0][0], 'mpvpaper')

    def test_no_usable_wallpaper_reports_failure_to_autostart(self):
        with patch.object(sys, 'path', [str(CONFIG / 'plugins'), *sys.path]):
            import appearance

        with (patch.object(appearance, 'ROOT', CONFIG),
              patch.object(appearance, 'game_enabled', return_value=False),
              patch.object(appearance, 'monitors', return_value=[{'name': 'first'}]),
              patch.object(appearance, 'tagged_renderers', return_value=[]),
              patch.object(appearance, 'renderer_state', return_value={}),
              patch.object(appearance, 'wallpaper_for', side_effect=TypeError('invalid preference')),
              patch.object(appearance, 'start_output', side_effect=RuntimeError('renderer exited')) as attempts,
              redirect_stderr(StringIO())):
            with self.assertRaisesRegex(RuntimeError, 'first'):
                appearance.start()
            self.assertEqual([call.args for call in attempts.call_args_list],
                             [('first', CONFIG / 'wallpaper.png'), ('first', None)])
