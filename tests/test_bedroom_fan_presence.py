"""Regression coverage against the actual pre-change HA configuration."""
from copy import deepcopy
from datetime import time
import json
from pathlib import Path
import unittest

from scripts.bedroom_fan_presence import overnight_config, DAYTIME, MORNING


class OvernightTests(unittest.TestCase):
    def setUp(self):
        self.before = json.loads((Path(__file__).parent / 'fixtures/bedroom_fan_before_overnight.json').read_text())
        self.after = overnight_config(self.before)
        self.empty = self.after['actions'][0]['choose'][1]

    def permits_empty(self, local_time, state='off', seconds=60):
        # Evaluate the declarative HA time/state conditions, not a second scheduler.
        for c in self.empty['conditions']:
            if c['condition'] == 'time':
                if not time.fromisoformat(c['after']) <= time.fromisoformat(local_time) < time.fromisoformat(c['before']):
                    return False
            elif c['condition'] == 'state':
                if state != c['state'] or seconds < c['for']['minutes'] * 60:
                    return False
        return True

    def test_night_boundaries_and_daytime(self):
        for clock, expected in [('20:59:59', True), ('21:00:00', True), ('22:59:59', True),
                                ('23:00:00', False), ('23:40:00', False),
                                ('00:00:00', False), ('06:39:59', False), ('06:40:00', True), ('12:00:00', True)]:
            with self.subTest(clock=clock):
                self.assertEqual(self.permits_empty(clock), expected)

    def test_morning_does_not_turn_off_occupied_or_uncertain_room(self):
        for state in ('on', 'unknown', 'unavailable'):
            self.assertFalse(self.permits_empty('06:40:00', state))

    def test_morning_respects_full_minute(self):
        self.assertFalse(self.permits_empty('06:40:00', seconds=59))
        self.assertTrue(self.permits_empty('06:40:00', seconds=60))
        self.assertTrue(self.permits_empty('06:40:00', seconds=3600))

    def test_existing_empty_at_wake_has_time_trigger(self):
        self.assertIn(MORNING, self.after['triggers'])
        self.assertEqual(self.after['triggers'][:-1], self.before['triggers'])

    def test_arrive_and_manual_branches_unchanged(self):
        for index in (0, 2, 3):
            self.assertEqual(self.after['actions'][0]['choose'][index], self.before['actions'][0]['choose'][index])
        self.assertEqual(self.after['conditions'], [])  # No global guard blocks manual controls.

    def test_only_empty_guards_and_morning_trigger_added(self):
        expected = deepcopy(self.before)
        expected['description'] = self.after['description']
        expected['triggers'].append(MORNING)
        expected['actions'][0]['choose'][1]['conditions'] += [DAYTIME, {
            'condition': 'state', 'entity_id': 'binary_sensor.bedroom_presence_occupancy',
            'state': 'off', 'for': {'minutes': 1}}]
        self.assertEqual(self.after, expected)

    def test_repeat_apply_is_idempotent_and_input_unchanged(self):
        original = deepcopy(self.before)
        self.assertEqual(overnight_config(self.after), self.after)
        self.assertEqual(self.before, original)

    def test_migrate_9pm_guard_instead_of_adding_another_condition(self):
        old = deepcopy(self.after)
        old['actions'][0]['choose'][1]['conditions'][1]['before'] = '21:00:00'
        old['description'] = old['description'].replace('23:00-', '21:00-')
        self.assertEqual(overnight_config(old), self.after)
        self.assertEqual(old['actions'][0]['choose'][1]['conditions'][1]['before'], '21:00:00')

    def test_unexpected_config_is_not_overwritten(self):
        for change in ('id', 'branch', 'target', 'duration'):
            config = deepcopy(self.before)
            if change == 'id': config['id'] = 'other'
            if change == 'branch': config['actions'][0]['choose'].pop(1)
            if change == 'target': config['actions'][0]['choose'][1]['sequence'][1]['target']['entity_id'] = 'fan.other'
            if change == 'duration': config['triggers'][1]['for']['minutes'] = 10
            with self.subTest(change=change), self.assertRaises(ValueError):
                overnight_config(config)


if __name__ == '__main__':
    unittest.main()
