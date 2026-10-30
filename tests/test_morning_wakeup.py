import datetime
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
        self.assertEqual(self.services, [('fan', 'turn_off', {'entity_id': mw.FAN})])
        self.assertIsNone(self.alarm().poll())  # a restart the same morning doesn't ring again
        with mock.patch.object(mw, 'start_music') as music:
            item['after']('Good morning, sir.')
            for t in __import__('threading').enumerate():
                if t.name == 'morning-music':
                    t.join(2)
        music.assert_called_once()

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


if __name__ == '__main__':
    unittest.main()
