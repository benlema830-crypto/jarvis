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
        }
        with mock.patch.object(music.apps, 'names', return_value=['roblox', 'notepad']):
            for text, expected in cases.items():
                self.assertEqual(music.parse(text), expected, text)

    def test_other_requests_are_left_to_the_assistant(self):
        with mock.patch.object(music.apps, 'names', return_value=['roblox', 'notepad']):
            for text in ('play roblox', 'play a video on youtube', 'what song is this', 'pause the timer',
                         'open spotify', 'skip the intro of this video', 'play the game', 'next', 'previous'):
                self.assertIsNone(music.parse(text), text)


class RunTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.responses = {}
        def dispatch(name, args):
            self.calls.append((name, args))
            result = self.responses.get(name, {'accepted': True})
            if isinstance(result, Exception):
                raise result
            return result(args) if callable(result) else result
        for patcher in (mock.patch.object(spotify_mcp, 'dispatch', side_effect=dispatch),
                        mock.patch.object(music, 'configured', return_value=True),
                        mock.patch.object(music.apps, 'names', return_value=['roblox'])):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_pause_next_previous_resume_are_silent(self):
        for text, tool in (('pause the music', 'spotify_pause'), ('next song', 'spotify_next'),
                           ('previous song', 'spotify_previous'), ('resume', 'spotify_play')):
            self.calls.clear()
            self.assertEqual(music.run(text), '', text)
            self.assertEqual(self.calls, [(tool, {})])

    def test_play_by_name_searches_then_plays_the_top_track(self):
        uri = 'spotify:track:' + 'A' * 22
        self.responses['spotify_search'] = {'items': [{'name': 'So What', 'uri': uri, 'artists': ['Miles Davis']}]}
        self.assertEqual(music.run('play so what by miles davis'), '')
        self.assertEqual(self.calls, [('spotify_search', {'query': 'so what by miles davis', 'type': 'track', 'limit': 1}),
                                      ('spotify_play', {'uri': uri})])

    def test_no_active_device_uses_an_available_one(self):
        state = {'first': True}
        def play(args):
            if state.pop('first', False):
                raise spotify_mcp.SpotifyError('No active Spotify device. Open Spotify and play a track first.')
            return {'accepted': True}
        self.responses['spotify_play'] = play
        self.responses['spotify_devices'] = {'devices': [{'id': 'phone1', 'type': 'Smartphone', 'is_restricted': False},
                                                         {'id': 'pc1', 'type': 'Computer', 'is_restricted': False}]}
        self.assertEqual(music.run('resume'), '')
        self.assertEqual(self.calls[-1], ('spotify_play', {'device_id': 'pc1'}))

    def test_failures_are_spoken_briefly(self):
        self.responses['spotify_search'] = {'items': []}
        self.assertIn("couldn't find", music.run('play zzzz qqqq').lower())
        self.responses['spotify_pause'] = spotify_mcp.SpotifyError('Spotify denied access. Check Premium, app user access and playback scopes.')
        self.assertIn('Premium', music.run('pause'))
        self.responses['spotify_devices'] = {'devices': []}
        self.responses['spotify_next'] = spotify_mcp.SpotifyError('No active Spotify device. Open Spotify and play a track first.')
        self.assertIn('Open Spotify', music.run('skip'))

    def test_not_set_up_falls_through_to_the_assistant(self):
        with mock.patch.object(music, 'configured', return_value=False):
            self.assertIsNone(music.run('pause the music'))
        self.assertEqual(self.calls, [])


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

    def test_local_spotify_playback_needs_no_approval_and_answers_in_the_same_turn(self):
        out, called, asked = self.run_call('Spotify (local)', '127.0.0.1:8791', 'spotify_pause')
        self.assertTrue(called)
        self.assertFalse(asked)
        self.assertIn('accepted', out)

    def test_other_servers_and_lookalikes_still_ask(self):
        for name, host, tool in (('Zapier MCP', 'mcp.zapier.com', 'gmail_send'),
                                 ('Spotify (local)', 'evil.example', 'spotify_pause'),
                                 ('Spotify (local)', '127.0.0.1:8791', 'spotify_delete_everything')):
            out, called, asked = self.run_call(name, host, tool)
            self.assertTrue(asked, (name, host, tool))
            self.assertFalse(called, (name, host, tool))


if __name__ == '__main__':
    unittest.main()
