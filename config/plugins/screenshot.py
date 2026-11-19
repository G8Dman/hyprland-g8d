#!/usr/bin/env python3
"""Select a region of an immutable desktop frame, with no new capture after selection."""
import fcntl
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time


def notify(message, critical=False):
    try:
        subprocess.run(['notify-send', *(['-u', 'critical'] if critical else []),
                        'g8d / снимок экрана', message], timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired): pass


def main():
    runtime = Path(os.environ.get('XDG_RUNTIME_DIR', '/tmp'))
    session = os.environ.get('HYPRLAND_INSTANCE_SIGNATURE', 'default')
    with (runtime / f'g8d-screenshot-{os.getuid()}-{session}.lock').open('w') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return
        with tempfile.TemporaryDirectory(prefix='g8d-screenshot-', dir=runtime) as temporary:
            frame = Path(temporary) / 'frame.png'
            # Capture before GTK starts, before menus lose focus and before the pointer moves.
            subprocess.run(['grim', str(frame)], check=True)
            select_frame(frame)


def select_frame(frame):
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('Gdk', '3.0')
    gi.require_version('GtkLayerShell', '0.1')
    from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, GtkLayerShell as Layer
    from PIL import Image

    Gtk.init(None)
    if not Layer.is_supported(): raise RuntimeError('Для выбора области нужен Wayland Layer Shell')
    display = Gdk.Display.get_default()
    monitors = [display.get_monitor(i) for i in range(display.get_n_monitors())]
    if not monitors: raise RuntimeError('Нет доступных экранов')
    rects = [m.get_geometry() for m in monitors]
    left, top = min(r.x for r in rects), min(r.y for r in rects)
    right, bottom = max(r.x + r.width for r in rects), max(r.y + r.height for r in rects)
    pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(frame))
    sx, sy = pixbuf.get_width() / (right - left), pixbuf.get_height() / (bottom - top)
    # Both frozen surfaces and slurp must appear immediately, including during desktop animations.
    subprocess.run(['hyprctl', 'eval', 'hl.layer_rule({ name = "g8d-screenshot", '
                    'match = { namespace = "^(g8d-screenshot-freeze|selection)$" }, '
                    'no_anim = true, blur = false })'], check=True, capture_output=True, timeout=3)
    windows, drawn = [], set()
    selection = None
    geometry = None
    error = None
    started = False

    def stop(*_):
        nonlocal selection
        if selection is not None and selection.poll() is None:
            selection.terminate()
            try: selection.wait(timeout=2)
            except subprocess.TimeoutExpired: selection.kill(); selection.wait()
        for window in windows: window.destroy()
        Gtk.main_quit()
        return False

    def selected():
        nonlocal geometry, error
        if selection.poll() is None: return True
        output, stderr = selection.communicate()
        if selection.returncode == 0: geometry = output.strip()
        elif selection.returncode != 1: error = RuntimeError(stderr.strip() or 'Не удалось выбрать область')
        stop()
        return False

    def begin():
        nonlocal selection, error
        try:
            selection = subprocess.Popen(['slurp', '-b', '111519bb', '-c', '8bbfba', '-w', '1'],
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            GLib.timeout_add(30, selected)
        except Exception as exc: error = exc; stop()
        return False

    def draw(widget, context, index, rect):
        nonlocal started
        context.scale(1 / sx, 1 / sy)
        Gdk.cairo_set_source_pixbuf(context, pixbuf, -(rect.x - left) * sx, -(rect.y - top) * sy)
        context.paint()
        drawn.add(index)
        if len(drawn) == len(monitors) and not started:
            started = True
            GLib.idle_add(begin)
        return False

    try:
        for index, (monitor, rect) in enumerate(zip(monitors, rects)):
            window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
            Layer.init_for_window(window)
            Layer.set_namespace(window, 'g8d-screenshot-freeze')
            Layer.set_monitor(window, monitor)
            Layer.set_layer(window, Layer.Layer.OVERLAY)
            Layer.set_keyboard_mode(window, Layer.KeyboardMode.NONE)
            Layer.set_exclusive_zone(window, -1)
            for edge in [Layer.Edge.TOP, Layer.Edge.BOTTOM, Layer.Edge.LEFT, Layer.Edge.RIGHT]:
                Layer.set_anchor(window, edge, True)
            canvas = Gtk.DrawingArea()
            canvas.connect('draw', draw, index, rect)
            window.add(canvas)
            windows.append(window)
        for window in windows: window.show_all()
        handlers = [GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, stop) for sig in [signal.SIGTERM, signal.SIGINT]]
        try: Gtk.main()
        finally:
            for handler in handlers: GLib.source_remove(handler)
    finally:
        if selection is not None and selection.poll() is None: selection.terminate(); selection.wait(timeout=3)
        for window in windows: window.destroy()
    if error: raise error
    if not geometry: return  # Escape: keep the clipboard and screenshot directory unchanged.
    match = re.fullmatch(r'(-?\d+),(-?\d+) (\d+)x(\d+)', geometry)
    if not match: raise RuntimeError('Некорректная область: ' + geometry)
    x, y, width, height = map(int, match.groups())
    if width <= 0 or height <= 0: return
    bounds = (round((x-left)*sx), round((y-top)*sy), round((x+width-left)*sx), round((y+height-top)*sy))
    directory = Path.home() / 'Pictures/Screenshots'
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / ('g8d-' + time.strftime('%Y%m%d-%H%M%S') + f'-{time.time_ns() % 1000000000:09d}.png')
    with Image.open(frame) as image: image.crop(bounds).save(target)
    with target.open('rb') as content:
        subprocess.run(['wl-copy', '--type', 'image/png'], stdin=content, check=True)
    notify('Сохранён и скопирован: ' + str(target))


if __name__ == '__main__':
    try: main()
    except Exception as exc:
        notify(str(exc), critical=True)
        raise
