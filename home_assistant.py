"""Home Assistant on the Raspberry Pi: control and read smart-home devices by name.

Needs HA_URL and HA_TOKEN (a long-lived access token) in .env. Talks only to that local
address, never through a proxy. Locks, alarms, garage doors and covers are left out on purpose.
"""
import os
import re
import time

import requests

# Device types Jarvis may control, in the order preferred when one device has several.
DOMAINS = ('light', 'switch', 'fan', 'media_player', 'remote', 'scene', 'script', 'input_boolean')
KIND_WORDS = {'light': 'light', 'lights': 'light', 'lamp': 'light', 'lamps': 'light',
              'plug': 'switch', 'plugs': 'switch', 'outlet': 'switch', 'outlets': 'switch',
              'fan': 'fan', 'fans': 'fan'}
FILLER = {'the', 'my', 'a', 'an', 'in', 'on', 'of', 'all', 'please', 'jarvis', 'room'}
MEDIA = {'play': 'media_play', 'pause': 'media_pause', 'play_pause': 'media_play_pause',
         'next': 'media_next_track', 'previous': 'media_previous_track',
         'volume_up': 'volume_up', 'volume_down': 'volume_down'}
WAKE_SECONDS = 2
ACTIONS = ('turn_on', 'turn_off', 'toggle', 'set_brightness', 'set_color', 'set_volume', 'mute', 'unmute',
           'open_app') + tuple(MEDIA)
# What a media player must report supporting (Home Assistant feature bits) before an action is sent,
# so an unsupported request is refused instead of "succeeding" while nothing happens.
NEEDS = {'pause': 1, 'play_pause': 1, 'play': 16384, 'previous': 16, 'next': 32, 'set_volume': 4,
         'volume_up': 4 | 1024, 'volume_down': 4 | 1024, 'mute': 8, 'unmute': 8, 'open_app': 2048,
         'turn_on': 128, 'turn_off': 256}


class HomeError(RuntimeError):
    pass


def _config():
    url, token = os.getenv('HA_URL', '').rstrip('/'), os.getenv('HA_TOKEN', '')
    if not url or not token:
        raise HomeError("Home Assistant isn't set up: add HA_URL and HA_TOKEN to .env.")
    return url, token


def _api(method, path, payload=None):
    url, token = _config()
    session = requests.Session()
    session.trust_env = False  # the Pi is on the local network; never send the token through a proxy
    try:
        response = session.request(method, url + path, json=payload, timeout=(3, 10), allow_redirects=False,
                                   headers={'Authorization': f'Bearer {token}'})
    except requests.RequestException:
        raise HomeError("I couldn't reach Home Assistant. Is the Pi on?") from None
    finally:
        session.close()
    if response.status_code == 401:
        raise HomeError('Home Assistant rejected the access token in .env.')
    if response.status_code >= 400:
        raise HomeError(f'Home Assistant refused that ({response.status_code}).')
    return response.json() if 'json' in response.headers.get('Content-Type', '') else response.text


_DEVICE_INFO = "{% for s in states %}{{ s.entity_id }}|{{ device_attr(s.entity_id, 'manufacturer') or '' }} " \
               "{{ device_attr(s.entity_id, 'model') or '' }} {{ area_name(s.entity_id) or '' }}\n{% endfor %}"
_info = (0.0, {})


def _device_info():
    """Maker, model and room per entity, so "Apple TV" finds a player named "Living Room"."""
    global _info
    if time.monotonic() > _info[0]:
        text = _api('POST', '/api/template', {'template': _DEVICE_INFO})
        info = dict(line.split('|', 1) for line in str(text).splitlines() if '|' in line)
        _info = (time.monotonic() + 300, info)
    return _info[1]


def _words(text):
    words = set(re.findall(r'[a-z0-9]+', text.lower()))
    if 'lge' in words:
        words.add('lg')
    return words


def devices():
    """Controllable entities: [{'id', 'name', 'domain', 'state', 'attributes'}]."""
    out = []
    for state in _api('GET', '/api/states'):
        domain = state['entity_id'].split('.')[0]
        if domain in DOMAINS:
            out.append({'id': state['entity_id'], 'domain': domain, 'state': state['state'],
                        'name': state['attributes'].get('friendly_name') or state['entity_id'],
                        'attributes': state['attributes']})
    return out


