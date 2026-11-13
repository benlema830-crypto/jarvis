"""Home Assistant on the Raspberry Pi: control and read smart-home devices by name.

Needs HA_URL and HA_TOKEN (a long-lived access token) in .env. Talks only to that local
address, never through a proxy. Locks, alarms, garage doors and covers are left out on purpose.
"""
import os
import json
from pathlib import Path
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
WAKE_TIMEOUT = 25  # seconds a TV may take to boot after Wake-on-LAN
ACTIONS = ('turn_on', 'turn_off', 'toggle', 'set_brightness', 'set_color', 'set_volume', 'mute', 'unmute',
           'open_app') + tuple(MEDIA)
# What a media player must report supporting (Home Assistant feature bits) before an action is sent,
# so an unsupported request is refused instead of "succeeding" while nothing happens.
NEEDS = {'pause': 1, 'play_pause': 1, 'play': 16384, 'previous': 16, 'next': 32, 'set_volume': 4,
         'volume_up': 4 | 1024, 'volume_down': 4 | 1024, 'mute': 8, 'unmute': 8, 'open_app': 2048,
         'turn_on': 128, 'turn_off': 256}


class HomeError(RuntimeError):
    pass


DEFAULTS_PATH = Path(__file__).resolve().parent / 'data' / 'home-device-defaults.json'


def _name(text):
    """Case/spacing normalization only: brackets distinguish these TV names."""
    return ' '.join(text.casefold().split())


