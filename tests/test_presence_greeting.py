import datetime
import tempfile
from pathlib import Path
import unittest
from unittest import mock

import presence_greeting as pg

AFTERNOON = datetime.datetime(2026, 10, 29, 16, 0).timestamp()


def _iso(ts):
    return datetime.datetime.fromtimestamp(ts).astimezone().isoformat()


class Sensor:
    def __init__(self, state='off', changed=AFTERNOON - 3600, person='home', person_changed=AFTERNOON - 86400):
        self.states = {pg.SENSOR: {'state': state, 'last_changed': _iso(changed)},
                       pg.PERSON: {'state': person, 'last_changed': _iso(person_changed)}}

    def set(self, state):
        self.states[pg.SENSOR] = dict(self.states[pg.SENSOR], state=state)

    def __call__(self, entity):
        return self.states[entity]


class WatcherTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(pg, 'PATH', Path(self.tmp.name) / 'greetings.json')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.now = AFTERNOON
        self.queued = []

    def watcher(self, sensor, idle=999.0, briefing=None):
        return pg.Watcher(self.queued.append, sensor, lambda: idle, briefing, clock=lambda: self.now)

    def test_never_greets_for_the_state_seen_at_startup(self):
        sensor = Sensor('on')
        self.assertIsNone(self.watcher(sensor).poll())
        self.assertEqual(self.queued, [])

    def test_greets_after_room_was_empty_for_an_hour_since_startup(self):
        sensor = Sensor('off', changed=AFTERNOON - 3600)
        w = self.watcher(sensor, briefing=lambda: 'Calendar: Dentist 5 PM')
        w.poll()
        sensor.set('on')
        self.assertEqual(w.poll(), 'greeted')
        prompt = self.queued[0]['prompt']
        self.assertIn('[PRESENCE GREETING]', prompt)
        self.assertIn('about an hour', prompt)
        self.assertIn('Dentist 5 PM', prompt)  # medium tier includes the briefing

    def test_short_absence_gets_one_line_and_no_briefing(self):
        sensor = Sensor('on')
        w = self.watcher(sensor, briefing=mock.Mock(return_value='x'))
        w.poll()
        sensor.set('off')
        w.poll()
        self.now += 10 * 60
        sensor.set('on')
        self.assertEqual(w.poll(), 'greeted')
        self.assertIn('One sentence', self.queued[0]['prompt'])
        w.briefing.assert_not_called()

    def test_flicker_quiet_hours_cooldown_and_desk_use_block_greeting(self):
        sensor = Sensor('on')
        w = self.watcher(sensor)
        w.poll()
        sensor.set('off'); w.poll()
        self.now += 60
        sensor.set('on')
        self.assertEqual(w.poll(), 'room was only briefly empty')

        self.assertEqual(pg.should_greet(60, datetime.datetime(2026, 10, 29, 23, 30), 0, 999), 'quiet hours')
        self.assertEqual(pg.should_greet(60, datetime.datetime(2026, 10, 29, 6, 39), 0, 999), 'quiet hours')
        self.assertIsNone(pg.should_greet(60, datetime.datetime(2026, 10, 29, 6, 40), 0, 999))
        noon = datetime.datetime(2026, 10, 29, 12, 0)
        self.assertEqual(pg.should_greet(60, noon, noon.timestamp() - 600, 999), 'cooldown')
        self.assertEqual(pg.should_greet(60, noon, 0, 5), 'someone was just using the PC')
        self.assertEqual(self.queued, [])

    def test_cooldown_survives_a_restart_and_wording_is_remembered(self):
        sensor = Sensor('off', changed=AFTERNOON - 3600)
        w = self.watcher(sensor)
        w.poll(); sensor.set('on'); w.poll()
        self.queued[0]['after']('Welcome back, sir.')
        again = self.watcher(Sensor('off', changed=self.now - 600))
        again.poll()
        again.read_state.set('on')
        self.now += 5 * 60
        self.assertEqual(again.poll(), 'cooldown')
        self.assertEqual(again.saved['recent'][-1]['text'], 'Welcome back, sir.')

    def test_a_quick_pass_through_gives_the_cooldown_back(self):
        # 2026-10-29: in for 20 s at 5:52 (greeted, they'd already gone), back at 6:09 -> cooldown blocked it.
        sensor = Sensor('off', changed=AFTERNOON - 240)
        w = self.watcher(sensor)
        w.poll(); sensor.set('on')
        self.assertEqual(w.poll(), 'greeted')
        self.now += 20
        sensor.set('off'); w.poll()
        self.assertEqual(w.saved['last_greeted'], 0)
        self.now += 17 * 60
        sensor.set('on')
        self.assertEqual(w.poll(), 'greeted')
        self.assertIn('about 21 minutes', self.queued[1]['prompt'])  # timed from before the pass-through

    def test_staying_keeps_the_cooldown(self):
        sensor = Sensor('off', changed=AFTERNOON - 3600)
        w = self.watcher(sensor)
        w.poll(); sensor.set('on'); w.poll()
        self.now += 10 * 60
        sensor.set('off'); w.poll()
        self.now += 5 * 60
        sensor.set('on')
        self.assertEqual(w.poll(), 'cooldown')

    def test_just_got_home_is_a_full_briefing_and_lists_past_lines(self):
        sensor = Sensor('off', changed=AFTERNOON - 3600, person_changed=AFTERNOON - 120)
        w = self.watcher(sensor)
        w.saved['recent'] = [{'text': 'Good to see you, sir.', 'style': pg.STYLES[1]}]
        w.poll(); sensor.set('on'); w.poll()
        prompt = self.queued[0]['prompt']
        self.assertIn('just got home', prompt)
        self.assertIn('short spoken briefing', prompt)
        self.assertIn('Good to see you, sir.', prompt)

    def test_style_never_repeats_twice_running(self):
        for _ in range(50):
            _, style = pg.build_prompt(10, False, datetime.datetime(2026, 10, 29, 12, 0),
                                       [{'text': 'x', 'style': pg.STYLES[0]}])
            self.assertNotEqual(style, pg.STYLES[0])


class ThroughTest(unittest.TestCase):
    def fake_voice(self):
        import voice
        v = voice.Voice.__new__(voice.Voice)
        v.output = 'Headset Earphone (INZONE H5 - C'
        v.calls = []
        v.set_output = lambda name: v.calls.append(('set', name))
        v.refresh_outputs = lambda: v.calls.append(('refresh',))
        v.wait = lambda: v.calls.append(('wait',))
        v._player = mock.Mock()
        return voice, v

    def test_switches_to_the_speaker_for_one_turn_and_back(self):
        voice, v = self.fake_voice()
        with mock.patch.object(voice, 'find_output', return_value=9):
            with v.through('Speakers (Bose') as switched:
                self.assertTrue(switched)
        self.assertEqual(v.calls, [('set', 'Speakers (Bose'), ('wait',), ('set', 'Headset Earphone (INZONE H5 - C')])

    def test_speaker_off_rescans_once_then_stays_on_the_headset(self):
        voice, v = self.fake_voice()
        with mock.patch.object(voice, 'find_output', return_value=None):
            with v.through('Speakers (Bose') as switched:
                self.assertFalse(switched)
        self.assertEqual(v.calls, [('refresh',)])


if __name__ == '__main__':
    unittest.main()
