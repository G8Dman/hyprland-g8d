from gi.repository import GLib, Gtk

import power_profiles
from quick_settings import accessible, image, text


LABELS = ('Энергосбережение', 'Нормальный', 'Производительность')


def symbol(profile):
    if profile == 'balanced':
        return image('desktop-windows', 24)
    area = Gtk.DrawingArea()
    area.set_size_request(24, 24)
    area.set_halign(Gtk.Align.CENTER)
    area.set_valign(Gtk.Align.CENTER)

    def draw(widget, cr):
        style = widget.get_style_context()
        color = style.get_color(style.get_state())
        cr.set_source_rgba(color.red, color.green, color.blue, color.alpha)
        cr.set_line_width(1.7)
        cr.set_line_cap(1)
        cr.set_line_join(1)
        if profile == 'power-saver':
            cr.move_to(5, 19)
            cr.curve_to(2, 8, 10, 6, 21, 4)
            cr.curve_to(21, 16, 16, 21, 7, 18)
            cr.move_to(4, 21)
            cr.curve_to(9, 15, 13, 12, 17, 9)
        else:
            cr.move_to(9, 16)
            cr.curve_to(8, 9, 13, 4, 21, 3)
            cr.curve_to(21, 11, 16, 16, 9, 16)
            cr.close_path()
            cr.move_to(9, 10)
            cr.line_to(5, 11)
            cr.line_to(4, 15)
            cr.line_to(9, 15)
            cr.move_to(14, 15)
            cr.line_to(13, 19)
            cr.line_to(9, 20)
            cr.line_to(9, 16)
            cr.move_to(7, 18)
            cr.line_to(4, 21)
            cr.new_sub_path()
            cr.arc(15.5, 8.5, 1.3, 0, 6.283)
        cr.stroke()
        return False

    area.connect('draw', draw)
    return area


class PowerPanel:
    def __init__(self, popup):
        self.popup = popup
        self.root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.root.get_style_context().add_class('power-profiles')
        header = Gtk.Box(spacing=8)
        header.pack_start(text('Питание', 'quick-name'), False, False, 0)
        self.status = text('', 'power-status')
        self.status.set_xalign(1)
        self.status.set_line_wrap(True)
        header.pack_end(self.status, True, True, 0)
        self.root.pack_start(header, False, False, 0)
        self.buttons = {}
        self.active = None
        self.available = ()
        self.busy = False
        self.disposed = False
        self.rendering = False
        segments = Gtk.Box(homogeneous=True)
        segments.get_style_context().add_class('power-segments')
        for profile, title in zip(power_profiles.PROFILES, LABELS):
            button = Gtk.ToggleButton()
            button.set_size_request(82, 48)
            button.add(symbol(profile))
            button.connect('clicked', self.select, profile)
            self.buttons[profile] = button
            segments.pack_start(button, True, True, 0)
        self.root.pack_start(segments, False, False, 0)
        self.render('Проверяю профили…')

    def select(self, _, profile):
        if self.rendering:
            return
        if self.busy or profile not in self.available or profile == self.active:
            self.render()
            return
        self.refresh(profile)

    def refresh(self, target=None):
        if self.busy:
            return
        self.busy = True
        if target is not None or not self.available:
            self.render('Переключаю профиль…' if target else 'Проверяю профили…')
        future = self.popup.app.action_pool.submit(power_profiles.exchange, target)
        future.add_done_callback(lambda result: GLib.idle_add(self.complete, result, target))

    def complete(self, future, target):
        self.busy = False
        if self.disposed or future.cancelled():
            return GLib.SOURCE_REMOVE
        try:
            self.active, self.available, warning = future.result()
            self.render('Производительность ограничена системой.' if warning and self.active == 'performance' else '',
                        warning)
        except Exception as exc:
            if target is None:
                self.active, self.available = None, ()
            self.render('Не удалось сменить профиль.' if target else 'Профили питания недоступны.', str(exc))
        return GLib.SOURCE_REMOVE

    def render(self, message='', detail=''):
        self.rendering = True
        for (profile, button), title in zip(self.buttons.items(), LABELS):
            supported = profile in self.available
            button.set_active(profile == self.active)
            button.set_sensitive(supported and not self.busy)
            accessible(button, title, title if supported else title + ' · недоступно')
        self.rendering = False
        if not message:
            message = next((title for profile, title in zip(power_profiles.PROFILES, LABELS)
                            if profile == self.active), 'Профили питания недоступны.')
        self.status.set_text(message)
        self.status.set_tooltip_text(detail or None)