def _default(query):
    try:
        saved = json.loads(DEFAULTS_PATH.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise HomeError('Could not read the saved home-device defaults; no device was selected.') from None
    if not isinstance(saved, dict):
        raise HomeError('Invalid saved home-device defaults; no device was selected.')
    key = re.sub(r'^(?:the|my)\s+', '', _name(query))
    target = saved.get(key)
    if target is None:
        return None
    if (not isinstance(target, dict) or target.get('domain') not in DOMAINS
            or any(not isinstance(target.get(k), str) or not target[k].strip() for k in ('name', 'area'))):
        raise HomeError(f"Invalid saved default for '{query}'; no device was selected.")
    return target


def _exact(matches, query):
    # Prefer the player over a same-named remote, never one of two same-domain entities.
    rank = min(DOMAINS.index(d['domain']) for d in matches)
    preferred = [d for d in matches if DOMAINS.index(d['domain']) == rank]
    if len(preferred) != 1:
        raise HomeError(f"'{query}' could mean multiple entities: {', '.join(d['id'] for d in preferred)}. Which one?")
    return preferred


def _resolve_default(query, target, everything):
    candidates = [d for d in everything if d['domain'] == target['domain'] and _name(d['name']) == _name(target['name'])]
    if candidates:
        # Fresh effective area (entity override or device area), not a cached fuzzy
        # manufacturer/model string. Template rendering is read-only in HA.
        template = "{% for s in states %}{{ s.entity_id }}|{{ area_name(s.entity_id) or '' }}\n{% endfor %}"
        text = _api('POST', '/api/template', {'template': template})
        areas = dict(line.split('|', 1) for line in str(text).splitlines() if '|' in line)
        candidates = [d for d in candidates if _name(areas.get(d['id'], '')) == _name(target['area'])]
    if len(candidates) != 1:
        raise HomeError(f"Saved default for '{query}' needs exactly one {target['name']} in {target['area']}; "
                        "no device was selected. Check the name and room in Home Assistant.")
    return candidates


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


_DEVICE_INFO = "{% for s in states %}{{ s.entity_id }}|{{ area_name(s.entity_id) or '' }}|" \
               "{{ device_attr(s.entity_id, 'manufacturer') or '' }} {{ device_attr(s.entity_id, 'model') or '' }}" \
               "\n{% endfor %}"
_info = (0.0, {})


def _device_info():
    """(room, maker and model) per entity, so "Apple TV" finds a player named "Living Room"
    and "bedroom lights" finds every light in the Bedroom, whatever the bulbs are called."""
    global _info
    if time.monotonic() > _info[0]:
        text = _api('POST', '/api/template', {'template': _DEVICE_INFO})
        info = {}
        for line in str(text).splitlines():
            parts = line.split('|', 2)
            if len(parts) == 3:
                info[parts[0]] = (parts[1], parts[2])
        _info = (time.monotonic() + 300, info)
    return _info[1]


def _words(text):
    words = set(re.findall(r'[a-z0-9]+', text.lower()))
    if 'lge' in words:
        words.add('lg')
    if words & {'television', 'telly'}:
        words = (words - {'television', 'telly'}) | {'tv'}
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
    everything = [d for d in everything if d['domain'] in DOMAINS]
    # Explicit entity IDs and punctuation-preserving full names remain usable.
    exact_ids = [d for d in everything if _name(d['id']) == _name(query)]
    if exact_ids:
        return _exact(exact_ids, query)
    target = _default(query)
    if target is not None:
        return _resolve_default(query, target, everything)
    exact_names = [d for d in everything if _name(d['name']) == _name(query)]
    if exact_names:
        return _exact(exact_names, query)
    words = _words(query) - FILLER
    kinds = {KIND_WORDS[w] for w in words if w in KIND_WORDS}
    lamp = bool(words & {'lamp', 'lamps'})
    words -= set(KIND_WORDS)
    pool = [d for d in everything if not kinds or d['domain'] in kinds]
    if lamp:  # "the lamp" means a light named lamp, not every light
        pool = [d for d in pool if 'lamp' in _words(d['name'] + ' ' + d['id'])] or pool
    if not words:
        if kinds and pool:
            return _without_group_members(pool)
        raise HomeError(f"I couldn't find '{query}' in Home Assistant.")
    info = _device_info()
    scored = []
    for d in pool:
        area, maker = info.get(d['id'], ('', ''))
        named = _words(d['name'] + ' ' + d['id'].split('.', 1)[1]) | _words(area)
        if words <= named:  # the device's own name and its room count equally
            scored.append((2, d))
        elif words <= named | _words(maker):
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
    return _without_group_members(matches)


def _without_group_members(matches):
    """A light group and its own bulbs both match "the lights": send the command once, to the group."""
    grouped = set()
    for d in matches:
        members = d['attributes'].get('entity_id')
        if isinstance(members, list):
            grouped.update(members)
    return [d for d in matches if d['id'] not in grouped] or matches


def tiles(everything=None):
    """The devices worth a tile on the page: a group once instead of each of its members, and none of the
    option switches a light brings along (WLED adds "Sync send", "Sync receive" and "Nightlight" per strip,
    which filled the Home panel with eight tiles for two monitor backlights)."""
    everything = devices() if everything is None else everything
    lights = [d['name'].lower() for d in everything if d['domain'] == 'light']

    proper = {d['name'].lower() for d in everything if d['domain'] in ('fan', 'light', 'media_player', 'climate')}

    def option(d):
        name = d['name'].lower()
        if d['domain'] != 'switch':
            return False
        # ...or the plain plug behind a fan or lamp that already has a tile under the same name.
        return name in proper or any(name.startswith(light + ' ') for light in lights)
    return [d for d in _without_group_members(everything) if not option(d)]


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


def _wait_until_on(entity_id, timeout=None):
    """A TV woken over the network takes several seconds to boot before it accepts an app."""
    deadline = time.monotonic() + (WAKE_TIMEOUT if timeout is None else timeout)
    time.sleep(WAKE_SECONDS)
    while time.monotonic() < deadline:
        if _api('GET', f'/api/states/{entity_id}').get('state') not in ('off', 'unavailable'):
            time.sleep(WAKE_SECONDS)  # on, but give its app launcher a moment
            return
        time.sleep(1)
    raise HomeError("The TV didn't wake up. Check that 'Turn on via Wi-Fi' is enabled in the TV's settings.")


CONFIRM_SECONDS = 4        # lights and plugs report back within a second or two
SLOW_CONFIRM_SECONDS = 12  # a TV takes a while to boot or switch apps
CONFIRM_POLL = 0.3
OFF_STATES = ('off', 'standby', 'unavailable', 'unknown')


def _expectation(device, action, data):
    """(what success looks like, test on a device state), or None when Home Assistant can't report it.

    A service call only means the command was accepted: 'TV turned on' was said for a TV that stayed dark
    because the result only said it was sent. So the state is read back before anything is claimed."""
    before = device['state']
    if device['domain'] in ('scene', 'script') or device['attributes'].get('assumed_state'):
        return None
    attrs = lambda state: state.get('attributes') or {}
    if action == 'turn_on':
        return 'on', lambda s: s.get('state') not in OFF_STATES
    if action == 'turn_off':
        return 'off', lambda s: s.get('state') in ('off', 'standby')
    if action == 'toggle':
        return 'toggled', lambda s: s.get('state') != before and s.get('state') not in ('unavailable', 'unknown')
    if action == 'set_brightness':
        percent = data['brightness_pct']
        if percent == 0:
            return 'off', lambda s: s.get('state') == 'off'
        return f'at {percent}%', lambda s: s.get('state') == 'on' and \
            abs((attrs(s).get('brightness') or 0) / 2.55 - percent) <= 3
    if action == 'set_color':
        return "on (the color itself can't be read back)", lambda s: s.get('state') == 'on'
    if action == 'set_volume':
        level = data['volume_level']
        return f'at {round(level * 100)}% volume', lambda s: abs((attrs(s).get('volume_level') or 0) - level) <= 0.02
    if action in ('mute', 'unmute'):
        return ('muted' if action == 'mute' else 'unmuted'), lambda s: attrs(s).get('is_volume_muted') is (action == 'mute')
    if action == 'open_app':
        app = data['source']
        return f'showing {app}', lambda s: app in (attrs(s).get('source'), attrs(s).get('app_name'))
    if action == 'play':
        return 'playing', lambda s: s.get('state') == 'playing'
    if action == 'pause':
        return 'paused', lambda s: s.get('state') in ('paused', 'idle')
    return None  # next, previous, volume up/down, play/pause: nothing reliable to read back


def _read_back(pending, seconds):
    """Poll until each (device, description, test) passes or time runs out. Returns those that never did."""
    deadline = time.monotonic() + seconds
    while True:
        waiting = []
        for item in pending:
            try:
                state = _api('GET', f"/api/states/{item[0]['id']}")
            except HomeError:
                state = {}
            if not (isinstance(state, dict) and item[2](state)):
                waiting.append(item + (state.get('state') if isinstance(state, dict) else None,))
        pending = [item[:3] for item in waiting]
        if not pending or time.monotonic() >= deadline:
            return waiting
        time.sleep(CONFIRM_POLL)


def control(device, action, value=''):
    """Send the command, then read the device back. The result says what was actually observed."""
    if action not in ACTIONS:
        raise HomeError(f"Unknown action '{action}'.")
    targets = find(device)
    calls = [(d, *_service(d, action, value)) for d in targets]  # check them all before acting
    slow = False
    pending, already, unknown = [], [], []
    for d, domain, service, data in calls:
        expected = _expectation(d, action, data)
        if expected and action not in ('toggle', 'set_color') and expected[1](d):
            already.append(f"{d['name']} was already {expected[0]}")
        elif expected:
            pending.append((d, expected[0], expected[1]))
        else:
            unknown.append(d['name'])
        slow = slow or (d['domain'] == 'media_player' and action in ('turn_on', 'toggle', 'open_app'))
        if action == 'open_app' and d['state'] == 'off':  # "open Netflix" on a sleeping TV wakes it first
            _api('POST', '/api/services/media_player/turn_on', {'entity_id': d['id']})
            _wait_until_on(d['id'])
        _api('POST', f'/api/services/{domain}/{service}', dict(data, entity_id=d['id']))
    seconds = SLOW_CONFIRM_SECONDS if slow else CONFIRM_SECONDS
    failed = _read_back(pending, seconds) if pending else []
    failed_ids = {item[0]['id'] for item in failed}
    parts = []
    confirmed = [f"{d['name']} is {what}" for d, what, _ in pending if d['id'] not in failed_ids]
    if confirmed:
        parts.append('Confirmed: ' + '; '.join(confirmed) + '.')
    if already:
        parts.append('; '.join(already).capitalize() + ', so nothing changed.')
    if failed:
        said = '; '.join(f"{d['name']} should be {what} but reports {now or 'nothing'}" for d, what, _, now in failed)
        parts.append(f"NOT CONFIRMED after {seconds} seconds: {said}. The command was sent, but it did not visibly "
                     "work. Do not say it worked.")
    if unknown:
        parts.append(f"Sent {action.replace('_', ' ')} to {', '.join(unknown)}. Home Assistant can't report the result "
                     "of that, so say it was sent, not that it happened.")
    return ' '.join(parts)


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
