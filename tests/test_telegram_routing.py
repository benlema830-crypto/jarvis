"""Routing tests use fake chats/providers; they never send Telegram or play audio."""
import threading
import unittest
from unittest import mock

import hud
import jarvis
import response_routing as routing
import telegram_bridge


class RoutingTest(unittest.TestCase):
    def test_concurrent_workers_keep_their_own_chat_after_turn_ends(self):
        queue = routing.CommandQueue()
        release = threading.Event()

        def work(label):
            release.wait(2)
            queue.put({'label': label, 'say': label, 'report': True, 'chime': True})

        workers = []
        for chat in (101, 202, None):
            with routing.telegram_turn(chat):
                worker = threading.Thread(target=routing.inherit(work), args=(str(chat),))
                worker.start()
                workers.append(worker)
        release.set()
        for worker in workers:
            worker.join(3)
            self.assertFalse(worker.is_alive())
        results = {item['label']: item for item in (queue.get_nowait() for _ in workers)}
        self.assertEqual(results['101']['telegram'], 101)
        self.assertEqual(results['202']['telegram'], 202)
        self.assertNotIn('telegram', results['None'])
        queue.put({'say': 'later PC reply'})
        self.assertNotIn('telegram', queue.get_nowait())

    def test_queue_does_not_mutate_or_override_explicit_destination(self):
        queue = routing.CommandQueue()
        original = {'say': 'report'}
        with routing.telegram_turn(101):
            queue.put(original)
            queue.put({'say': 'other', 'telegram': 202})
            queue.put({'prompt': 'phone', 'phone': 'phone-callback'})
        self.assertNotIn('telegram', original)
        self.assertEqual(queue.get_nowait()['telegram'], 101)
        self.assertEqual(queue.get_nowait()['telegram'], 202)
        self.assertNotIn('telegram', queue.get_nowait())

    def test_exception_restores_origin_and_inherit_captures_at_creation(self):
        queue = routing.CommandQueue()
        with self.assertRaises(ValueError):
            with routing.telegram_turn(101):
                captured = routing.inherit(lambda: queue.put({'say': 'captured'}))
                raise ValueError('test')
        with routing.telegram_turn(202):
            captured()
            queue.put({'say': 'outer'})
        queue.put({'say': 'PC'})
        self.assertEqual(queue.get_nowait()['telegram'], 101)
        self.assertEqual(queue.get_nowait()['telegram'], 202)
        self.assertNotIn('telegram', queue.get_nowait())


class TelegramDispatchTest(unittest.TestCase):
    def setUp(self):
        self.brain, self.voice = mock.Mock(), mock.Mock()
        self.queue = routing.CommandQueue()
        self.patches = [mock.patch.object(hud, 'emit'),
                        mock.patch.object(hud, 'commands', self.queue),
                        mock.patch.object(telegram_bridge.BRIDGE, 'send'),
                        mock.patch.object(telegram_bridge.BRIDGE, 'send_voice')]
        self.emit, _, self.send, self.send_voice = [p.start() for p in self.patches]
        for patch in self.patches:
            self.addCleanup(patch.stop)

    def assert_silent(self):
        self.assertEqual(self.voice.mock_calls, [])
        self.send_voice.assert_not_called()

    def test_ordinary_streamed_reply_reaches_telegram_as_text_only(self):
        def ask(prompt, deliver):
            deliver('Hello.')
            deliver('Here is the answer.')
        self.brain.ask.side_effect = ask
        self.assertTrue(jarvis.handle_telegram_item(self.brain, self.voice, {
            'telegram': 101, 'prompt': '[Via Telegram] question', 'voice_reply': True}))
        self.send.assert_called_once_with(101, 'Hello. Here is the answer.')
        self.assert_silent()

    def test_task_completion_keeps_full_report_and_history_without_audio(self):
        report = 'A complete report. ' * 60
        self.assertTrue(jarvis.handle_telegram_item(self.brain, self.voice, {
            'telegram': 101, 'say': report, 'note': '[TASK FINISHED] plug paired',
            'report': True, 'chime': True}))
        self.send.assert_called_once_with(101, report)
        self.brain.note.assert_called_once_with('[TASK FINISHED] plug paired', report)
        self.brain.ask.assert_not_called()
        self.assert_silent()

    def test_task_started_during_telegram_turn_delivers_after_a_pc_turn(self):
        def ask(prompt, deliver):
            self.worker = routing.inherit(lambda: hud.commands.put({
                'label': 'Done', 'say': 'Air Purifier paired.', 'report': True, 'chime': True}))
            deliver('Working on it.')
        self.brain.ask.side_effect = ask
        jarvis.respond_telegram(self.brain, self.voice, {'telegram': 101, 'prompt': '[Via Telegram] pair plug'})
        # A later local request cannot change the destination captured by this job.
        hud.commands.put({'label': 'PC', 'say': 'Local reply'})
        thread = threading.Thread(target=self.worker)
        thread.start()
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertFalse(jarvis.handle_telegram_item(self.brain, self.voice, self.queue.get_nowait()))
        jarvis.handle_telegram_item(self.brain, self.voice, self.queue.get_nowait())
        self.assertEqual(self.send.call_args_list, [mock.call(101, 'Working on it.'), mock.call(101, 'Air Purifier paired.')])
        self.assert_silent()

    def test_prompt_followup_inherits_origin_for_further_work(self):
        def ask(prompt, deliver):
            hud.commands.put({'label': 'Follow-up', 'say': 'Next result'})
            deliver('Summarized result.')
        self.brain.ask.side_effect = ask
        jarvis.handle_telegram_item(self.brain, self.voice, {'telegram': 202, 'prompt': '[MCP RESULT] data', 'chime': True})
        self.send.assert_called_once_with(202, 'Summarized result.')
        self.assertEqual(self.queue.get_nowait()['telegram'], 202)
        self.assert_silent()

    def test_provider_and_delivery_errors_never_fall_back_to_pc_speech(self):
        self.brain.ask.side_effect = RuntimeError('fake provider failure')
        jarvis.handle_telegram_item(self.brain, self.voice, {'telegram': 101, 'prompt': '[Via Telegram] question'})
        self.assertIn('lost my train of thought', self.send.call_args.args[1])
        self.send.side_effect = RuntimeError('fake network failure')
        jarvis.handle_telegram_item(self.brain, self.voice, {'telegram': 101, 'say': 'Report'})
        self.assertTrue(any('Telegram reply failed' in str(c) for c in self.emit.call_args_list))
        self.assert_silent()

    def test_pc_and_phone_items_are_left_to_existing_dispatch(self):
        for item in ({'say': 'PC report', 'chime': True}, {'phone': mock.Mock(), 'prompt': 'Phone'}):
            self.assertFalse(jarvis.handle_telegram_item(self.brain, self.voice, item))
        self.send.assert_not_called()


