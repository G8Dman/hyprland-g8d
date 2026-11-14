import subprocess


def run(args, timeout=15, input_text=None):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, input=input_text)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'Не удалось выполнить действие')
    return result.stdout.strip()


def fields(line):
    result = []
    value = ''
    escaped = False
    for char in line:
        if escaped:
            value += char
            escaped = False
        elif char == '\\':
            escaped = True
        elif char == ':':
            result.append(value)
            value = ''
        else:
            value += char
    if escaped:
        value += '\\'
    result.append(value)
    return result


def device_name(runner=run):
    for line in runner(['nmcli', '-t', '-f', 'DEVICE,TYPE', 'device']).splitlines():
        values = fields(line)
        if len(values) == 2 and values[1] == 'wifi':
            return values[0]
    raise RuntimeError('Wi-Fi адаптер не найден')


def saved_ssids(runner=run):
    saved = set()
    profiles = runner(['nmcli', '-t', '-f', 'UUID,TYPE', 'connection', 'show'])
    for line in profiles.splitlines():
        values = fields(line)
        if len(values) != 2 or values[1] != '802-11-wireless':
            continue
        details = runner(['nmcli', '-t', '-f', '802-11-wireless.ssid',
                          'connection', 'show', 'uuid', values[0]])
        for detail in details.splitlines():
            pair = fields(detail)
            if len(pair) == 2 and pair[0] == '802-11-wireless.ssid' and pair[1]:
                saved.add(pair[1])
    return saved


def scan(rescan=False, runner=run):
    device = device_name(runner)
    saved = saved_ssids(runner)
    output = runner(['nmcli', '-t', '-f', 'IN-USE,SSID,SIGNAL,SECURITY',
                     'device', 'wifi', 'list', 'ifname', device,
                     '--rescan', 'yes' if rescan else 'no'])
    networks = {}
    for line in output.splitlines():
        values = fields(line)
        if len(values) != 4 or not values[1]:
            continue
        try:
            signal = int(values[2])
        except ValueError:
            signal = 0
        network = {'ssid': values[1], 'signal': signal,
                   'security': '' if values[3] == '--' else values[3],
                   'active': values[0] == '*', 'saved': values[1] in saved}
        previous = networks.get(network['ssid'])
        if previous is None or network['active'] or (not previous['active'] and signal > previous['signal']):
            networks[network['ssid']] = network
    ordered = sorted(networks.values(), key=lambda item: (not item['active'], -item['signal'], item['ssid'].casefold()))
    return {'device': device, 'networks': ordered}


def needs_password(network):
    security = network.get('security', '')
    return bool(security) and not security.startswith('OWE') and not network.get('saved', False)


def connect(ssid, device, password=None, runner=run):
    command = ['nmcli', '--wait', '45']
    input_text = None
    if password is not None:
        if not password:
            raise ValueError('Введите пароль сети')
        command.append('--ask')
        input_text = password + '\n'
    command += ['device', 'wifi', 'connect', ssid, 'ifname', device]
    return runner(command, timeout=60, input_text=input_text)


def disconnect(device, runner=run):
    return runner(['nmcli', 'device', 'disconnect', device], timeout=30)
