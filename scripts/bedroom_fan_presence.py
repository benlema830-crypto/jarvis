"""Maintain the existing HA fan automation; this is not a background controller.

Default: preview only. --apply backs up the live automation, adds overnight
protection, validates HA configuration and reloads automations. No fan commands.
"""
import argparse
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
AUTOMATION_ID = 'bedroom_fan_on_when_back'
AUTOMATION_ENTITY = 'automation.bedroom_fan_back_on_when_you_return'
PRESENCE = 'binary_sensor.bedroom_presence_occupancy'
DAYTIME = {'condition': 'time', 'after': '06:40:00', 'before': '23:00:00'}
PREVIOUS_DAYTIME = {**DAYTIME, 'before': '21:00:00'}
MORNING = {'trigger': 'time', 'at': '06:40:00', 'id': 'empty'}
EMPTY = {'condition': 'state', 'entity_id': PRESENCE, 'state': 'off', 'for': {'minutes': 1}}
NOTE = ' Presence auto-off is suppressed nightly 23:00-06:40 (HA local time); at 06:40 recheck one continuous empty minute. Manual and wake-up commands remain available.'


def overnight_config(original):
    """Patch only the known empty branch, fail closed on an unexpected shape."""
    result = deepcopy(original)
    if result.get('id') != AUTOMATION_ID:
        raise ValueError('Unexpected automation ID; no change made.')
    branches = result.get('actions', [{}])[0].get('choose', [])
    empty = [b for b in branches if {'condition': 'trigger', 'id': 'empty'} in b.get('conditions', [])]
    if len(empty) != 1:
        raise ValueError('Expected exactly one empty-room branch; inspect live automation.')
    branch = empty[0]
    off = [a for a in branch.get('sequence', []) if a.get('action') == 'fan.turn_off']
    if len(off) != 1 or off[0].get('target', {}).get('entity_id') != 'fan.bedroom_fan':
        raise ValueError('Unexpected fan-off action; inspect live automation.')
    triggers = result.get('triggers', [])
    if not any(t.get('id') == 'empty' and t.get('entity_id') == PRESENCE
               and t.get('to') == 'off' and t.get('for') == {'minutes': 1} for t in triggers):
        raise ValueError('Expected existing one-minute absence trigger.')
    # Replace the previous guard: adding a second AND condition would still
    # suppress auto-off at 21:00 instead of moving the boundary to 23:00.
    branch['conditions'] = [deepcopy(DAYTIME) if c == PREVIOUS_DAYTIME else c
                            for c in branch['conditions']]
    for condition in (DAYTIME, EMPTY):
        if condition not in branch['conditions']:
            branch['conditions'].append(deepcopy(condition))
    if MORNING not in triggers:
        triggers.append(deepcopy(MORNING))
    result['description'] = result.get('description', '').replace(NOTE.replace('23:00-', '21:00-'), NOTE)
    if NOTE not in result.get('description', ''):
        result['description'] = result.get('description', '') + NOTE
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    from dotenv import load_dotenv
    import home_assistant as ha
    load_dotenv(ROOT / '.env')
    endpoint = '/api/config/automation/config/' + AUTOMATION_ID
    before = ha._api('GET', endpoint)
    after = overnight_config(before)
    if not args.apply:
        print(json.dumps(after, indent=2))
        return
    folder = ROOT / 'data/reports' / ('bedroom-fan-overnight-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    folder.mkdir(parents=True)
    def save(name, data):
        (folder / name).write_text(json.dumps(data, indent=2), encoding='utf-8')
    save('before.json', before)
    save('proposed.json', after)
    if ha._api('GET', endpoint) != before:
        raise RuntimeError('Automation changed while preparing; retry after reviewing.')
    # Explicit --apply is required; a saved report never grants authorization.
    ha._api('POST', endpoint, after)
    check = ha._api('POST', '/api/config/core/check_config', {})
    save('config-check.json', check)
    if check.get('result') != 'valid':
        raise RuntimeError('HA config check was not valid. Inspect backup and config-check report before continuing.')
    ha._api('POST', '/api/services/automation/reload', {})
    readback = ha._api('GET', endpoint)
    save('after.json', readback)
    if readback != after:
        raise RuntimeError('Automation readback differs from saved configuration.')
    state = ha._api('GET', '/api/states/' + AUTOMATION_ENTITY)
    save('state-after.json', state)
    if state['state'] != 'on':
        raise RuntimeError('Configuration saved, but automation is not enabled.')
    print('Saved, config valid, reloaded and enabled. Backup/report: ' + str(folder))


if __name__ == '__main__':
    main()
