import os
import unittest
from unittest import mock

import home_assistant as ha

STATES = [
    {'entity_id': 'media_player.lg_webos_tv_oled65c4pua', 'state': 'on',
     'attributes': {'friendly_name': '[LG] webOS TV OLED65C4PUA', 'volume_level': 0.2, 'supported_features': 152461}},
    {'entity_id': 'media_player.living_room_living_room', 'state': 'playing',
     'attributes': {'friendly_name': 'Living Room', 'media_title': 'Dune', 'volume_level': 0.5,
                    'supported_features': 450487,
                    'source_list': ['App Store', 'Netflix', 'Prime Video', 'YouTube', 'YouTube TV']}},
    {'entity_id': 'media_player.nightstand_speaker', 'state': 'off',
     'attributes': {'friendly_name': 'Nightstand Speaker', 'supported_features': 152461}},
    {'entity_id': 'remote.living_room_living_room', 'state': 'on', 'attributes': {'friendly_name': 'Living Room'}},
    {'entity_id': 'light.desk_lamp', 'state': 'on', 'attributes': {'friendly_name': 'Desk Lamp', 'brightness': 128}},
    {'entity_id': 'light.ceiling', 'state': 'off', 'attributes': {'friendly_name': 'Ceiling'}},
    {'entity_id': 'switch.amazon_plug', 'state': 'off', 'attributes': {'friendly_name': 'Amazon Plug'}},
    {'entity_id': 'lock.front_door', 'state': 'locked', 'attributes': {'friendly_name': 'Front Door'}},
    {'entity_id': 'sensor.temperature', 'state': '70', 'attributes': {'friendly_name': 'Temperature'}},
]
INFO = ('media_player.lg_webos_tv_oled65c4pua|LGE OLED65C4PUA \n'
        'media_player.living_room_living_room|Apple Apple TV 4K (gen 2) Living Room\n'
        'remote.living_room_living_room|Apple Apple TV 4K (gen 2) Living Room\n'
        'light.desk_lamp|IKEA TRADFRI Bedroom\nlight.ceiling|Hue Bedroom\n')


class HomeAssistantTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        def api(method, path, payload=None):
            self.calls.append((method, path, payload))
            if path == '/api/states':
                return STATES
            if path == '/api/template':
                return INFO
            return []
        patcher = mock.patch.object(ha, '_api', side_effect=api)
        patcher.start()
        self.addCleanup(patcher.stop)
        ha._info = (0.0, {})

    def ids(self, query):
        return [d['id'] for d in ha.find(query)]

    def test_names_resolve_to_the_right_device(self):
        self.assertEqual(self.ids('the TV'), ['media_player.lg_webos_tv_oled65c4pua'])
        self.assertEqual(self.ids('LG TV'), ['media_player.lg_webos_tv_oled65c4pua'])
        self.assertEqual(self.ids('Apple TV'), ['media_player.living_room_living_room'])  # the player, not the remote
        self.assertEqual(self.ids('living room'), ['media_player.living_room_living_room'])
        self.assertEqual(self.ids('desk lamp'), ['light.desk_lamp'])
        self.assertEqual(self.ids('the plug'), ['switch.amazon_plug'])

    def test_lights_and_rooms_mean_every_matching_light(self):
        self.assertEqual(set(self.ids('the lights')), {'light.desk_lamp', 'light.ceiling'})
        self.assertEqual(set(self.ids('bedroom lights')), {'light.desk_lamp', 'light.ceiling'})

    def test_unknown_ambiguous_and_unsafe_devices_are_refused(self):
        with self.assertRaisesRegex(ha.HomeError, "couldn't find"):
            ha.find('garage')
        with self.assertRaisesRegex(ha.HomeError, "couldn't find"):
            ha.find('front door')  # locks are never controllable
        with self.assertRaisesRegex(ha.HomeError, 'Which one'):
            ha.find('bedroom')

    def test_control_calls_the_matching_services(self):
        self.assertEqual(ha.control('desk lamp', 'set_brightness', '40%'), 'Sent set brightness 40% to Desk Lamp.')
        ha.control('lights', 'turn_off')
        ha.control('TV', 'set_volume', '30')
        ha.control('Apple TV', 'pause')
        ha.control('desk lamp', 'set_color', 'Blue')
        services = [(p, d) for m, p, d in self.calls if p.startswith('/api/services/')]
        self.assertEqual(services, [
            ('/api/services/light/turn_on', {'brightness_pct': 40, 'entity_id': 'light.desk_lamp'}),
            ('/api/services/light/turn_off', {'entity_id': 'light.desk_lamp'}),
            ('/api/services/light/turn_off', {'entity_id': 'light.ceiling'}),
            ('/api/services/media_player/volume_set', {'volume_level': 0.3, 'entity_id': 'media_player.lg_webos_tv_oled65c4pua'}),
            ('/api/services/media_player/media_pause', {'entity_id': 'media_player.living_room_living_room'}),
            ('/api/services/light/turn_on', {'color_name': 'blue', 'entity_id': 'light.desk_lamp'}),
        ])

    def test_open_app_launches_the_named_app(self):
        self.assertEqual(ha.control('Apple TV', 'open_app', 'netflix'), 'Asked Living Room to open Netflix.')
        ha.control('Apple TV', 'open_app', 'YouTube')
        ha.control('Apple TV', 'open_app', 'prime')
        ha.control('Apple TV', 'open_app', 'app store')
        sources = [d['source'] for m, p, d in self.calls if p == '/api/services/media_player/select_source']
        self.assertEqual(sources, ['Netflix', 'YouTube', 'Prime Video', 'App Store'])

    def test_wrong_action_for_device_does_nothing(self):
        for device, action, value in [('the plug', 'pause', ''), ('TV', 'set_brightness', '50'),
                                      ('desk lamp', 'set_brightness', 'bright'), ('TV', 'unlock', ''),
                                      ('Apple TV', 'open_app', 'Max Payne'), ('Apple TV', 'open_app', ''),
                                      ('Apple TV', 'mute', ''),  # the Apple TV reports no mute support
                                      ('TV', 'open_app', 'Netflix'),  # the LG reports no app list
                                      ('nightstand speaker', 'set_volume', '20')]:  # it's off
            with self.assertRaises(ha.HomeError, msg=(device, action)):
                ha.control(device, action, value)
        self.assertFalse([c for c in self.calls if c[1].startswith('/api/services/')])

    def test_open_app_wakes_a_sleeping_player_first(self):
        STATES[1]['state'] = 'off'
        self.addCleanup(STATES[1].__setitem__, 'state', 'playing')
        with mock.patch.object(ha.time, 'sleep') as sleep:
            ha.control('Apple TV', 'open_app', 'Netflix')
        sleep.assert_called_once_with(ha.WAKE_SECONDS)
        services = [p.rsplit('/', 1)[1] for m, p, d in self.calls if p.startswith('/api/services/')]
        self.assertEqual(services, ['turn_on', 'select_source'])
        with self.assertRaisesRegex(ha.HomeError, 'is off'):
            ha.control('Apple TV', 'pause')

    def test_off_device_can_still_be_turned_on(self):
        ha.control('nightstand speaker', 'turn_on')
        self.assertIn(('POST', '/api/services/media_player/turn_on', {'entity_id': 'media_player.nightstand_speaker'}), self.calls)
        with self.assertRaisesRegex(ha.HomeError, 'is off'):
            ha.control('nightstand speaker', 'pause')

    def test_status_describes_devices(self):
        text = ha.status()
        self.assertIn('Desk Lamp: on, brightness 50%', text)
        self.assertIn('Living Room: playing, playing Dune, volume 50%', text)
        self.assertNotIn('Front Door', text)
        self.assertEqual(ha.status('TV'), '[LG] webOS TV OLED65C4PUA: on, volume 20%')


class ApiTest(unittest.TestCase):
    def test_needs_configuration(self):
        with mock.patch.dict(os.environ, {'HA_URL': '', 'HA_TOKEN': ''}):
            with self.assertRaisesRegex(ha.HomeError, 'HA_URL and HA_TOKEN'):
                ha._api('GET', '/api/states')

    def test_token_never_goes_through_a_proxy(self):
        session = mock.Mock()
        session.request.return_value = mock.Mock(status_code=200, headers={'Content-Type': 'application/json'},
                                                 json=lambda: [])
        with mock.patch.dict(os.environ, {'HA_URL': 'http://192.168.1.118/', 'HA_TOKEN': 'secret'}), \
             mock.patch.object(ha.requests, 'Session', return_value=session):
            ha._api('GET', '/api/states')
        self.assertFalse(session.trust_env)
        args, kwargs = session.request.call_args
        self.assertEqual(args, ('GET', 'http://192.168.1.118/api/states'))
        self.assertEqual(kwargs['headers'], {'Authorization': 'Bearer secret'})
        self.assertFalse(kwargs['allow_redirects'])

    def test_rejected_token_is_explained(self):
        session = mock.Mock()
        session.request.return_value = mock.Mock(status_code=401, headers={})
        with mock.patch.dict(os.environ, {'HA_URL': 'http://x', 'HA_TOKEN': 'bad'}), \
             mock.patch.object(ha.requests, 'Session', return_value=session):
            with self.assertRaisesRegex(ha.HomeError, 'rejected the access token'):
                ha._api('GET', '/api/states')


if __name__ == '__main__':
    unittest.main()
