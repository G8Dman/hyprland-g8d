"""Asynchronous BlueZ operations for the quick settings panel."""
from gi.repository import Gio, GLib

from bluetooth_battery import BATTERY, BatteryMonitor, address, percentage

BLUEZ = 'org.bluez'
ADAPTER = BLUEZ + '.Adapter1'
DEVICE = BLUEZ + '.Device1'
AGENT = BLUEZ + '.Agent1'
AGENT_MANAGER = BLUEZ + '.AgentManager1'
AGENT_PATH = '/org/g8d/BluetoothAgent'
AGENT_XML = """<node><interface name="org.bluez.Agent1">
  <method name="Release"/>
  <method name="Cancel"/>
  <method name="RequestPinCode"><arg type="o"/><arg type="s" direction="out"/></method>
  <method name="RequestPasskey"><arg type="o"/><arg type="u" direction="out"/></method>
  <method name="DisplayPinCode"><arg type="o"/><arg type="s"/></method>
  <method name="DisplayPasskey"><arg type="o"/><arg type="u"/><arg type="q"/></method>
  <method name="RequestConfirmation"><arg type="o"/><arg type="u"/></method>
  <method name="RequestAuthorization"><arg type="o"/></method>
  <method name="AuthorizeService"><arg type="o"/><arg type="s"/></method>
</interface></node>"""


def properties(proxy, *keys):
    return {key: value.unpack() for key in keys if (value := proxy.get_cached_property(key)) is not None}


