"""Build the scoped HA bedroom-light manual-off configuration; no network calls."""
from copy import deepcopy

HELPER = 'input_boolean.bedroom_lights_manual_off'
SENSOR = 'binary_sensor.bedroom_presence_occupancy'
LIGHTS = ['light.ceiling_light', 'light.bedroom_lamp']
HOLD_ID = 'bedroom_lights_manual_off_hold'


def configurations(current):
    result = deepcopy(current)
    if result.get('id') != 'bedroom_lights_presence':
        raise ValueError('Unexpected lighting automation.')
    choices = result['actions'][0]['choose']
    arrivals = [b for b in choices if {'condition': 'trigger', 'id': 'arrive'} in b['conditions']]
    if len(arrivals) != 1:
        raise ValueError('Expected one arrival branch.')
    guard = {'condition': 'state', 'entity_id': HELPER, 'state': 'off'}
    if guard not in arrivals[0]['conditions']:
        arrivals[0]['conditions'].append(guard)
    note = ' Manual off while occupied holds auto-on until the next clear state.'
    if note not in result.get('description', ''):
        result['description'] = result.get('description', '') + note
    hold = {
        'id': HOLD_ID, 'alias': 'Bedroom Lights - Manual Off Hold',
        'description': 'An on-to-off light change while occupied holds presence auto-on. Any clear state releases it; no light commands. Startup clears a stale hold only if the room is clear.',
        'triggers': [
            {'trigger': 'state', 'entity_id': LIGHTS, 'from': 'on', 'to': 'off', 'id': 'manual_off'},
            {'trigger': 'state', 'entity_id': SENSOR, 'to': 'off', 'id': 'clear'},
            {'trigger': 'homeassistant', 'event': 'start', 'id': 'startup'},
        ],
        'conditions': [],
        'actions': [{'choose': [
            {'conditions': [
                {'condition': 'trigger', 'id': 'manual_off'},
                {'condition': 'state', 'entity_id': SENSOR, 'state': 'on'},
            ], 'sequence': [{'action': 'input_boolean.turn_on', 'target': {'entity_id': HELPER}}]},
            {'conditions': [{'condition': 'trigger', 'id': 'clear'}],
             'sequence': [{'action': 'input_boolean.turn_off', 'target': {'entity_id': HELPER}}]},
            {'conditions': [
                {'condition': 'trigger', 'id': 'startup'},
                {'condition': 'state', 'entity_id': SENSOR, 'state': 'off'},
            ], 'sequence': [{'action': 'input_boolean.turn_off', 'target': {'entity_id': HELPER}}]},
        ]}],
        'mode': 'queued', 'max': 20,
    }
    return result, hold
