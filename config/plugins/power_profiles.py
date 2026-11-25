"""Use the system Power Profiles API, including TuneD's compatible service."""

PROFILES = ('power-saver', 'balanced', 'performance')
SERVICES = (
    ('org.freedesktop.UPower.PowerProfiles', '/org/freedesktop/UPower/PowerProfiles'),
    ('net.hadess.PowerProfiles', '/net/hadess/PowerProfiles'),
)


def exchange(target=None):
    from gi.repository import Gio, GLib

    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)
    for name, path in SERVICES:
        def call(method, args):
            return bus.call_sync(name, path, 'org.freedesktop.DBus.Properties',
                                 method, args, None, Gio.DBusCallFlags.NONE, 4000, None)

        try:
            data, = call('GetAll', GLib.Variant('(s)', (name,))).unpack()
        except GLib.Error as error:
            reason = Gio.DBusError.get_remote_error(error) or ''
            if reason.endswith(('.ServiceUnknown', '.NameHasNoOwner', '.UnknownInterface', '.UnknownObject')):
                continue
            raise
        if not data.get('Profiles'):
            continue
        active, available, warning = profile_state(data)
        if target is not None and target != active:
            if target not in available:
                raise RuntimeError('Этот профиль сейчас недоступен.')
            call('Set', GLib.Variant('(ssv)', (name, 'ActiveProfile', GLib.Variant('s', target))))
            data, = call('GetAll', GLib.Variant('(s)', (name,))).unpack()
            if data.get('ActiveProfile') != target:
                raise RuntimeError('Система не подтвердила смену профиля.')
            return profile_state(data)
        return active, available, warning
    return None, (), ''


def profile_state(data):
    reported = {item.get('Profile') for item in data['Profiles']}
    if data.get('PerformanceInhibited'):
        reported.discard('performance')
    return (data.get('ActiveProfile'), tuple(profile for profile in PROFILES if profile in reported),
            data.get('PerformanceDegraded') or '')
