"""Build HA Nap Mode configurations, without executing device actions."""
from copy import deepcopy

NAP = 'input_boolean.nap_mode'
DEADLINE = 'input_datetime.nap_mode_until'
SENSOR = 'binary_sensor.bedroom_presence_occupancy'
DURATION = 'input_number.nap_duration_hours'
DEFAULT_HOURS = 2
# Retained solely to recognize and remove the previous arrival bypass.
RETURN = "{{ trigger.from_state is defined and trigger.from_state is not none and trigger.to_state is defined and trigger.to_state is not none and trigger.from_state.state == 'off' and trigger.to_state.state == 'on' and (as_timestamp(trigger.to_state.last_changed) - as_timestamp(trigger.from_state.last_changed)) >= 300 }}"
EXPIRED = "{{ as_timestamp(states('input_datetime.nap_mode_until'), 0) > 0 and as_timestamp(states('input_datetime.nap_mode_until'), 0) <= as_timestamp(now()) }}"
PHONE_AWAY = "{{ trigger.to_state is defined and trigger.to_state is not none and trigger.to_state.state not in ['home', 'unknown', 'unavailable', ''] }}"
DEADLINE_TEMPLATE = "{{ as_timestamp(now()) + (states('input_number.nap_duration_hours') | float(2)) * 3600 }}"


def end_nap():
    return {'action': 'input_boolean.turn_off', 'target': {'entity_id': NAP}}


def guard_arrival(config):
    result = deepcopy(config)
    branches = [b for b in result['actions'][0]['choose']
                if {'condition': 'trigger', 'id': 'arrive'} in b['conditions']]
    if len(branches) != 1:
        raise ValueError('Expected exactly one arrival branch.')
    previous = {'condition': 'or', 'conditions': [
        {'condition': 'state', 'entity_id': NAP, 'state': 'off'},
        {'condition': 'template', 'value_template': RETURN},
    ]}
    guard = {'condition': 'state', 'entity_id': NAP, 'state': 'off'}
    branches[0]['conditions'] = [guard if c == previous else c for c in branches[0]['conditions']]
    if guard not in branches[0]['conditions']:
        branches[0]['conditions'].append(guard)
    return result


def configurations(existing, phone_entity=None):
    patched = {i: guard_arrival(existing[i]) for i in
               ('bedroom_lights_presence', 'bedroom_fan_on_when_back')}
    script = {
        'alias': 'Nap Mode', 'icon': 'mdi:sleep', 'mode': 'single',
        'description': 'Activate bedroom Nap Mode. The Nap Mode lifecycle turns off lights and the fan plug. Toggle Nap Mode off to end early.',
        'sequence': [{'action': 'input_boolean.turn_on', 'target': {'entity_id': NAP}}],
    }
    lifecycle = {
        'id': 'bedroom_nap_mode', 'alias': 'Bedroom - Nap Mode', 'mode': 'queued', 'max': 10,
        'description': 'Activation: off lights and fan plug, with a persistent adjustable timeout (default 2 hours). End only on manual toggle off, timeout, or verified phone departure if configured. Room absence and return never end a nap. Ending never forces devices on.',
        'triggers': [
            {'trigger': 'state', 'entity_id': NAP, 'from': 'off', 'to': 'on', 'id': 'activate'},
            {'trigger': 'time', 'at': DEADLINE, 'id': 'expiry'},
            {'trigger': 'time_pattern', 'minutes': '/1', 'id': 'expiry'},
            {'trigger': 'homeassistant', 'event': 'start', 'id': 'expiry'},
        ],
        'conditions': [],
        'actions': [{'choose': [
            {'conditions': [{'condition': 'trigger', 'id': 'activate'},
                            {'condition': 'state', 'entity_id': NAP, 'state': 'on'}],
             'sequence': [
                 {'action': 'input_datetime.set_datetime', 'target': {'entity_id': DEADLINE},
                  'data': {'timestamp': DEADLINE_TEMPLATE}},
                 {'action': 'light.turn_off', 'target': {'entity_id': ['light.ceiling_light', 'light.bedroom_lamp']}, 'continue_on_error': True},
                 {'action': 'switch.turn_off', 'target': {'entity_id': 'switch.bedroom_fan'}, 'continue_on_error': True},
             ]},
            {'conditions': [{'condition': 'trigger', 'id': 'expiry'},
                            {'condition': 'state', 'entity_id': NAP, 'state': 'on'},
                            {'condition': 'template', 'value_template': EXPIRED}],
             'sequence': [end_nap()]},
        ]}],
    }
    if phone_entity:
        lifecycle['triggers'].append({'trigger': 'state', 'entity_id': phone_entity,
                                      'from': 'home', 'id': 'phone_left'})
        lifecycle['actions'][0]['choose'].append({
            'conditions': [{'condition': 'trigger', 'id': 'phone_left'},
                           {'condition': 'state', 'entity_id': NAP, 'state': 'on'},
                           {'condition': 'template', 'value_template': PHONE_AWAY}],
            'sequence': [end_nap()],
        })
    dashboard = {'title': 'Bedroom Nap', 'views': [{
        'title': 'Nap Mode', 'path': 'nap', 'icon': 'mdi:sleep', 'cards': [
            {'type': 'button', 'name': 'Start Nap Mode', 'icon': 'mdi:sleep',
             'tap_action': {'action': 'perform-action', 'perform_action': 'script.turn_on', 'target': {'entity_id': 'script.nap_mode'}}},
            {'type': 'entities', 'title': 'Nap Mode', 'show_header_toggle': False,
             'entities': [NAP, {'entity': DURATION, 'name': 'Nap timeout (hours)'},
                          {'entity': DEADLINE, 'name': 'Automatic end', 'type': 'simple-entity'}]},
            {'type': 'markdown', 'content': 'Turns off bedroom lights and fan. Presence never switches them on during a nap. Ends only when you switch Nap Mode off, its timeout expires (default 2 hours), or your phone leaves home if configured. Set Nap timeout before starting; changing it does not shorten a nap already in progress. Ending does not force devices on.'},
        ]}]}
    return patched, script, lifecycle, dashboard
