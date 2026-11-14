#!/usr/bin/env python3
"""CLI entry point for g8d's standalone Yandex Music backend."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
from yamusic_backend import run

if __name__ == '__main__':
    try:
        runtime = Path(os.environ.get('XDG_RUNTIME_DIR', '/tmp'))
        path = runtime / f'g8d-yandex-presets-{os.getuid()}.lock'
        with path.open('a') as lock:
            os.chmod(path, 0o600)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('Предыдущая команда музыки ещё выполняется') from None
            print(json.dumps(run(sys.argv[1] if len(sys.argv) > 1 else 'show')))
    except (OSError, ValueError, subprocess.SubprocessError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
