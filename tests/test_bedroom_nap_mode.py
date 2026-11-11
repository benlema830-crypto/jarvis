from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from jinja2 import Environment
import home_assistant as ha
from scripts.bedroom_nap_mode import configurations, RETURN, NAP, DEADLINE, DURATION, PHONE_AWAY, EXPIRED


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
            self.assertEqual(guard, {'condition':'state','entity_id':NAP,'state':'off'})
        self.assertEqual(configurations(self.patched)[0], self.patched)

    def test_phone_departure_ignores_home_and_unavailable_states(self):
        env = Environment()
        template = env.from_string(PHONE_AWAY)
        for new, expected in [('home',False),('unknown',False),('unavailable',False),
                              ('not_home',True),('Work',True),('',False)]:
            trigger = SimpleNamespace(to_state=SimpleNamespace(state=new))
            self.assertEqual(template.render(trigger=trigger).strip(), str(expected))
        self.assertEqual(template.render(trigger={}).strip(), 'False')

    def test_activation_sets_deadline_before_independent_device_off_actions(self):
        seq = self.life['actions'][0]['choose'][0]['sequence']
        self.assertEqual(seq[0]['action'], 'input_datetime.set_datetime')
        template = Environment().from_string(seq[0]['data']['timestamp'])
        for setting, hours in [('2',2),('3.5',3.5),('unavailable',2)]:
            value = template.render(now=lambda:1000, as_timestamp=lambda n:n, states=lambda _:setting)
            self.assertEqual(float(value), 1000 + hours * 3600)
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

    def test_absence_can_never_end_nap_or_bypass_nap_guard(self):
        for current in self.patched.values():
            guard=current['actions'][0]['choose'][0]['conditions'][-1]
            self.assertEqual(guard, {'condition':'state','entity_id':NAP,'state':'off'})
        self.assertNotIn(RETURN, json.dumps(self.life))
        self.assertFalse(any(t.get('entity_id')=='binary_sensor.bedroom_presence_occupancy'
                             for t in self.life['triggers']))

    def test_previous_return_bypass_is_replaced_not_retained(self):
        previous=deepcopy(self.before)
        for config in previous.values():
            config['actions'][0]['choose'][0]['conditions'].append({'condition':'or','conditions':[
                {'condition':'state','entity_id':NAP,'state':'off'},
                {'condition':'template','value_template':RETURN}]})
        changed=configurations(previous)[0]
        self.assertEqual(changed,self.patched)
        self.assertEqual(configurations(changed)[0],changed)

    def test_phone_trigger_only_when_verified_entity_supplied(self):
        self.assertFalse(any(t.get('id')=='phone_left' for t in self.life['triggers']))
        life=configurations(self.before,phone_entity='device_tracker.jarvis')[2]
        trigger=next(t for t in life['triggers'] if t.get('id')=='phone_left')
        self.assertEqual(trigger,{'trigger':'state','entity_id':'device_tracker.jarvis','from':'home','id':'phone_left'})
        self.assertEqual(life['actions'][0]['choose'][-1]['sequence'],
                         [{'action':'input_boolean.turn_off','target':{'entity_id':NAP}}])

    def test_missing_deadline_does_not_end_nap_and_expiry_boundary(self):
        template=Environment().from_string(EXPIRED)
        def timestamp(value,default=0):
            try:return float(value)
            except (ValueError,TypeError):return default
        for deadline,expected in [('unknown',False),('0',False),('999',True),('1000',True),('1001',False)]:
            actual=template.render(states=lambda _:deadline,now=lambda:1000,as_timestamp=timestamp)
            self.assertEqual(actual.strip(),str(expected))

    def test_dashboard_exposes_timeout_without_changing_running_deadline(self):
        self.assertIn(DURATION,json.dumps(self.dashboard))
        self.assertEqual(len(self.script['sequence']),1)

    def test_jarvis_exact_name_prefers_script_without_a_device_command(self):
        devices = [dict(id='script.nap_mode',name='Nap Mode',domain='script',state='off',attributes={}),
                   dict(id=NAP,name='Nap Mode',domain='input_boolean',state='off',attributes={})]
        with patch.object(ha, '_default', return_value=None):
            chosen = ha.find('nap mode', devices)
        self.assertEqual(chosen[0]['id'], 'script.nap_mode')
        self.assertEqual(ha._service(chosen[0], 'turn_on', ''), ('script', 'turn_on', {}))


if __name__ == '__main__':
    unittest.main()
