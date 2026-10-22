"""Spoken Spotify commands act immediately and silently; only failures are spoken."""
import json
import queue
from types import SimpleNamespace
import unittest
from unittest import mock

import music
import spotify_mcp
import tools


class ParseTest(unittest.TestCase):
    def test_playback_phrases(self):
        cases = {
            'pause': ('pause', None), 'Pause the music.': ('pause', None), 'pause spotify please': ('pause', None),
            'can you pause the song': ('pause', None), 'resume': ('resume', None), 'resume the music': ('resume', None),
            'unpause spotify': ('resume', None), 'play music': ('resume', None), 'play spotify': ('resume', None),
            'keep playing': ('resume', None), 'next song': ('next', None), 'skip': ('next', None),
            'skip this song': ('next', None), 'next track please': ('next', None), 'previous song': ('previous', None),
            'go back a song': ('previous', None), 'play the previous track': ('previous', None),
            'play Kind of Blue by Miles Davis': ('play', 'Kind of Blue by Miles Davis'),
            'please play bohemian rhapsody on spotify': ('play', 'bohemian rhapsody'),
            'Play some Taylor Swift.': ('play', 'some Taylor Swift'),
            'queue highway to hell': ('queue', 'highway to hell'),
            'queue up thunderstruck on spotify': ('queue', 'thunderstruck'),
            'add back in black to the queue': ('queue', 'back in black'),
            'add back in black to my queue please': ('queue', 'back in black'),
        }
        with mock.patch.object(music.apps, 'names', return_value=['roblox', 'notepad']):
            for text, expected in cases.items():
                self.assertEqual(music.parse(text), expected, text)

    def test_other_requests_are_left_to_the_assistant(self):
        with mock.patch.object(music.apps, 'names', return_value=['roblox', 'notepad']):
            for text in ('play roblox', 'play a video on youtube', 'what song is this', 'pause the timer',
                         'open spotify', 'skip the intro of this video', 'play the game', 'next', 'previous',
                         'add a reminder for tomorrow', 'queue the video'):
                self.assertIsNone(music.parse(text), text)


class RunTest(unittest.TestCase):
    def setUp(self):
        self.calls, self.keys, self.opened, self.playing, self.devices = [], [], [], False, [{'id': 'pc1', 'type': 'Computer'}]
        def dispatch(name, args):
            self.calls.append(name)
            if name == 'spotify_search':
                return {'items': [{'name': 'Thunderstruck', 'uri': 'spotify:track:T', 'artists': ['AC/DC']},
                                  {'name': 'Highway to Hell', 'uri': 'spotify:track:H', 'artists': ['AC/DC']}]}
            if name == 'spotify_playback':
                return {'is_playing': self.playing}
            if name == 'spotify_devices':
                return {'devices': list(self.devices)}
            if name == 'spotify_queue':
                return {'accepted': True}
            raise AssertionError('playback API commands are not used: ' + name)
        for patcher in (mock.patch.object(spotify_mcp, 'dispatch', side_effect=dispatch),
                        mock.patch.object(music, 'configured', return_value=True),
                        mock.patch.object(music, '_press', side_effect=self.keys.append),
                        mock.patch.object(music.os, 'startfile', side_effect=self.opened.append, create=True),
                        mock.patch.object(music, 'launch_spotify', return_value=True),
                        mock.patch.object(music.time, 'sleep'),
                        mock.patch.object(music.apps, 'names', return_value=[])):
            patcher.start(); self.addCleanup(patcher.stop)

    def test_play_opens_the_best_matching_track_link(self):
        self.assertEqual(music.run('play highway to hell'), '')
        self.assertEqual(self.opened, ['spotify:track:H'])

    def test_play_while_playing_switches_immediately_via_queue_and_skip(self):
        self.playing = True
        self.assertEqual(music.run('play highway to hell'), '')
        self.assertEqual(self.opened, [])
        self.assertIn('spotify_queue', self.calls)
        self.assertEqual(self.keys, ['next'])

    def test_queue_while_playing_only_queues(self):
        self.playing = True
        self.assertEqual(music.run('queue highway to hell'), '')
        self.assertEqual((self.keys, self.opened), ([], []))
        self.assertIn('spotify_queue', self.calls)

    def test_queue_with_nothing_playing_just_plays_it(self):
        self.assertEqual(music.run('add highway to hell to the queue'), '')
        self.assertEqual(self.opened, ['spotify:track:H'])
        self.assertNotIn('spotify_queue', self.calls)

    def test_pause_and_resume_press_the_key_only_when_needed(self):
        self.playing = True
        music.run('pause'); music.run('resume')
        self.assertEqual(self.keys, ['play_pause'])
        self.playing = False
        music.run('pause'); music.run('resume')
        self.assertEqual(self.keys, ['play_pause', 'play_pause'])

    def test_next_previous_and_nothing_running(self):
        self.playing = True
        music.run('next song'); music.run('previous song')
        self.assertEqual(self.keys, ['next', 'previous'])
        self.playing, self.devices = False, []
        self.assertIn('Nothing is playing', music.run('skip'))

    def test_errors_and_missing_results_are_spoken(self):
        with mock.patch.object(spotify_mcp, 'dispatch', return_value={'items': []}):
            self.assertIn("couldn't find", music.run('play zzzz').lower())
        with mock.patch.object(spotify_mcp, 'dispatch', side_effect=spotify_mcp.SpotifyError('Spotify rate or account quota reached. Wait before trying again.')):
            self.assertIn('quota', music.run('pause'))

    def test_not_set_up_falls_through_to_the_assistant(self):
        with mock.patch.object(music, 'configured', return_value=False):
            self.assertIsNone(music.run('pause the music'))


