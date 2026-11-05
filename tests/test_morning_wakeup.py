import datetime
import importlib.util
import tempfile
from pathlib import Path
import unittest
from unittest import mock

import morning_wakeup as mw
import presence_greeting as pg

THURSDAY_640 = datetime.datetime(2026, 10, 29, 6, 40, 5).timestamp()


class AlarmTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(mw, 'PATH', Path(self.tmp.name) / 'wake.json')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.now = THURSDAY_640
        self.queued, self.services = [], []
        self.states = {pg.PERSON: {'state': 'home'}, pg.SENSOR: {'state': 'on'}}
        self.idle, self.last_user = 9999.0, 0.0

    def alarm(self):
        return mw.Alarm(self.queued.append, lambda e: self.states[e],
                        lambda d, s, data: self.services.append((d, s, data)), lambda: 'Weather: 40F',
                        lambda: self.idle, lambda: self.last_user, clock=lambda: self.now)

    def test_due_only_on_weekdays_in_the_window_once_a_day(self):
        at = lambda *a: datetime.datetime(2026, 10, *a)
        self.assertTrue(mw.due(at(29, 6, 40), None))
        self.assertFalse(mw.due(at(29, 6, 39), None))
        self.assertFalse(mw.due(at(29, 7, 15), None))           # PC woke too late: skip
        self.assertFalse(mw.due(at(31, 6, 45), None))           # Saturday
        self.assertFalse(mw.due(at(29, 6, 45), '2026-10-29'))   # already rang today

    def test_wake_rings_on_the_speaker_turns_the_fan_off_and_briefs(self):
        a = self.alarm()
        self.assertEqual(a.poll(), 'woke')
        item = self.queued[0]
        self.assertEqual((item['alarm'], item['output']), (4, pg.SPEAKER))
        self.assertIn('Weather: 40F', item['prompt'])
        self.assertEqual(self.services, [('fan', 'turn_off', {'entity_id': mw.FAN}),
                                         ('light', 'turn_on', {'entity_id': mw.LIGHTS, 'brightness_pct': 100})])
        self.assertIsNone(self.alarm().poll())  # a restart the same morning doesn't ring again
        with mock.patch.object(mw, 'start_music', return_value='started spotify:playlist:x') as music:
            item['after']('Good morning, sir.')
            for t in __import__('threading').enumerate():
                if t.name == 'morning-music':
                    t.join(2)
        music.assert_called_once()
        run = mw._load()['last_run']
        self.assertEqual((run['fan'], run['lights'], run['speaker'], run['music']),
                         ('done', 'done', 'Bose', 'started spotify:playlist:x'))
        self.assertNotIn('phone_alert', run)

    def test_bose_not_connected_still_rings_and_alerts_the_phone(self):
        a = mw.Alarm(self.queued.append, lambda e: self.states[e],
                     lambda d, s, data: self.services.append((d, s, data)), lambda: 'Weather: 40F',
                     lambda: self.idle, lambda: self.last_user, clock=lambda: self.now,
                     speaker_ready=lambda: False)
        self.assertEqual(a.poll(), 'woke')
        self.assertEqual(len(self.queued), 1)  # the alarm still plays, on the default output
        notify = [x for x in self.services if x[0] == 'notify']
        self.assertEqual(notify[0][1], mw.PHONE)
        self.assertEqual(notify[0][2]['data']['push']['sound']['critical'], 1)
        run = mw._load()['last_run']
        self.assertIn('NOT connected', run['speaker'])
        self.assertEqual(run['phone_alert'], 'done')

    def test_a_failed_step_is_recorded_and_the_rest_still_runs(self):
        def service(domain, name, data):
            if domain == 'light':
                raise RuntimeError('Ceiling Light unavailable')
            self.services.append((domain, name, data))
        a = mw.Alarm(self.queued.append, lambda e: self.states[e], service, lambda: '',
                     clock=lambda: self.now)
        self.assertEqual(a.poll(), 'woke')
        run = mw._load()['last_run']
        self.assertEqual(run['lights'], 'failed: Ceiling Light unavailable')
        self.assertEqual(run['fan'], 'done')
        self.assertEqual(len(self.queued), 1)
        text = '\n'.join(mw.describe())
        self.assertIn('lights failed: Ceiling Light unavailable', text)
        self.assertIn('Weekdays (Mon-Fri) at 6:40', text)

    def test_not_home_is_recorded_and_nothing_happens(self):
        self.states[pg.PERSON] = {'state': 'not_home'}
        self.assertEqual(self.alarm().poll(), 'not home')
        self.assertEqual((self.queued, self.services), ([], []))
        self.assertEqual(mw._load()['last_run']['result'], 'skipped: phone not home')

    def test_checks_back_every_three_minutes_until_they_answer(self):
        a = self.alarm()
        a.poll()
        self.now += 2 * 60
        self.assertIsNone(a.poll())
        self.now += 60
        self.assertEqual(a.poll(), 'nudged')
        self.assertEqual(self.queued[-1]['alarm'], 1)
        self.last_user = self.now + 1
        self.now += 10
        self.assertEqual(a.poll(), 'up')
        self.now += 10 * 60
        self.assertIsNone(a.poll())

    def test_leaving_the_room_or_touching_the_pc_counts_as_up(self):
        a = self.alarm()
        a.poll()
        self.states[pg.SENSOR] = {'state': 'off'}
        self.now += 60
        self.assertIsNone(a.poll())          # first sight of an empty room starts the clock
        self.now += 60
        self.assertIsNone(a.poll())          # empty only a minute: maybe the sensor lost them
        self.now += 60
        self.assertEqual(a.poll(), 'up')

        b = mw.Alarm(self.queued.append, lambda e: {'state': 'on'} if e == pg.SENSOR else {'state': 'home'},
                     lambda *x: None, lambda: '', lambda: 5.0, lambda: 0.0, clock=lambda: self.now)
        b.woke_at = self.now - 120
        self.assertEqual(b.poll(), 'up')

    def test_gives_up_after_the_last_check_and_skips_when_away(self):
        a = self.alarm()
        a.poll()
        for _ in range(mw.MAX_FOLLOWUPS):
            self.now += mw.FOLLOWUP_MINUTES * 60
            self.assertEqual(a.poll(), 'nudged')
        self.assertEqual(a.poll(), 'gave up')
        self.states[pg.PERSON] = {'state': 'not_home'}
        self.now += 86400
        self.assertEqual(self.alarm().poll(), 'not home')


