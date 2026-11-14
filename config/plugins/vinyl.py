"""Native Cairo turntable, with the actual MPRIS album cover on the label."""
import math
from pathlib import Path
import time
from urllib.parse import unquote, urlparse

import cairo
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk


TAU = math.tau
SPEED = TAU / 8


def circle(ctx, x, y, radius):
    ctx.new_sub_path()
    ctx.arc(x, y, radius, 0, TAU)


def rounded(ctx, x, y, width, height, radius):
    ctx.new_sub_path()
    for cx, cy, start in [(x + width - radius, y + radius, -math.pi / 2),
                          (x + width - radius, y + height - radius, 0),
                          (x + radius, y + height - radius, math.pi / 2),
                          (x + radius, y + radius, math.pi)]:
        ctx.arc(cx, cy, radius, start, start + math.pi / 2)
    ctx.close_path()


class Vinyl(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.set_size_request(-1, 234)
        self.set_tooltip_text('Обложка текущего альбома · вращается во время воспроизведения')
        self.get_style_context().add_class('heading')
        self.get_accessible().set_name('Виниловый проигрыватель · обложка альбома')
        self.cover = None
        self.cover_key = None
        self.playing = False
        self.offset = 0.0
        self.started = time.monotonic()
        self.tick = 0
        self.connect('draw', self.draw)
        self.connect('map', lambda *_: self.animate())
        self.connect('unmap', lambda *_: self.stop_tick())
        self.connect('destroy', lambda *_: self.stop_tick())

    def angle(self):
        elapsed = time.monotonic() - self.started if self.playing else 0
        return (self.offset + elapsed * SPEED) % TAU

    def update(self, player):
        player = player or {}
        playing = player.get('status') == 'Playing'
        if playing != self.playing:
            self.offset = self.angle()
            self.started = time.monotonic()
            self.playing = playing
            if playing:
                self.animate()
            else:
                self.stop_tick()
        self.load_cover(player.get('art', ''))
        title = player.get('title') or 'Нет выбранного трека'
        self.set_tooltip_text(title + (' · пластинка вращается' if playing else ' · на паузе'))
        self.queue_draw()

    def load_cover(self, uri):
        try:
            parsed = urlparse(uri)
            if parsed.scheme != 'file' or parsed.netloc not in ('', 'localhost'):
                raise ValueError('Not a local MPRIS cover')
            path = Path(unquote(parsed.path))
            info = path.stat()
            key = (str(path), info.st_mtime_ns, info.st_size)
            if key == self.cover_key:
                return
            if not path.is_file() or info.st_size > 6 * 1024 * 1024:
                raise ValueError('Cover too large')
            self.cover = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), 240, 240, True)
            self.cover_key = key
        except (OSError, ValueError, TypeError, GLib.Error):
            # A disappearing Chromium temp file or malformed art must never
            # interrupt playback or the rest of the dashboard.
            self.cover = None
            self.cover_key = None

    def animate(self):
        if self.playing and self.get_mapped() and not self.tick:
            self.tick = self.add_tick_callback(self.frame)

    def frame(self, _widget, _clock):
        self.queue_draw()
        return True

    def stop_tick(self):
        if self.tick:
            self.remove_tick_callback(self.tick)
            self.tick = 0

    def draw(self, _widget, ctx):
        width, height = self.get_allocated_width(), self.get_allocated_height()
        scale = min(width / 430, height / 234)
        ctx.save()
        ctx.translate((width - 430 * scale) / 2, (height - 234 * scale) / 2)
        ctx.scale(scale, scale)
        # The heading accent follows the shell's current palette.
        accent = self.get_style_context().get_color(Gtk.StateFlags.NORMAL)
        rgb = (accent.red, accent.green, accent.blue)

        # Low graphite plinth and its machined edge.
        rounded(ctx, 18, 9, 394, 216, 15)
        plinth = cairo.LinearGradient(0, 9, 0, 225)
        plinth.add_color_stop_rgb(0, .12, .15, .18)
        plinth.add_color_stop_rgb(1, .065, .083, .10)
        ctx.set_source(plinth)
        ctx.fill_preserve()
        ctx.set_source_rgba(.40, .49, .55, .22)
        ctx.set_line_width(1)
        ctx.stroke()

        # Platter shadow, aluminium rim and the record itself.
        cx, cy, radius = 159, 116, 96
        circle(ctx, cx + 1, cy + 4, radius + 5)
        ctx.set_source_rgba(0, 0, 0, .45)
        ctx.fill()
        circle(ctx, cx, cy, radius + 3)
        ctx.set_source_rgb(.24, .29, .32)
        ctx.fill()
        circle(ctx, cx, cy, radius)
        ctx.set_source_rgb(.025, .030, .037)
        ctx.fill()
        for r in range(56, 95, 2):
            circle(ctx, cx, cy, r)
            ctx.set_source_rgba(.40, .47, .53, .12 if r % 4 else .19)
            ctx.set_line_width(.6)
            ctx.stroke()

        # Stationary reflections across the black grooves.
        ctx.save()
        ctx.translate(cx, cy)
        for angle in (-1.1, math.pi - 1.1):
            ctx.move_to(0, 0)
            ctx.arc(0, 0, radius - 2, angle, angle + .38)
            ctx.close_path()
            ctx.set_source_rgba(.70, .78, .84, .045)
            ctx.fill()
        ctx.rotate(self.angle())

        # Crop the real square cover to a circular paper label.
        ctx.save()
        circle(ctx, 0, 0, 53)
        ctx.clip()
        if self.cover:
            w, h = self.cover.get_width(), self.cover.get_height()
            factor = 106 / min(w, h)
            ctx.scale(factor, factor)
            Gdk.cairo_set_source_pixbuf(ctx, self.cover, -w / 2, -h / 2)
            ctx.paint()
        else:
            gradient = cairo.LinearGradient(-53, -53, 53, 53)
            gradient.add_color_stop_rgb(0, .15, .26, .31)
            gradient.add_color_stop_rgb(1, .07, .12, .17)
            ctx.set_source(gradient)
            ctx.paint()
            ctx.set_source_rgba(*rgb, .75)
            ctx.select_font_face('DejaVu Sans', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
            ctx.set_font_size(39)
            ctx.move_to(-17, 14)
            ctx.show_text('♪')
        ctx.restore()
        circle(ctx, 0, 0, 54)
        ctx.set_source_rgba(.82, .88, .90, .28)
        ctx.set_line_width(1)
        ctx.stroke()
        # A small etched marker makes rotation visible with any cover.
        ctx.set_source_rgba(.80, .85, .87, .35)
        ctx.set_line_width(1.2)
        ctx.move_to(0, -89)
        ctx.line_to(0, -84)
        ctx.stroke()
        circle(ctx, 0, 0, 6)
        ctx.set_source_rgb(.06, .07, .08)
        ctx.fill()
        circle(ctx, 0, 0, 2)
        ctx.set_source_rgb(.64, .69, .72)
        ctx.fill()
        ctx.restore()

        # Tonearm, parked to the right on pause; engaged over the grooves.
        ctx.save()
        ctx.translate(331, 47)
        if not self.playing:
            ctx.rotate(-.40)
        circle(ctx, 0, 0, 19)
        ctx.set_source_rgb(.10, .13, .15)
        ctx.fill_preserve()
        ctx.set_source_rgba(.55, .63, .67, .35)
        ctx.set_line_width(1)
        ctx.stroke()
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        for thickness, col in [(9, (.035, .045, .052)), (5, (.49, .56, .60)),
                               (1.4, (.80, .85, .88))]:
            ctx.move_to(0, 0)
            ctx.line_to(-36, 62)
            ctx.line_to(-84, 91)
            ctx.set_line_width(thickness)
            ctx.set_source_rgb(*col)
            ctx.stroke()
        ctx.translate(-84, 91)
        ctx.rotate(.84)
        rounded(ctx, -7, -4, 14, 24, 3)
        ctx.set_source_rgb(.14, .20, .23)
        ctx.fill_preserve()
        ctx.set_source_rgba(*rgb, .8)
        ctx.set_line_width(1)
        ctx.stroke()
        ctx.restore()
        circle(ctx, 331, 47, 6)
        ctx.set_source_rgb(.55, .62, .66)
        ctx.fill()

        circle(ctx, 345, 199, 3)
        ctx.set_source_rgba(*rgb, .95 if self.playing else .23)
        ctx.fill()
        ctx.select_font_face('DejaVu Sans', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        ctx.set_font_size(9)
        ctx.set_source_rgba(.62, .69, .73, .65)
        ctx.move_to(361, 202)
        ctx.show_text('33⅓')
        ctx.restore()
        return False
