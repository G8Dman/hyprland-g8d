"""Audio output and playback streams via the PulseAudio protocol."""
import json
import subprocess

from bluetooth_battery import address

def pactl(*args):
    return subprocess.run(['pactl', *args], capture_output=True, text=True, check=True, timeout=3).stdout


def level(item):
    channels = [channel['value'] for channel in (item.get('volume') or {}).values()
                if isinstance(channel, dict) and isinstance(channel.get('value'), (int, float))]
    return round(sum(channels) * 100 / (len(channels) * 65536)) if channels else None


def applications(streams, outputs):
    by_index = {output['index']: output['name'] for output in outputs}
    groups = {}
    for stream in streams:
        properties = stream.get('properties') or {}
        name = properties.get('application.name') or properties.get('application.process.binary')
        key = next((properties[key] for key in ('application.id', 'application.process.binary', 'application.name')
                    if properties.get(key)), f"stream:{stream['index']}")
        group = groups.setdefault(key, {'key': key, 'name': name or 'Аудиопоток', 'streams': [],
                                        'outputs': set(), 'levels': [], 'writable': []})
        group['streams'].append(stream['index'])
        group['outputs'].add(by_index.get(stream['sink']))
        percent = level(stream)
        if percent is not None and stream.get('volume_writable', True) is not False:
            group['levels'].append(percent)
            group['writable'].append(stream['index'])
    for group in groups.values():
        group['output'] = next(iter(group['outputs'])) if len(group['outputs']) == 1 else None
        group['mixed'] = len(group['outputs']) > 1
        values = group['levels']
        group['volume'] = round(sum(values) / len(values)) if values else None
    return sorted(groups.values(), key=lambda group: (group['name'].casefold(), group['key']))


def snapshot(expanded):
    info = json.loads(pactl('-f', 'json', 'info'))
    outputs = [{'index': sink['index'], 'name': sink['name'], 'label': sink.get('description') or sink['name'],
                'volume': level(sink), 'muted': sink.get('mute', False), 'bluetooth': bluetooth_address(sink)}
               for sink in json.loads(pactl('-f', 'json', 'list', 'sinks'))]
    outputs.sort(key=lambda sink: sink['label'].casefold())
    default = next((sink for sink in outputs if sink['name'] == info.get('default_sink_name')), None)
    apps = applications(json.loads(pactl('-f', 'json', 'list', 'sink-inputs')), outputs) if expanded else None
    return default, outputs, apps


def bluetooth_address(sink):
    value = address((sink.get('properties') or {}).get('api.bluez5.address'))
    if value:
        return value
    name = sink['name'].split('.')
    return address(name[1]) if len(name) > 1 and name[0] == 'bluez_output' else None


def error_detail(error):
    return (getattr(error, 'stderr', '') or str(error)).strip()


def apply(edits, expanded):
    errors = []
    for message, commands in edits:
        for command in commands:
            try:
                pactl(*command)
            except (OSError, subprocess.SubprocessError) as exc:
                errors.append((message, error_detail(exc)))
    try:
        state = snapshot(expanded)
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as exc:
        return None, errors or [('Звуковая служба недоступна.', error_detail(exc))]
    return state, errors
