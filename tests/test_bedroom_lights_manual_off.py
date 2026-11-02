from copy import deepcopy
from datetime import time
import json
from pathlib import Path
import unittest

from scripts.bedroom_lights_manual_off import configurations, HELPER, SENSOR


class ManualOffTests(unittest.TestCase):
    def setUp(self):
        self.before = json.loads((Path(__file__).parent / 'fixtures/bedroom_lights_before_manual_off.json').read_text())
        self.main, self.hold = configurations(self.before)

    def actions(self, config, trigger, presence='on', hold='off', clock='12:00:00', empty_seconds=0):
        states = {SENSOR: presence, HELPER: hold}
        def passes(c):
            if c['condition'] == 'trigger': return c['id'] == trigger
            if c['condition'] == 'state':
                return states[c['entity_id']] == c['state'] and empty_seconds >= c.get('for', {}).get('minutes', 0) * 60
            if c['condition'] == 'time':
                return time.fromisoformat(c['after']) <= time.fromisoformat(clock) < time.fromisoformat(c['before'])
            raise AssertionError(c)
        for branch in config['actions'][0]['choose']:
            if all(passes(c) for c in branch['conditions']):
                return [a['action'] for a in branch['sequence']]
        return []

    def test_manual_off_holds_until_clear_and_reentry(self):
        self.assertEqual(self.actions(self.hold, 'manual_off'), ['input_boolean.turn_on'])
        self.assertEqual(self.actions(self.main, 'arrive', hold='on'), [])
        self.assertEqual(self.actions(self.hold, 'clear', presence='off', hold='on'), ['input_boolean.turn_off'])
        self.assertEqual(self.actions(self.main, 'arrive'), ['light.turn_on'])

    def test_automatic_off_while_empty_does_not_set_hold(self):
        self.assertEqual(self.actions(self.hold, 'manual_off', presence='off'), [])
        self.assertEqual(self.actions(self.main, 'empty', presence='off', hold='on', empty_seconds=300), ['light.turn_off'])

    def test_five_minute_timer_and_reentry(self):
        self.assertEqual(self.actions(self.main, 'empty', presence='off', empty_seconds=299), [])
        self.assertEqual(self.actions(self.main, 'empty', presence='on', empty_seconds=300), [])
        self.assertEqual(self.main['triggers'], self.before['triggers'])
        self.assertEqual(self.main['mode'], 'restart')

    def test_quiet_window_unchanged_and_off_allowed_at_night(self):
        for clock in ('23:00:00', '00:00:00', '06:39:59'):
            self.assertEqual(self.actions(self.main, 'arrive', clock=clock), [])
            self.assertEqual(self.actions(self.main, 'empty', presence='off', clock=clock, empty_seconds=300), ['light.turn_off'])
        for clock in ('06:40:00', '22:59:59'):
            self.assertEqual(self.actions(self.main, 'arrive', clock=clock), ['light.turn_on'])

    def test_unknown_or_startup_occupied_does_not_release_hold(self):
        for state in ('on', 'unknown', 'unavailable'):
            self.assertEqual(self.actions(self.hold, 'startup', presence=state, hold='on'), [])
        self.assertEqual(self.actions(self.hold, 'startup', presence='off', hold='on'), ['input_boolean.turn_off'])

    def test_minimal_patch_no_fan_or_light_actions_in_companion(self):
        expected = deepcopy(self.before)
        expected['actions'][0]['choose'][0]['conditions'].append({'condition':'state','entity_id':HELPER,'state':'off'})
        expected['description'] = self.main['description']
        self.assertEqual(self.main, expected)
        self.assertEqual(configurations(self.main)[0], self.main)
        for branch in self.hold['actions'][0]['choose']:
            for action in branch['sequence']:
                self.assertEqual(action['target']['entity_id'], HELPER)
                self.assertTrue(action['action'].startswith('input_boolean.'))
        trigger = self.hold['triggers'][0]
        self.assertEqual((trigger['from'], trigger['to']), ('on', 'off'))


if __name__ == '__main__':
    unittest.main()
