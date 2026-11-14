#!/usr/bin/env python3
"""Repair existing SNI registrations after panel startup/reload, then exit."""
import sys
import time
import gi
gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib

bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
watcher = 'org.kde.StatusNotifierWatcher'
interface = 'org.kde.StatusNotifierWatcher'
path = '/StatusNotifierWatcher'

def call(service, object_path, iface, method, args):
    return bus.call_sync(service, object_path, iface, method, args, None,
                         Gio.DBusCallFlags.NONE, 1000, None).unpack()

def owner(name):
    return name if name.startswith(':') else call('org.freedesktop.DBus',
        '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'GetNameOwner', GLib.Variant('(s)', (name,)))[0]

for attempt in range(12):
    try:
        properties = call(watcher, path, 'org.freedesktop.DBus.Properties', 'GetAll',
                          GLib.Variant('(s)', (interface,)))[0]
        if properties.get('IsStatusNotifierHostRegistered'):
            break
    except GLib.Error:
        pass
    time.sleep(.25)
else:
    raise SystemExit(0)

seen = set()
for item in properties.get('RegisteredStatusNotifierItems', []):
    service, _, object_path = item.partition('/')
    try:
        seen.add((owner(service), '/' + object_path))
    except GLib.Error:
        pass
names = call('org.freedesktop.DBus', '/org/freedesktop/DBus',
             'org.freedesktop.DBus', 'ListNames', None)[0]
for service in names:
    if not service.startswith(':') or (service, '/StatusNotifierItem') in seen:
        continue
    try:
        item = call(service, '/StatusNotifierItem', 'org.freedesktop.DBus.Properties',
                    'GetAll', GLib.Variant('(s)', ('org.kde.StatusNotifierItem',)))[0]
        if 'Status' not in item or 'Id' not in item:
            continue
        call(watcher, path, interface, 'RegisterStatusNotifierItem', GLib.Variant('(s)', (service,)))
        print(f"g8d tray: restored {item.get('Id', service)}", file=sys.stderr)
    except GLib.Error:
        continue
