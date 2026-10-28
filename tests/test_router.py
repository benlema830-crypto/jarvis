from pathlib import Path
import tempfile
import unittest
from unittest import mock

import model_provider as mp
import ollama_brain
import router

LOCAL = {'provider': 'ollama', 'model': router.DEFAULT_MODEL}
CHATS = ('What time is it', 'Thanks Jarvis', 'Good night')
CODEX = {'provider': 'codex', 'model': 'gpt-test'}


class RouterTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for patcher in (mock.patch.object(mp.preferences, 'PATH', Path(directory.name) / 'preferences.json'),
                        mock.patch.object(ollama_brain, 'enabled', return_value=True),
                        mock.patch.object(ollama_brain, 'models', return_value=[router.DEFAULT_MODEL])):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_quick_requests_go_local(self):
        for text in ['Mute', 'Set the volume to 30 percent', 'Turn it louder', 'Open Spotify',
                     'Remind me in 10 minutes to check the laundry', 'Set a timer for 5 minutes',
                     "What's the weather like?", 'What time is it', "What's on my schedule today?",
                     'Add a Zigbee plug to my Amazon cart', 'Thanks Jarvis', 'Good night',
                     'Add milk to my to-do list', 'Turn off the TV', 'Pause the Apple TV',
                     'Dim the bedroom lights', 'Turn the desk lamp on', 'Set the lights to blue', 'Lights off']:
            tools = router.HOME_TOOLS if router.HOME.search(text) else router.LOCAL_TOOLS
            self.assertEqual(router.choose(text, CODEX), dict(LOCAL, action=text not in CHATS, tools=tools), text)

    def test_hard_or_unknown_requests_stay_on_selected_brain(self):
        for text in ['Pause', 'Skip this song', 'Fix the bug in the HUD', 'Open a Codex session for Rocket Frontier', 'Why is the sky blue?',
                     "What's the latest news?", 'Remember that my sister is called Sam',
                     'Write an email to my teacher', 'Book a dentist appointment', 'Yes, go ahead',
                     'What is the best Zigbee plug on Amazon?', 'Open Spotify and then play my liked songs',
                     'Look at my screen', 'Tell me a story about dragons', 'Turn off focus mode',
                     'Turn on the hologram', 'Switch the voice to Kokoro',
                     'Make an Amazon cart with the products in my shopping list',
                     'Add everything from my notes to my Amazon cart',
                     'Remind me ' + 'about the thing ' * 6]:
            self.assertIsNone(router.choose(text, CODEX), text)

    def test_off_when_disabled_unavailable_or_already_local(self):
        mp.preferences.update(local_router={'enabled': False})
        self.assertIsNone(router.choose('Mute', CODEX))
        mp.preferences.update(local_router={})
        self.assertIsNone(router.choose('Mute', LOCAL))
        with mock.patch.object(ollama_brain, 'enabled', return_value=False):
            self.assertIsNone(router.choose('Mute', CODEX))
        with mock.patch.object(ollama_brain, 'models', return_value=[]):
            self.assertIsNone(router.choose('Mute', CODEX))
        mp.preferences.update(local_router={'model': 'other:1b'})
        with mock.patch.object(ollama_brain, 'models', return_value=['other:1b']):
            self.assertEqual(router.choose('Mute', CODEX), {'provider': 'ollama', 'model': 'other:1b', 'action': True,
                                                            'tools': router.LOCAL_TOOLS})

    def test_tool_defs_are_the_quick_subset(self):
        names = {t['name'] for t in router.tool_defs()}
        self.assertEqual(names, set(router.LOCAL_TOOLS))
        self.assertEqual({t['name'] for t in router.tool_defs(router.HOME_TOOLS)}, set(router.HOME_TOOLS))

    def test_smart_home_requests_get_only_smart_home_tools(self):
        self.assertEqual(router.choose('Open YouTube on the Apple TV', CODEX)['tools'], router.HOME_TOOLS)
        self.assertEqual(router.choose('Open YouTube', CODEX)['tools'], router.LOCAL_TOOLS)


def route(text):
    return dict(LOCAL, action=text != 'Thanks', tools=router.HOME_TOOLS if router.HOME.search(text) else router.LOCAL_TOOLS)