class Bluetooth:
    def __init__(self, pool=None):
        self.view = None
        self.manager = None
        self.loading = False
        self.refresh_id = 0
        self.scan_adapter = None
        self.scan_pending = False
        self.scan_wanted = False
        self.scan_timer = 0
        self.nearby = set()
        self.operation = None
        self.pairing = None
        self.agent_id = 0
        self.agent_registered = False
        self.prompt = None
        self.batteries = BatteryMonitor(pool, self.changed) if pool else None

    def open(self, view):
        self.view = view
        if self.manager is not None or self.loading:
            self.changed()
            return
        self.loading = True
        self.changed()
        Gio.DBusObjectManagerClient.new_for_bus(
            Gio.BusType.SYSTEM, Gio.DBusObjectManagerClientFlags.DO_NOT_AUTO_START,
            BLUEZ, '/', None, None, None, self.ready)

    def ready(self, _, result):
        self.loading = False
        try:
            self.manager = Gio.DBusObjectManagerClient.new_for_bus_finish(result)
        except GLib.Error:
            self.changed()
            return
        for signal in ('interface-proxy-properties-changed', 'object-added', 'object-removed',
                       'interface-added', 'interface-removed'):
            self.manager.connect(signal, self.queue_update)
        self.manager.connect('notify::name-owner', self.owner_changed)
        self.changed()

    def owner_changed(self, *_):
        self.agent_registered = False
        self.stop_scan()
        self.changed()

    def queue_update(self, *_):
        if self.view and not self.refresh_id:
            self.refresh_id = GLib.timeout_add(100, self.flush_update)

    def flush_update(self):
        self.refresh_id = 0
        return self.changed()

    def snapshot(self):
        if self.manager is None:
            return 'loading' if self.loading else 'unavailable', None, []
        adapters, devices = [], []
        for obj in self.manager.get_objects():
            path = obj.get_object_path()
            adapter = obj.get_interface(ADAPTER)
            if adapter:
                adapters.append((path, properties(adapter, 'Powered').get('Powered', False)))
            device = obj.get_interface(DEVICE)
            if device:
                state = properties(device, 'Adapter', 'Alias', 'Name', 'Address', 'Icon',
                                   'Paired', 'Connected', 'RSSI')
                state['path'] = path
                if state.get('Connected'):
                    mac = address(state.get('Address'))
                    levels = dict(self.batteries.values.get(mac, {})) if self.batteries else {}
                    battery = obj.get_interface(BATTERY)
                    total = percentage(properties(battery, 'Percentage').get('Percentage')) if battery else None
                    if total is not None:
                        levels['total'] = total
                    state['battery'] = levels
                devices.append(state)
        if not adapters:
            return 'unavailable', None, []
        adapters.sort(key=lambda entry: (not entry[1], entry[0]))
        path, powered = adapters[0]
        devices = [device for device in devices if device.get('Adapter') == path]
        if self.scan_wanted:
            self.nearby.update(device['path'] for device in devices if 'RSSI' in device)
        return ('on' if powered else 'off'), path, [
            device for device in devices
            if device.get('Connected') or device.get('Paired') or device['path'] in self.nearby]

    def changed(self):
        if self.view:
            power, _, devices = self.snapshot()
            if self.scan_wanted and power != 'on':
                self.stop_scan()
                return GLib.SOURCE_REMOVE
            if self.batteries:
                self.batteries.watch(device.get('Address') for device in devices if device.get('Connected'))
            self.view.update(power, devices, self.scan_wanted, self.scan_pending, self.operation)
        return GLib.SOURCE_REMOVE

    def call(self, path, interface, method, args=None, *, timeout=15000, done=None):
        connection = self.manager.get_connection()

        def finished(bus, result):
            try:
                bus.call_finish(result)
                error = None
            except GLib.Error as exc:
                error = Gio.DBusError.get_remote_error(exc) or exc.message
            if done:
                done(error)

        connection.call(BLUEZ, path, interface, method, args, None,
                        Gio.DBusCallFlags.NO_AUTO_START, timeout, None, finished)

    def close(self, view):
        if self.view is not view:
            return
        self.stop_scan()
        self.cancel_pairing()
        self.nearby.clear()
        self.view = None
        if self.batteries:
            self.batteries.watch()

    def toggle_scan(self):
        if self.scan_wanted:
            self.stop_scan()
            return
        power, path, _ = self.snapshot()
        if power != 'on' or self.scan_pending:
            return
        self.nearby.clear()
        self.scan_wanted = True
        self.scan_pending = True
        self.changed()

        def started(error):
            self.scan_pending = False
            if error:
                self.scan_wanted = False
                self.show_error('Не удалось начать поиск', error)
            else:
                self.scan_adapter = path
                if self.scan_wanted:
                    self.scan_timer = GLib.timeout_add_seconds(15, self.scan_expired)
                else:
                    self.stop_scan()
            self.changed()

        self.call(path, ADAPTER, 'StartDiscovery', done=started)

    def scan_expired(self):
        self.scan_timer = 0
        self.stop_scan()
        return GLib.SOURCE_REMOVE

    def stop_scan(self):
        self.scan_wanted = False
        if self.scan_timer:
            GLib.source_remove(self.scan_timer)
            self.scan_timer = 0
        if self.scan_adapter:
            path, self.scan_adapter = self.scan_adapter, None
            self.scan_pending = True

            def stopped(error):
                self.scan_pending = False
                self.changed()

            self.call(path, ADAPTER, 'StopDiscovery', done=stopped)
        self.changed()

    def power_on(self):
        power, path, _ = self.snapshot()
        if power != 'off' or self.operation:
            return
        self.operation = path
        self.changed()
        self.call(path, 'org.freedesktop.DBus.Properties', 'Set',
                  GLib.Variant('(ssv)', (ADAPTER, 'Powered', GLib.Variant('b', True))),
                  done=lambda error: self.complete('Не удалось включить Bluetooth', error))

    def activate(self, device):
        if self.operation:
            return
        path = self.operation = device['path']
        self.changed()
        if device.get('Connected'):
            self.call(path, DEVICE, 'Disconnect',
                      done=lambda error: self.complete('Не удалось отключить устройство', error))
        elif device.get('Paired'):
            self.connect_device(path)
        else:
            self.pairing = path
            self.ensure_agent(lambda error: self.begin_pair(path, error))

    def ensure_agent(self, done):
        if self.agent_registered:
            done(None)
            return
        if not self.agent_id:
            info = Gio.DBusNodeInfo.new_for_xml(AGENT_XML)
            self.agent_id = self.manager.get_connection().register_object(
                AGENT_PATH, info.interfaces[0], self.agent_call, None, None)

        def registered(error):
            self.agent_registered = not error
            done(error)

        self.call('/org/bluez', AGENT_MANAGER, 'RegisterAgent',
                  GLib.Variant('(os)', (AGENT_PATH, 'KeyboardDisplay')), done=registered)

    def begin_pair(self, path, error):
        if self.pairing != path or error:
            self.complete('Не удалось подготовить сопряжение', error)
            return

        def paired(failure):
            canceled = self.pairing != path
            self.clear_prompt()
            if canceled or (failure and not failure.endswith('.AlreadyExists')):
                self.complete('Не удалось сопрячь устройство', None if canceled else failure)
            else:
                _, _, devices = self.snapshot()
                if any(item['path'] == path and item.get('Connected') for item in devices):
                    self.complete('', None)
                else:
                    self.connect_device(path)

        self.call(path, DEVICE, 'Pair', timeout=90000, done=paired)

    def connect_device(self, path):
        self.call(path, DEVICE, 'Connect', timeout=30000,
                  done=lambda error: self.complete('Не удалось подключить устройство', error))

    def cancel_pairing(self):
        if self.pairing:
            path, self.pairing = self.pairing, None
            self.clear_prompt()
            self.call(path, DEVICE, 'CancelPairing')

    def complete(self, title, error):
        self.operation = self.pairing = None
        self.clear_prompt()
        if error and not error.endswith(('.AlreadyConnected', '.NotConnected')):
            self.show_error(title, error)
        self.changed()

    def show_error(self, title, error):
        if self.view:
            self.view.error(title, error)

    def clear_prompt(self):
        if self.prompt:
            invocation, self.prompt = self.prompt, None
            invocation.return_dbus_error(BLUEZ + '.Error.Canceled', 'Pairing was canceled')
        if self.view:
            self.view.clear_prompt()

    def agent_call(self, _, sender, path, interface, method, parameters, invocation):
        args = parameters.unpack()
        if sender != self.manager.get_name_owner() or (args and (not self.view or args[0] != self.pairing)):
            invocation.return_dbus_error(BLUEZ + '.Error.Rejected', 'No active pairing request')
            return
        if method in ('Release', 'Cancel'):
            if method == 'Release':
                self.agent_registered = False
            self.clear_prompt()
            invocation.return_value(None)
        elif method in ('DisplayPinCode', 'DisplayPasskey'):
            self.view.ask(method, args[1:], None)
            invocation.return_value(None)
        else:
            self.clear_prompt()
            self.prompt = invocation

            def reply(accept, value):
                self.prompt = None
                if not accept:
                    invocation.return_dbus_error(BLUEZ + '.Error.Rejected', 'Pairing was declined')
                elif method == 'RequestPinCode':
                    invocation.return_value(GLib.Variant('(s)', (value,)))
                elif method == 'RequestPasskey':
                    invocation.return_value(GLib.Variant('(u)', (int(value),)))
                else:
                    invocation.return_value(None)
                self.view.clear_prompt()

            self.view.ask(method, args[1:], reply)