class MusicTest(unittest.TestCase):
    def test_playlist_link_plays_in_order_and_resume_is_the_default(self):
        import music
        import preferences
        import spotify_mcp
        with mock.patch.object(preferences, 'read', return_value={'morning_music': 'spotify:playlist:abc'}),                 mock.patch.object(music, 'perform', return_value='') as perform,                 mock.patch.object(spotify_mcp, 'api') as api:
            mw.start_music()
        perform.assert_called_once_with('play', 'spotify:playlist:abc')
        api.assert_called_once_with('PUT', '/me/player/shuffle', params={'state': 'false'})
        with mock.patch.object(preferences, 'read', return_value={}),                 mock.patch.object(music, 'perform', return_value='') as perform:
            mw.start_music()
        perform.assert_called_once_with('resume')


class MorningWindowTest(unittest.TestCase):
    """Presence automations must not undo the alarm: no fan on, no lights off, 6:40-7:10 on weekdays."""

    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / 'scripts' / 'bedroom_morning_window.py'
        spec = importlib.util.spec_from_file_location('bedroom_morning_window', path)
        cls.script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.script)

    @staticmethod
    def automation(automation_id, trigger_id, action):
        return {'id': automation_id, 'description': 'x', 'triggers': [{'trigger': 'state', 'id': trigger_id}],
                'actions': [{'choose': [
                    {'conditions': [{'condition': 'trigger', 'id': 'other'}], 'sequence': [{'action': 'noop'}]},
                    {'conditions': [{'condition': 'trigger', 'id': trigger_id}], 'sequence': [{'action': action}]},
                ]}]}

    def test_fan_arrival_is_blocked_only_on_its_own_branch_and_applying_twice_changes_nothing(self):
        before = self.automation(self.script.FAN_ID, 'arrive', 'fan.turn_on')
        after = self.script.fan_config(before)
        other, arrive = after['actions'][0]['choose']
        self.assertIn(self.script.OUTSIDE_WINDOW, arrive['conditions'])
        self.assertNotIn(self.script.OUTSIDE_WINDOW, other['conditions'])
        self.assertEqual(self.script.fan_config(after), after)
        self.assertEqual(len(before['actions'][0]['choose'][1]['conditions']), 1)  # original left untouched

    def test_lights_stay_on_in_the_window_and_are_rechecked_at_its_end(self):
        after = self.script.lights_config(self.automation(self.script.LIGHTS_ID, 'empty', 'light.turn_off'))
        self.assertIn(self.script.OUTSIDE_WINDOW, after['actions'][0]['choose'][1]['conditions'])
        self.assertIn(self.script.LIGHTS_RECHECK, after['triggers'])
        self.assertEqual(self.script.lights_config(after), after)

    def test_recheck_lands_just_outside_the_window_so_it_can_act(self):
        self.assertEqual(self.script.LIGHTS_RECHECK['at'], self.script.WINDOW['before'])  # "before" excludes it

    def test_an_unexpected_automation_is_refused(self):
        with self.assertRaises(ValueError):
            self.script.fan_config(self.automation('something_else', 'arrive', 'fan.turn_on'))
        with self.assertRaises(ValueError):
            self.script.fan_config(self.automation(self.script.FAN_ID, 'arrive', 'light.turn_on'))


class ReconnectTest(unittest.TestCase):
    def run_connect(self, states):
        import bluetooth_audio
        waits = []
        with mock.patch.object(bluetooth_audio, 'connected', side_effect=states), \
                mock.patch.object(bluetooth_audio, 'request_reconnect') as request:
            result = bluetooth_audio.connect('Bose', sleep=waits.append)
        return result, request.call_count, len(waits)

    def test_already_connected_sends_nothing(self):
        self.assertEqual(self.run_connect([True]), (True, 0, 0))

    def test_stops_as_soon_as_the_speaker_is_up(self):
        self.assertEqual(self.run_connect([False, False, True]), (True, 2, 2))

    def test_gives_up_when_the_speaker_never_answers(self):
        self.assertEqual(self.run_connect([False] * 4), (False, 3, 3))

    def test_a_failed_request_is_retried_not_raised(self):
        import bluetooth_audio
        with mock.patch.object(bluetooth_audio, 'connected', side_effect=[False, True]), \
                mock.patch.object(bluetooth_audio, 'request_reconnect', side_effect=OSError('no driver')):
            self.assertTrue(bluetooth_audio.connect('Bose', sleep=lambda _: None))


if __name__ == '__main__':
    unittest.main()
