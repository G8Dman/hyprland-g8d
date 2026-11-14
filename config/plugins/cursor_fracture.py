"""A short, click-through particle burst spanning a shared monitor edge. No motion polling."""
import json
import math
import random
import re
import subprocess
import time
from pathlib import Path

import cairo
from gi.repository import Gdk, Gtk, GtkLayerShell as Layer


class Fracture:
    RADIUS = 240
    DURATION = .78

    def __init__(self, app):
        self.app = app
        self.config = Path(__file__).parent.parent / 'cursor-effects.json'
        try: self.enabled = bool(json.loads(self.config.read_text()).get('enabled', True))
        except (OSError, ValueError): self.enabled = True
        self.windows = []
        self.last = None
        self.last_hit = 0
        self.started = 0
        self.tick = 0
        self.previous = ''
        try:
            monitors = json.loads(subprocess.check_output(['hyprctl', '-j', 'monitors'], text=True, timeout=1))
            self.previous = next((m['name'] for m in monitors if m.get('focused')), '')
        except (OSError, ValueError, subprocess.SubprocessError): pass

    def set_enabled(self, enabled, persist=True):
        if persist:
            self.save_enabled(enabled)
        self.enabled = bool(enabled)
        if not self.enabled: self.clear()

    def save_enabled(self, enabled):
        temporary = self.config.with_suffix('.json.tmp')
        temporary.write_text(json.dumps({'enabled': bool(enabled)}) + '\n')
        temporary.replace(self.config)

    def monitor_focused(self, name):
        if name == self.previous: return
        previous, self.previous = self.previous, name
        if not self.enabled or self.app.game_state.get('enabled'): return
        try:
            monitors = json.loads(subprocess.check_output(['hyprctl', '-j', 'monitors'], text=True, timeout=1))
            cursor = json.loads(subprocess.check_output(['hyprctl', '-j', 'cursorpos'], text=True, timeout=1))
        except (OSError, ValueError, subprocess.SubprocessError): return
        source = next((m for m in monitors if m['name'] == previous), None)
        target = next((m for m in monitors if m['name'] == name), None)
        if not source or not target: return
        def rect(m):
            width, height = m['width'], m['height']
            if m.get('transform', 0) % 2: width, height = height, width
            return (m['x'], m['y'], round(width / m['scale']), round(height / m['scale']))
        ax, ay, aw, ah = rect(source)
        bx, by, bw, bh = rect(target)
        x, y = cursor['x'], cursor['y']
        if not (bx <= x < bx+bw and by <= y < by+bh): return
        # Focus events can arrive after a fast pointer has travelled deep into
        # the next screen. Project its position onto the shared edge instead of
        # requiring it to remain in a narrow strip near that edge.
        if ax+aw == bx or bx+bw == ax:
            seam = bx if ax+aw == bx else ax
            low, high = max(ay, by), min(ay+ah, by+bh)
            if low <= y < high:
                self.burst(seam, y, 1 if bx > ax else -1, False)
        elif ay+ah == by or by+bh == ay:
            seam = by if ay+ah == by else ay
            low, high = max(ax, bx), min(ax+aw, bx+bw)
            if low <= x < high:
                self.burst(x, seam, 1 if by > ay else -1, True)

    def accent(self):
        try:
            css = (Path(__file__).parent / 'style.css').read_text()
            match = re.search(r'\.heading\s*\{\s*color:\s*#([0-9a-fA-F]{6})', css)
            value = match[1] if match else '8bbfba'
            return tuple(int(value[i:i+2],16)/255 for i in (0,2,4))
        except OSError: return (.55,.75,.73)

    def burst(self, x, y, direction, horizontal=False):
        if not self.enabled or self.app.game_state.get('enabled'): return
        self.clear()
        self.last_hit = self.started = time.monotonic()
        self.last = {'x': x, 'y': y, 'direction': direction, 'horizontal': horizontal}
        self.color = self.accent()
        self.shards = []
        rng = random.Random()
        for _ in range(32):
            self.shards.append((rng.uniform(-12,12), rng.uniform(-46,46),
                                direction*rng.uniform(40,230)+rng.uniform(-120,120),
                                rng.uniform(-175,175), rng.uniform(4,12), rng.uniform(-9,9)))
        radius = self.RADIUS
        for i in range(self.app.display.get_n_monitors()):
            monitor = self.app.display.get_monitor(i)
            g = monitor.get_geometry()
            left, top = max(g.x, int(x-radius)), max(g.y, int(y-radius))
            right, bottom = min(g.x+g.width, int(x+radius)), min(g.y+g.height, int(y+radius))
            if left >= right or top >= bottom: continue
            window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
            window.set_decorated(False)
            window.set_app_paintable(True)
            visual = window.get_screen().get_rgba_visual()
            if visual: window.set_visual(visual)
            window.set_accept_focus(False)
            Layer.init_for_window(window)
            Layer.set_namespace(window, 'g8d-cursor-fracture')
            Layer.set_monitor(window, monitor)
            Layer.set_layer(window, Layer.Layer.OVERLAY)
            Layer.set_keyboard_mode(window, Layer.KeyboardMode.NONE)
            Layer.set_exclusive_zone(window, -1)
            Layer.set_anchor(window, Layer.Edge.TOP, True)
            Layer.set_anchor(window, Layer.Edge.LEFT, True)
            Layer.set_margin(window, Layer.Edge.LEFT, left-g.x)
            Layer.set_margin(window, Layer.Edge.TOP, top-g.y)
            window.set_size_request(right-left,bottom-top)
            # Store the empty region on GtkWidget so map/resize cannot restore
            # a rectangular input surface after GdkWindow realization.
            window.input_shape_combine_region(cairo.Region())
            window.connect('realize', lambda w: w.get_window().set_pass_through(True))
            window.connect('draw', self.draw, x-left, y-top, horizontal)
            self.windows.append(window)
            window.show_all()
        if self.windows: self.tick = self.windows[0].add_tick_callback(self.frame)

    def frame(self, *_):
        if time.monotonic() - self.started >= self.DURATION:
            self.tick = 0
            self.clear()
            return False
        for window in self.windows: window.queue_draw()
        return True

    def draw(self, window, context, cx, cy, horizontal):
        context.set_operator(cairo.OPERATOR_SOURCE)
        context.set_source_rgba(0,0,0,0)
        context.paint()
        context.set_operator(cairo.OPERATOR_OVER)
        age = max(0, time.monotonic()-self.started)
        progress = min(1, age/self.DURATION)
        alpha = (1-progress)**1.5
        context.translate(cx,cy)
        if horizontal: context.rotate(math.pi/2)
        # An expanding shockwave and tumbling fragments; no cracks.
        context.save()
        context.scale(.5,1)
        context.arc(0,0,10+progress*150,0,math.tau)
        context.set_source_rgba(*self.color,alpha*.6)
        context.set_line_width(2)
        context.stroke()
        context.restore()
        for px,py,vx,vy,size,spin in self.shards:
            context.save()
            context.translate(px+vx*age,py+vy*age+85*age*age)
            context.rotate(spin*age)
            context.move_to(-size,-size*.5)
            context.line_to(size*.7,-size*.65)
            context.line_to(size*.3,size)
            context.close_path()
            context.set_source_rgba(.12,.16,.2,alpha*.95)
            context.fill_preserve()
            context.set_line_width(.9)
            context.set_source_rgba(*self.color,alpha)
            context.stroke()
            context.restore()
        return False

    def clear(self):
        if self.tick and self.windows: self.windows[0].remove_tick_callback(self.tick)
        self.tick = 0
        for window in self.windows: window.destroy()
        self.windows.clear()

    close = clear
