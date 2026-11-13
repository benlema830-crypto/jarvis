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

    def set(self, state, changed):
        self.states[pg.SENSOR] = dict(self.states[pg.SENSOR], state=state, last_changed=_iso(changed))

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
        self.sensor = Sensor('on', changed=self.now)
        self.w = pg.Watcher(self.queued.append, self.sensor, lambda: 999,
                            clock=lambda: self.now)
        self.w.poll()

    def change(self, state):
        self.sensor.set(state, self.now)
        return self.w.poll()

    def wait(self, seconds):
        for _ in range(seconds // 2):
            self.now += 2
            self.w.poll()
        if seconds % 2:
            self.now += 1
            self.w.poll()

    def test_ten_continuous_minutes_boundary_and_exact_duration(self):
        self.change('off'); self.wait(599)
        self.assertEqual(self.change('on'), 'room was only briefly empty')
        self.change('off'); self.wait(600)
        self.assertEqual(self.change('on'), 'greeted')
        self.assertIn('about 10 minutes', self.queued[0]['prompt'])

    def test_repeated_doorway_trips_do_not_reuse_absence_or_refund_cooldown(self):
        self.change('off'); self.wait(16 * 60); self.change('on')
        greeted = self.w.saved['last_greeted']
        for minutes in (4, 1, 3):
            self.wait(20); self.change('off'); self.wait(minutes * 60)
            self.assertEqual(self.change('on'), 'room was only briefly empty')
            self.assertEqual(self.w.saved['last_greeted'], greeted)
        self.assertEqual(len(self.queued), 1)

    def test_new_absence_has_own_duration_even_after_brief_return(self):
        self.change('off'); self.wait(16 * 60); self.change('on')
        self.wait(20); self.change('off'); self.wait(31 * 60)
        self.assertEqual(self.change('on'), 'greeted')
        self.assertIn('about 31 minutes', self.queued[-1]['prompt'])

    def test_short_clear_blips_do_not_accumulate_or_reset_cooldown(self):
        for _ in range(8):
            self.change('off'); self.wait(120); self.change('on'); self.wait(2)
        self.assertEqual(self.queued, [])
        self.assertNotIn('last_greeted', self.w.saved)

    def test_cooldown_persists_and_survives_restart(self):
        self.change('off'); self.wait(600); self.change('on')
        self.queued[0]['after']('Welcome back, sir.')
        self.wait(20); self.change('off'); self.wait(600)
        self.w = pg.Watcher(self.queued.append, self.sensor, lambda: 999, clock=lambda: self.now)
        self.w.poll()
        self.assertEqual(self.change('on'), 'cooldown')
        self.assertEqual(self.w.saved['recent'][-1]['text'], 'Welcome back, sir.')
        self.assertGreaterEqual(pg.COOLDOWN_MINUTES, 10)

    def test_unknown_and_read_errors_break_continuity(self):
        for failure in ('unavailable', 'unknown', 'exception'):
            self.change('off'); self.wait(600)
            if failure == 'exception':
                with mock.patch.object(self.w, 'read_state', side_effect=RuntimeError('offline')):
                    with self.assertRaises(RuntimeError): self.w.poll()
            else:
                self.change(failure)
            self.change('on')
        self.assertEqual(self.queued, [])

    def test_missed_on_off_between_polls_uses_new_clear_timestamp(self):
        self.change('off'); self.wait(600)
        self.now += 1
        self.sensor.set('off', self.now)  # HA reports a fresh clear interval after an unseen on.
        self.w.poll(); self.wait(60)
        self.assertEqual(self.change('on'), 'room was only briefly empty')
        self.assertEqual(self.queued, [])

    def test_poll_stall_does_not_invent_continuity(self):
        self.change('off'); self.wait(600)
        self.now += 100
        self.assertEqual(self.change('on'), 'observation gap')
        self.assertEqual(self.queued, [])

    def test_sensor_transition_times_not_poll_times_measure_absence(self):
        self.sensor.set('off', self.now - 2); self.w.poll(); self.wait(600)
        self.sensor.set('on', self.now - 1)
        self.assertEqual(self.w.poll(), 'greeted')
        self.assertIn('about 10 minutes', self.queued[0]['prompt'])

    def test_startup_does_not_greet_but_ha_clear_duration_is_used(self):
        self.assertEqual(self.queued, [])
        self.sensor = Sensor('off', changed=self.now - 3600)
        self.w = pg.Watcher(self.queued.append, self.sensor, lambda:999,
                            briefing=lambda:'Calendar: Dentist 5 PM', clock=lambda:self.now)
        self.assertIsNone(self.w.poll())
        self.assertEqual(self.change('on'), 'greeted')
        self.assertIn('about an hour', self.queued[0]['prompt'])
        self.assertIn('Dentist', self.queued[0]['prompt'])

    def test_quiet_hours_and_desk_use_still_block(self):
        self.assertEqual(pg.should_greet(60, datetime.datetime(2026,10,29,23,30),0,999),'quiet hours')
        self.assertEqual(pg.should_greet(60, datetime.datetime(2026,10,29,6,39),0,999),'quiet hours')
        self.assertIsNone(pg.should_greet(60, datetime.datetime(2026,10,29,6,40),0,999))
        noon=datetime.datetime(2026,10,29,12,0)
        self.assertEqual(pg.should_greet(60,noon,noon.timestamp()-599,999),'cooldown')
        self.assertEqual(pg.should_greet(60,noon,0,5),'someone was just using the PC')
        # 11-04: asleep in bed, the sensor lost them at 6:13, and the 6:40 alarm "welcomed them back".
        morning=datetime.datetime(2026,11,4,6,40,12)
        self.assertEqual(pg.should_greet(27,morning,0,999,datetime.datetime(2026,11,4,6,13)),'the room only looked empty overnight')
        self.assertIsNone(pg.should_greet(40,datetime.datetime(2026,11,4,8,23),0,999,datetime.datetime(2026,11,4,7,43)))

    def test_style_and_home_briefing_preserved(self):
        self.assertEqual(pg.tier(10, True),'long')
        for _ in range(20):
            prompt,style=pg.build_prompt(10,True,datetime.datetime(2026,10,29,12,0),
                                        [{'text':'x','style':pg.STYLES[0]}])
            self.assertNotEqual(style,pg.STYLES[0])
            self.assertIn('just got home',prompt)


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


class SetOutputTest(unittest.TestCase):
    def fake_voice(self):
        import threading
        import voice
        v = voice.Voice.__new__(voice.Voice)
        v.output = ''
        v.refreshed = 0
        v._player = mock.Mock(close=lambda: [])
        v._player_lock = threading.Lock()
        return voice, v

    def test_rescans_for_a_speaker_that_connected_after_startup(self):
        voice, v = self.fake_voice()
        found = [None, 5]  # missing from the stale list, there after the rescan
        v.refresh_outputs = lambda: setattr(v, 'refreshed', v.refreshed + 1)
        with mock.patch.object(voice, 'find_output', side_effect=lambda name: found.pop(0)), \
                mock.patch.object(voice, '_Player'), \
                mock.patch.object(voice, 'output_devices', return_value=[(5, 'Speakers (Bose Micro SoundLink)')]):
            self.assertEqual(v.set_output('bose'), 'Speakers (Bose Micro SoundLink)')
        self.assertEqual(v.refreshed, 1)

    def test_still_missing_after_the_rescan_raises(self):
        voice, v = self.fake_voice()
        v.refresh_outputs = lambda: None
        with mock.patch.object(voice, 'find_output', return_value=None):
            with self.assertRaises(ValueError):
                v.set_output('bose')


if __name__ == '__main__':
    unittest.main()
