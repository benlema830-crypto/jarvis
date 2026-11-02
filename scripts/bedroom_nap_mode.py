"""Build HA Nap Mode configurations, without executing device actions."""
from copy import deepcopy

NAP = 'input_boolean.nap_mode'
DEADLINE = 'input_datetime.nap_mode_until'
SENSOR = 'binary_sensor.bedroom_presence_occupancy'
RETURN = "{{ trigger.from_state is defined and trigger.from_state is not none and trigger.to_state is defined and trigger.to_state is not none and trigger.from_state.state == 'off' and trigger.to_state.state == 'on' and (as_timestamp(trigger.to_state.last_changed) - as_timestamp(trigger.from_state.last_changed)) >= 300 }}"
EXPIRED = "{{ as_timestamp(states('input_datetime.nap_mode_until'), 0) <= as_timestamp(now()) }}"


def end_nap():
    return {'action': 'input_boolean.turn_off', 'target': {'entity_id': NAP}}


def guard_arrival(config):
    result = deepcopy(config)
    branches = [b for b in result['actions'][0]['choose']
                if {'condition': 'trigger', 'id': 'arrive'} in b['conditions']]
    if len(branches) != 1:
        raise ValueError('Expected exactly one arrival branch.')
    # A qualifying return is allowed even before the lifecycle automation has
    # cleared Nap Mode. This avoids races between independent HA automations.
    guard = {'condition': 'or', 'conditions': [
        {'condition': 'state', 'entity_id': NAP, 'state': 'off'},
        {'condition': 'template', 'value_template': RETURN},
    ]}
    if guard not in branches[0]['conditions']:
        branches[0]['conditions'].append(guard)
    return result


def configurations(existing):
    patched = {i: guard_arrival(existing[i]) for i in
               ('bedroom_lights_presence', 'bedroom_fan_on_when_back')}
    script = {
        'alias': 'Nap Mode', 'icon': 'mdi:sleep', 'mode': 'single',
        'description': 'Activate bedroom Nap Mode. The Nap Mode lifecycle turns off lights and the fan plug. Toggle Nap Mode off to end early.',
        'sequence': [{'action': 'input_boolean.turn_on', 'target': {'entity_id': NAP}}],
    }
    lifecycle = {
        'id': 'bedroom_nap_mode', 'alias': 'Bedroom - Nap Mode', 'mode': 'queued', 'max': 10,
        'description': 'Activation: off lights and fan plug, with a persistent 3-hour deadline. End on manual toggle off, or return after 5 continuous clear minutes. Recovery checks deadlines after reload/restart. Ending never forces devices on.',
        'triggers': [
            {'trigger': 'state', 'entity_id': NAP, 'from': 'off', 'to': 'on', 'id': 'activate'},
            {'trigger': 'state', 'entity_id': SENSOR, 'from': 'off', 'to': 'on', 'id': 'return'},
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
                  'data': {'timestamp': '{{ as_timestamp(now()) + 10800 }}'}},
                 {'action': 'light.turn_off', 'target': {'entity_id': ['light.ceiling_light', 'light.bedroom_lamp']}, 'continue_on_error': True},
                 {'action': 'switch.turn_off', 'target': {'entity_id': 'switch.bedroom_fan'}, 'continue_on_error': True},
             ]},
            {'conditions': [{'condition': 'trigger', 'id': 'return'},
                            {'condition': 'state', 'entity_id': NAP, 'state': 'on'},
                            {'condition': 'template', 'value_template': RETURN}],
             'sequence': [end_nap()]},
            {'conditions': [{'condition': 'trigger', 'id': 'expiry'},
                            {'condition': 'state', 'entity_id': NAP, 'state': 'on'},
                            {'condition': 'template', 'value_template': EXPIRED}],
             'sequence': [end_nap()]},
        ]}],
    }
    dashboard = {'title': 'Bedroom Nap', 'views': [{
        'title': 'Nap Mode', 'path': 'nap', 'icon': 'mdi:sleep', 'cards': [
            {'type': 'button', 'name': 'Start Nap Mode', 'icon': 'mdi:sleep',
             'tap_action': {'action': 'perform-action', 'perform_action': 'script.turn_on', 'target': {'entity_id': 'script.nap_mode'}}},
            {'type': 'entities', 'title': 'Nap Mode', 'show_header_toggle': False,
             'entities': [NAP, {'entity': DEADLINE, 'name': 'Automatic end', 'type': 'simple-entity'}]},
            {'type': 'markdown', 'content': 'Turns off the bedroom lights and fan. Ends after 3 hours, or when you return after 5 continuous minutes away. Turn the Nap Mode switch off to end early. Ending does not force devices on.'},
        ]}]}
    return patched, script, lifecycle, dashboard