class QuickReplyTest(unittest.TestCase):
    def test_jarvis_quick_reply_runs_music_without_the_ai(self):
        import jarvis
        with mock.patch.object(jarvis.tools.window_control, 'quick_action', return_value=None), \
                mock.patch.object(music, 'run', return_value='') as run:
            self.assertEqual(jarvis.quick_reply('pause the music'), '')
        run.assert_called_once_with('pause the music')


class SpotifyApprovalTest(unittest.TestCase):
    def setUp(self):
        self.commands = queue.Queue()
        patcher = mock.patch.object(tools.hud, 'commands', self.commands)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_call(self, name, host, tool):
        catalog = [{'id': 'c1', 'name': name, 'tools': [{'name': tool}]}]
        public = [{'id': 'c1', 'name': name, 'host': host, 'enabled': True, 'tools': [{'name': tool}]}]
        with mock.patch('mcp_connections.catalog', return_value=catalog), \
                mock.patch('mcp_connections.connections', return_value=public), \
                mock.patch('mcp_connections.call', return_value='{"accepted": true}') as call, \
                mock.patch('approvals.ask', return_value=(False, 'no')) as ask:
            out = tools.run_tool(SimpleNamespace(name='call_mcp_tool', id='m', input={
                'connection_id': 'c1', 'tool_name': tool, 'arguments_json': '{}'}))['content']
            if not ask.called:
                return out, call.called, False
            self.commands.get(timeout=5)
            return out, call.called, True

    def test_local_spotify_search_needs_no_approval_and_answers_in_the_same_turn(self):
        out, called, asked = self.run_call('Spotify (local)', '127.0.0.1:8791', 'spotify_search')
        self.assertTrue(called)
        self.assertFalse(asked)
        self.assertIn('accepted', out)

    def test_assistant_playback_uses_the_same_working_method_as_voice(self):
        # Regression: the assistant used Spotify's play API, which stops music on this PC.
        for tool, action in (('spotify_play', 'play'), ('spotify_queue', 'queue'), ('spotify_pause', 'pause'),
                             ('spotify_next', 'next'), ('spotify_previous', 'previous')):
            with mock.patch.object(music, 'perform', return_value='') as perform:
                out, called, asked = self.run_call('Spotify (local)', '127.0.0.1:8791', tool)
            self.assertFalse(called, tool)  # the Spotify API command was not sent
            self.assertFalse(asked, tool)
            self.assertEqual(perform.call_args.args[0], action)
            self.assertIn('Done', out)

    def test_other_servers_and_lookalikes_still_ask(self):
        for name, host, tool in (('Zapier MCP', 'mcp.zapier.com', 'gmail_send'),
                                 ('Spotify (local)', 'evil.example', 'spotify_pause'),
                                 ('Spotify (local)', '127.0.0.1:8791', 'spotify_delete_everything')):
            out, called, asked = self.run_call(name, host, tool)
            self.assertTrue(asked, (name, host, tool))
            self.assertFalse(called, (name, host, tool))


class BridgeAutostartTest(unittest.TestCase):
    def test_bridge_starts_hidden_when_set_up_and_not_running(self):
        with mock.patch.object(music, 'configured', return_value=True),                 mock.patch.object(music, '_listening', return_value=False),                 mock.patch.object(music.subprocess, 'Popen') as popen:
            self.assertTrue(music.start_bridge())
        flags = popen.call_args.kwargs['creationflags']
        self.assertTrue(flags & music.subprocess.CREATE_NO_WINDOW)
        self.assertFalse(flags & getattr(music.subprocess, 'DETACHED_PROCESS', 0))  # no stray console window
        self.assertTrue(popen.call_args.args[0][-1].endswith('spotify_mcp.py'))

    def test_bridge_is_not_duplicated_or_started_without_setup(self):
        with mock.patch.object(music.subprocess, 'Popen') as popen:
            with mock.patch.object(music, 'configured', return_value=True), mock.patch.object(music, '_listening', return_value=True):
                self.assertFalse(music.start_bridge())
            with mock.patch.object(music, 'configured', return_value=False):
                self.assertFalse(music.start_bridge())
        popen.assert_not_called()


class LaunchSpotifyTest(unittest.TestCase):
    def test_launch_starts_spotify_minimized(self):
        with mock.patch.object(music, '_spotify_exe', return_value='C:/Apps/Spotify.exe'), mock.patch.object(music.subprocess, 'Popen') as popen:
            self.assertTrue(music.launch_spotify())
        self.assertEqual(popen.call_args.args[0], ['C:/Apps/Spotify.exe', '--minimized'])

    def test_missing_spotify_is_reported_not_raised(self):
        with mock.patch.object(music, '_spotify_exe', return_value=None):
            self.assertFalse(music.launch_spotify())
        with mock.patch.object(music, '_spotify_exe', return_value='C:/Apps/Spotify.exe'), mock.patch.object(music.subprocess, 'Popen', side_effect=OSError):
            self.assertFalse(music.launch_spotify())



if __name__ == '__main__':
    unittest.main()
