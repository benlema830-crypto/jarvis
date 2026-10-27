"""'Jarvis, open' / 'Jarvis, open up' opens Jarvis's own Brain page without an AI turn."""
import unittest
from unittest import mock

import jarvis
import music


class OpenSelfTest(unittest.TestCase):
    def setUp(self):
        # open_app is faked: the test checks routing only, and used to launch a real Notepad each run.
        for patcher in (mock.patch.object(music, 'run', return_value=None),
                        mock.patch.object(jarvis.tools.window_control, 'quick_action', return_value=None),
                        mock.patch.object(jarvis.tools, 'open_app', mock.Mock(**{'call.return_value': 'Opened'}))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_open_phrases_open_the_brain(self):
        for said in ('open', 'Open.', 'open up', 'open up please', 'open yourself', 'please open up', 'show yourself'):
            with mock.patch.object(jarvis, 'open_brain_page') as page:
                self.assertEqual(jarvis.quick_reply(said), '', said)
                page.assert_called_once()

    def test_opening_other_things_is_unchanged(self):
        with mock.patch.object(jarvis, 'open_brain_page') as page:
            jarvis.quick_reply('open notepad')
            jarvis.quick_reply('open up spotify')
            page.assert_not_called()