class BrainRoutingTest(unittest.TestCase):
    def brain(self):
        import jarvis
        selection = mp.Selection(validate=mock.Mock(), persist=mock.Mock())
        selection.active = dict(CODEX)
        selection.ready = True
        with mock.patch.object(mp, 'SELECTION', selection), mock.patch.object(jarvis.preferences, 'read', return_value={}), \
             mock.patch.object(jarvis.memory, 'prompt_section', return_value=''), mock.patch.object(jarvis.memory, 'recent_prompt', return_value=''), \
             mock.patch.object(jarvis, 'web_search_def', return_value={}):
            brain = jarvis.Brain()
        brain.config = dict(CODEX)
        brain._codex_brain = mock.Mock()
        brain.messages = [{'role': 'user', 'content': f'old {i}'} for i in range(30)]
        return brain

    def ask(self, brain, text, local_ask):
        import jarvis
        said, selected = [], []
        def run(speak):
            selected.append(brain.config)
            speak('From Codex.')
            brain.messages.append({'role': 'assistant', 'content': 'From Codex.'})
        with mock.patch.object(jarvis.router, 'choose', side_effect=lambda t, c: route(t) if t in ('Mute', 'Thanks', 'Pause the Apple TV') else None), \
             mock.patch.object(ollama_brain, 'ask', side_effect=local_ask), mock.patch.object(brain, '_run_codex', side_effect=run), \
             mock.patch.object(jarvis.memory, 'record_turn'), mock.patch.object(jarvis.hud, 'emit'), \
             mock.patch.object(jarvis, 'run_tool', return_value={'content': 'Done.'}) as tool:
            brain.ask(text, said.append)
        return said, selected, tool

    def test_quick_turn_runs_locally_with_small_tool_set_and_keeps_codex_open(self):
        brain = self.brain()
        brain._recent_context = 'PAST EXCERPT'
        brain.system = brain._compose()
        codex = brain._codex_brain
        seen = {}
        def local_ask(model, system, history, definitions, run_tool, delta, cancel, keep_alive):
            seen.update(model=model, history=len(history), tools={t['name'] for t in definitions}, keep_alive=keep_alive)
            self.assertNotIn('PAST EXCERPT', system)
            run_tool(mock.Mock(name='media_control'))
            delta('Muted.')
            return 'Muted.'
        said, selected, tool = self.ask(brain, 'Mute', local_ask)
        self.assertEqual(said, ['Muted.'])
        tool.assert_called_once()
        self.assertEqual(selected, [])
        self.assertEqual(seen, {'model': router.DEFAULT_MODEL, 'history': router.RECENT,
                                'tools': set(router.LOCAL_TOOLS), 'keep_alive': router.KEEP_ALIVE})
        self.assertEqual(brain.config, CODEX)
        codex.close.assert_not_called()
        self.assertEqual(brain.messages[-1], {'role': 'assistant', 'content': 'Muted.'})
        self.assertIn('PAST EXCERPT', brain.system)  # restored for the selected brain
        self.assertFalse(brain.selection.busy)

    def test_other_turns_use_the_selected_brain(self):
        brain = self.brain()
        said, selected, _ = self.ask(brain, 'Fix the HUD', mock.Mock())
        self.assertEqual((said, selected), (['From Codex.'], [CODEX]))

    def test_local_failure_before_anything_happened_falls_back(self):
        brain = self.brain()
        def local_ask(*args):
            raise ollama_brain.OllamaError('down')
        said, selected, _ = self.ask(brain, 'Mute', local_ask)
        self.assertEqual((said, selected), (['From Codex.'], [CODEX]))
        self.assertEqual(sum(m['content'].endswith('Mute') for m in brain.messages if m['role'] == 'user'), 1)

    def test_local_failure_after_a_tool_ran_does_not_repeat_it(self):
        import jarvis
        brain = self.brain()
        def local_ask(model, system, history, definitions, run_tool, delta, cancel, keep_alive):
            run_tool(mock.Mock(name='media_control'))
            raise ollama_brain.OllamaError('broke')
        with self.assertRaises(mp.ProviderError):
            self.ask(brain, 'Mute', local_ask)
        self.assertEqual(brain.config, CODEX)
        self.assertFalse(brain.selection.busy)

    def test_claimed_action_without_a_tool_is_dropped_for_the_selected_brain(self):
        brain = self.brain()
        def local_ask(model, system, history, definitions, run_tool, delta, cancel, keep_alive):
            delta('Muted.')
            return 'Muted.'
        said, selected, tool = self.ask(brain, 'Mute', local_ask)
        self.assertEqual((said, selected), (['From Codex.'], [CODEX]))
        tool.assert_not_called()
        self.assertNotIn({'role': 'assistant', 'content': 'Muted.'}, brain.messages)

    def test_local_turn_whose_tools_all_failed_goes_to_the_selected_brain(self):
        import jarvis
        brain = self.brain()
        def local_ask(model, system, history, definitions, run_tool, delta, cancel, keep_alive):
            jarvis.run_tool.return_value = {'content': "Error: I couldn't find 'focus'", 'is_error': True}
            run_tool(mock.Mock(name='home_control'))
            delta("I couldn't find that device.")
            return "I couldn't find that device."
        said, selected, tool = self.ask(brain, 'Mute', local_ask)
        self.assertEqual((said, selected), (['From Codex.'], [CODEX]))
        tool.assert_called_once()

    def test_local_turn_with_any_failed_tool_goes_to_the_selected_brain(self):
        import jarvis
        brain = self.brain()
        def local_ask(model, system, history, definitions, run_tool, delta, cancel, keep_alive):
            self.assertEqual({t['name'] for t in definitions}, set(router.HOME_TOOLS))
            jarvis.run_tool.side_effect = [{'content': 'Error: Living Room is off.', 'is_error': True},
                                           {'content': 'Sent turn on to Living Room.'}]
            run_tool(mock.Mock(name='home_control'))
            run_tool(mock.Mock(name='home_control'))
            delta('Apple TV paused.')
            return 'Apple TV paused.'
        said, selected, _ = self.ask(brain, 'Pause the Apple TV', local_ask)
        self.assertEqual((said, selected), (['From Codex.'], [CODEX]))

    def test_small_talk_needs_no_tool(self):
        brain = self.brain()
        def local_ask(model, system, history, definitions, run_tool, delta, cancel, keep_alive):
            delta("You're welcome.")
            return "You're welcome."
        said, selected, _ = self.ask(brain, 'Thanks', local_ask)
        self.assertEqual((said, selected), (["You're welcome."], []))


if __name__ == '__main__':
    unittest.main()
