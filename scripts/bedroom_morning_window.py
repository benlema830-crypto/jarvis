"""Keep the bedroom's presence automations from fighting the weekday alarm (6:40-7:10).

The presence sensor flickers on and off while the owner sleeps. Without this, each flicker after 6:40 turns
the fan on (the 6:40 recheck has just cleared the manual-off hold), and five quiet minutes turn the alarm's
lights off. Inside the window: presence never turns the fan on and never turns the lights off. A 7:10 check
then turns the lights off if the room has really been empty. Voice and manual control work as usual.

Default: preview only. --apply backs up both automations, saves, reloads and reads them back.
"""
import argparse
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
FAN_ID = 'bedroom_fan_on_when_back'
LIGHTS_ID = 'bedroom_lights_presence'
WINDOW = {'condition': 'time', 'after': '06:40:00', 'before': '07:10:00',
          'weekday': ['mon', 'tue', 'wed', 'thu', 'fri']}
OUTSIDE_WINDOW = {'condition': 'not', 'conditions': [WINDOW]}
LIGHTS_RECHECK = {'trigger': 'time', 'at': '07:10:00', 'id': 'empty'}
FAN_NOTE = ' Weekdays 06:40-07:10 presence never turns the fan on, so the morning alarm stays fan-free.'
LIGHTS_NOTE = (' Weekdays 06:40-07:10 presence never turns the lights off, so a sleeper the sensor misses keeps the '
               "alarm's lights; 07:10 rechecks five clear minutes.")


def _branch(config, trigger_id, action):
    """The one choose branch for this trigger that runs this action; fail closed on an unexpected shape."""
    found = [b for b in config.get('actions', [{}])[0].get('choose', [])
             if {'condition': 'trigger', 'id': trigger_id} in b.get('conditions', [])
             and any(a.get('action') == action for a in b.get('sequence', []))]
    if len(found) != 1:
        raise ValueError(f'Expected one {trigger_id}/{action} branch in {config.get("id")}; no change made.')
    return found[0]


def _guard(branch):
    if OUTSIDE_WINDOW not in branch['conditions']:
        branch['conditions'].append(deepcopy(OUTSIDE_WINDOW))


def _note(config, note):
    if note not in config.get('description', ''):
        config['description'] = config.get('description', '') + note


def fan_config(original):
    result = deepcopy(original)
    if result.get('id') != FAN_ID:
        raise ValueError('Unexpected automation ID; no change made.')
    _guard(_branch(result, 'arrive', 'fan.turn_on'))
    _note(result, FAN_NOTE)
    return result


def lights_config(original):
    result = deepcopy(original)
    if result.get('id') != LIGHTS_ID:
        raise ValueError('Unexpected automation ID; no change made.')
    _guard(_branch(result, 'empty', 'light.turn_off'))
    if LIGHTS_RECHECK not in result['triggers']:
        result['triggers'].append(deepcopy(LIGHTS_RECHECK))
    _note(result, LIGHTS_NOTE)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    from dotenv import load_dotenv
    import home_assistant as ha
    load_dotenv(ROOT / '.env')
    changes = []
    for automation_id, patch in ((FAN_ID, fan_config), (LIGHTS_ID, lights_config)):
        endpoint = '/api/config/automation/config/' + automation_id
        before = ha._api('GET', endpoint)
        changes.append((automation_id, endpoint, before, patch(before)))  # both validated before either is saved
    if not args.apply:
        print(json.dumps([c[3] for c in changes], indent=2))
        return
    folder = ROOT / 'data/reports' / ('bedroom-morning-window-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    folder.mkdir(parents=True)
    for automation_id, _, before, _after in changes:
        (folder / f'{automation_id}-before.json').write_text(json.dumps(before, indent=2), encoding='utf-8')
    for _, endpoint, _before, after in changes:
        ha._api('POST', endpoint, after)
    check = ha._api('POST', '/api/config/core/check_config', {})
    if check.get('result') != 'valid':
        raise RuntimeError(f'HA config check failed: {check}. Backups are in {folder}.')
    ha._api('POST', '/api/services/automation/reload', {})
    for automation_id, endpoint, _before, after in changes:
        if ha._api('GET', endpoint) != after:
            raise RuntimeError(f'{automation_id} read back differently. Backups are in {folder}.')
    print('Saved, valid and reloaded. Backups: ' + str(folder))


if __name__ == '__main__':
    main()