def find(query, everything=None):
    """The entities a spoken name means. "the lights" means every light; otherwise the best match."""
    everything = devices() if everything is None else everything
    words = _words(query) - FILLER
    kinds = {KIND_WORDS[w] for w in words if w in KIND_WORDS}
    words -= set(KIND_WORDS)
    pool = [d for d in everything if not kinds or d['domain'] in kinds]
    if not words:
        if kinds and pool:
            return pool
        raise HomeError(f"I couldn't find '{query}' in Home Assistant.")
    info = _device_info()
    scored = []
    for d in pool:
        named = _words(d['name'] + ' ' + d['id'].split('.', 1)[1])
        if words <= named:
            scored.append((2, d))
        elif words <= named | _words(info.get(d['id'], '')):
            scored.append((1, d))
    if not scored:
        raise HomeError(f"I couldn't find '{query}' in Home Assistant.")
    best = max(score for score, _ in scored)
    matches = [d for score, d in scored if score == best]
    # One physical device often has a player and a remote under the same name: keep the preferred one.
    by_name = {}
    for d in sorted(matches, key=lambda d: DOMAINS.index(d['domain'])):
        by_name.setdefault(d['name'], d)
    matches = list(by_name.values())
    if len(matches) > 1 and not kinds:
        raise HomeError(f"'{query}' could mean {', '.join(d['name'] for d in matches)}. Which one?")
    return matches


def _service(device, action, value):
    domain, state = device['domain'], device['state']
    if state == 'unavailable':
        raise HomeError(f"{device['name']} isn't responding to Home Assistant right now.")
    if domain == 'media_player':
        if state == 'off' and action not in ('turn_on', 'toggle', 'open_app'):
            raise HomeError(f"{device['name']} is off. Turn it on first.")
        need = NEEDS.get(action, 0)
        if need and not int(device['attributes'].get('supported_features') or 0) & need:
            raise HomeError(f"{device['name']} can't {action.replace('_', ' ')} through Home Assistant.")
    if action in ('turn_on', 'turn_off', 'toggle'):
        if domain in ('scene', 'script') and action != 'turn_on':
            raise HomeError(f"{device['name']} can only be turned on.")
        return domain, action, {}
    if action in ('set_brightness', 'set_color'):
        if domain != 'light':
            raise HomeError(f"{device['name']} isn't a light.")
        if action == 'set_brightness':
            return 'light', 'turn_on', {'brightness_pct': _percent(value)}
        if not value.strip():
            raise HomeError('Say which color.')
        return 'light', 'turn_on', {'color_name': value.strip().lower()}
    if domain != 'media_player':
        raise HomeError(f"{device['name']} isn't a media player.")
    if action == 'set_volume':
        return 'media_player', 'volume_set', {'volume_level': _percent(value) / 100}
    if action in ('mute', 'unmute'):
        return 'media_player', 'volume_mute', {'is_volume_muted': action == 'mute'}
    if action == 'open_app':
        return 'media_player', 'select_source', {'source': _app(device, value)}
    return 'media_player', MEDIA[action], {}


def _app(device, value):
    """The installed app (Home Assistant "source") the user named: exact name first, then partial."""
    def plain(text):
        return re.sub(r'\s+', ' ', str(text).replace('\xa0', ' ')).strip().lower()
    wanted, apps = plain(value), device['attributes'].get('source_list') or []
    if not wanted:
        raise HomeError('Say which app.')
    for match in ([a for a in apps if plain(a) == wanted],
                  sorted((a for a in apps if wanted in plain(a)), key=len)):
        if match:
            return match[0]
    raise HomeError(f"{device['name']} has no app called '{value}'.")


def _percent(value):
    try:
        return max(0, min(100, int(float(str(value).strip().rstrip('%')))))
    except ValueError:
        raise HomeError(f"'{value}' isn't a percentage.") from None


def control(device, action, value=''):
    if action not in ACTIONS:
        raise HomeError(f"Unknown action '{action}'.")
    targets = find(device)
    calls = [(d, *_service(d, action, value)) for d in targets]  # check them all before acting
    for d, domain, service, data in calls:
        if action == 'open_app' and d['state'] == 'off':  # "open Netflix" on a sleeping TV wakes it first
            _api('POST', '/api/services/media_player/turn_on', {'entity_id': d['id']})
            time.sleep(WAKE_SECONDS)
        _api('POST', f'/api/services/{domain}/{service}', dict(data, entity_id=d['id']))
    names = ', '.join(d['name'] for d in targets)
    if action == 'open_app':
        return f"Asked {names} to open {calls[0][3]['source']}."
    return f"Sent {action.replace('_', ' ')}{' ' + value if value else ''} to {names}."


def describe(d):
    a, parts = d['attributes'], [f"{d['name']}: {d['state']}"]
    if d['domain'] == 'light' and a.get('brightness') is not None:
        parts.append(f"brightness {round(a['brightness'] / 2.55)}%")
    if a.get('media_title'):
        parts.append(f"playing {a.get('media_artist', '') + ' - ' if a.get('media_artist') else ''}{a['media_title']}")
    if a.get('volume_level') is not None:
        parts.append(f"volume {round(a['volume_level'] * 100)}%")
    return ', '.join(parts)


def status(device=''):
    everything = devices()
    if device.strip():
        shown = find(device, everything)
    else:  # one line per device: a TV's player and remote share a name
        by_name = {}
        for d in sorted(everything, key=lambda d: DOMAINS.index(d['domain'])):
            by_name.setdefault(d['name'], d)
        shown = list(by_name.values())
    return '\n'.join(describe(d) for d in shown[:40]) or 'No controllable devices yet.'