class BackgroundEntryPointTest(unittest.TestCase):
    def setUp(self):
        self.queue = routing.CommandQueue()
        patch = mock.patch.object(hud, 'commands', self.queue)
        patch.start()
        self.addCleanup(patch.stop)

    def test_terminal_and_screen_start_capture_destination(self):
        import agent
        import terminal
        with mock.patch.object(agent.anthropic, 'Anthropic'), \
                mock.patch.object(agent.Agent, '_configure_screen'), \
                mock.patch.object(terminal, '_claude_exe', return_value='fake.exe'), \
                mock.patch.object(hud, 'emit'):
            for worker in (terminal.TerminalWorker(), agent.Agent()):
                def finish(*args):
                    self.queue.put({'label': 'Completed', 'say': 'Result', 'chime': True})
                with mock.patch.object(worker, '_run', side_effect=finish):
                    with routing.telegram_turn(101):
                        worker.start('Test work')
                    worker._thread.join(3)
                self.assertFalse(worker._thread.is_alive())
                self.assertEqual(self.queue.get_nowait()['telegram'], 101)

    def test_research_summary_keeps_destination(self):
        import research
        import tools
        finished = threading.Event()

        def work(run, done, *args):
            try:
                done({'ok': True, 'summary': 'Findings', 'topic': 'Test topic', 'note': 'fake.md'})
            finally:
                finished.set()

        with mock.patch.object(research, '_load', return_value={'runs': []}), \
                mock.patch.object(research, '_save'), mock.patch.object(research, '_work', side_effect=work):
            with routing.telegram_turn(101):
                research.start('Test topic', on_done=tools._research_done)
            self.assertTrue(finished.wait(3))
        self.assertEqual(self.queue.get_nowait()['telegram'], 101)

    def test_deferred_approval_question_and_result_keep_destination(self):
        import approvals
        import tools

        def ask(*args, **kwargs):
            self.queue.put({'label': 'Question', 'say': 'May I proceed?', 'chime': True})
            return False, 'no'

        def work():
            self.fail('Declined work must never execute')

        # A queue read waits for the real approval worker; it does not change any settings.
        with mock.patch.object(approvals, 'ask', side_effect=ask):
            with routing.telegram_turn(101):
                tools._after_approval('Test approval', work, 'Test', declined='Declined')
            question = self.queue.get(timeout=3)
            result = self.queue.get(timeout=3)
        self.assertEqual(question['telegram'], 101)
        self.assertEqual(result['telegram'], 101)
        self.assertEqual(result['say'], 'Declined')


if __name__ == '__main__':
    unittest.main()
