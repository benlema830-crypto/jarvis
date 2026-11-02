from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from jinja2 import Environment
import home_assistant as ha
from scripts.bedroom_nap_mode import configurations, RETURN, NAP, DEADLINE


class NapTests(unittest.TestCase):
    def setUp(self):
        self.before = json.loads((Path(__file__).parent / 'fixtures/bedroom_before_nap.json').read_text())
        self.patched, self.script, self.life, self.dashboard = configurations(self.before)

    def test_only_arrival_guards_changed(self):
        for key, current in self.patched.items():
            expected = deepcopy(self.before[key])
            guard = current['actions'][0]['choose'][0]['conditions'][-1]
            expected['actions'][0]['choose'][0]['conditions'].append(guard)
            self.assertEqual(current, expected)
            self.assertEqual(guard['conditions'][0], {'condition':'state','entity_id':NAP,'state':'off'})
        self.assertEqual(configurations(self.patched)[0], self.patched)

    def test_continuous_clear_return_boundary(self):
        env = Environment()
        env.globals['as_timestamp'] = lambda value: value.timestamp()
        template = env.from_string(RETURN)
        start = datetime(2026, 10, 31, 16)
        for seconds, old, new, expected in [(299,'off','on',False),(300,'off','on',True),
                                           (600,'off','on',True),(600,'unknown','on',False),
                                           (600,'off','unavailable',False)]:
            trigger = SimpleNamespace(from_state=SimpleNamespace(state=old,last_changed=start),
                                      to_state=SimpleNamespace(state=new,last_changed=start+timedelta(seconds=seconds)))
            self.assertEqual(template.render(trigger=trigger).strip(), str(expected))
        self.assertEqual(template.render(trigger={}).strip(), 'False')

    def test_activation_sets_deadline_before_independent_device_off_actions(self):
        seq = self.life['actions'][0]['choose'][0]['sequence']
        self.assertEqual(seq[0]['action'], 'input_datetime.set_datetime')
        self.assertIn('10800', seq[0]['data']['timestamp'])
        self.assertEqual(seq[0]['target']['entity_id'], DEADLINE)
        self.assertEqual(seq[1]['target']['entity_id'], ['light.ceiling_light','light.bedroom_lamp'])
        self.assertEqual(seq[2]['target']['entity_id'], 'switch.bedroom_fan')
        self.assertTrue(seq[1]['continue_on_error'] and seq[2]['continue_on_error'])
        self.assertEqual(self.script['sequence'][0]['target']['entity_id'], NAP)

    def test_end_never_forces_devices_on(self):
        for branch in self.life['actions'][0]['choose'][1:]:
            self.assertEqual(branch['sequence'], [{'action':'input_boolean.turn_off','target':{'entity_id':NAP}}])
        triggers = self.life['triggers']
        self.assertTrue(any(t.get('at')==DEADLINE for t in triggers))
        self.assertTrue(any(t.get('trigger')=='homeassistant' for t in triggers))
        self.assertTrue(any(t.get('trigger')=='time_pattern' for t in triggers))

    def test_return_race_guard_uses_same_qualification_as_end(self):
        for current in self.patched.values():
            self.assertEqual(current['actions'][0]['choose'][0]['conditions'][-1]['conditions'][1]['value_template'], RETURN)
        self.assertEqual(self.life['actions'][0]['choose'][1]['conditions'][-1]['value_template'], RETURN)

    def test_jarvis_exact_name_prefers_script_without_a_device_command(self):
        devices = [dict(id='script.nap_mode',name='Nap Mode',domain='script',state='off',attributes={}),
                   dict(id=NAP,name='Nap Mode',domain='input_boolean',state='off',attributes={})]
        with patch.object(ha, '_default', return_value=None):
            chosen = ha.find('nap mode', devices)
        self.assertEqual(chosen[0]['id'], 'script.nap_mode')
        self.assertEqual(ha._service(chosen[0], 'turn_on', ''), ('script', 'turn_on', {}))


if __name__ == '__main__':
    unittest.main()
