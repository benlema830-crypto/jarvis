"""Pacing, actual playback timing, workload cleanup and audio recovery without hardware."""
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import conversation_settings as settings
import runtime_metrics as metrics
import voice
import voice_health as health


class ConversationRuntimeTest(unittest.TestCase):
    def test_audio_stream_separates_channels_and_sends_silence(self):
        import hud
        output=Mock(side_effect=[.06,0])
        microphone=Mock(side_effect=[.03,0])
        with patch.object(hud,'emit') as emit, patch.object(hud.time,'sleep',side_effect=[None,StopIteration]):
            with self.assertRaises(StopIteration):hud._level_loop(output,microphone)
        self.assertEqual(emit.call_args_list[0].kwargs,{'v':.06,'output':.06,'input':.03})
        self.assertEqual(emit.call_args_list[1].kwargs,{'v':0,'output':0,'input':0})

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patches = [patch.object(settings, 'STORE', Path(self.temp.name)/'pacing.json'),
                   patch.object(settings, '_cache', (0., None)),
                   patch.multiple(metrics, _samples={}, _active={}, _turn=None, _sequence=0, _emit=None),
                   patch.multiple(health, _recoveries={}, _recovering=set())]
        for p in patches:
            p.start(); self.addCleanup(p.stop)

    def test_pacing_persists_and_rejects_unbounded_values(self):
        settings.update({'pause_seconds': 1.6, 'followup_seconds': 20})
        with patch.object(settings, '_cache', (0., None)):
            self.assertEqual(settings.read()['pause_seconds'], 1.6)
        for value in [float('nan'), float('inf'), True, -.1, 1000]:
            with self.assertRaises(ValueError):
                settings.update({'pause_seconds': value})

    def test_long_first_sentence_starts_at_clause_without_changing_words(self):
        buf = voice.SentenceBuffer()
        first = 'I have reviewed the changes in your project and identified the cause of the problem, '
        rest = 'so I will fix the failing import and then run the relevant checks. '
        chunks = buf.feed(first + 'so I')
        self.assertEqual(chunks, [first.strip()])
        chunks += buf.feed(rest[4:])
        chunks += [buf.flush()]
        self.assertEqual(' '.join(filter(None, chunks)), (first+rest).strip())

    def test_workload_clears_on_failure_and_does_not_store_content(self):
        events=[];metrics.bind(lambda *a, **kw: events.append((a,kw)))
        with self.assertRaises(RuntimeError), metrics.work('recognition'):
            self.assertEqual(metrics.snapshot()['active'], ['recognition'])
            raise RuntimeError('private content')
        self.assertEqual(metrics.snapshot()['active'], [])
        self.assertNotIn('private', str(metrics.snapshot()))
        self.assertEqual(events[-1][1]['active'], [])

    def test_turn_latency_is_first_occurrence_from_speech_end(self):
        with patch.object(metrics.time, 'monotonic', return_value=10):
            metrics.begin_turn(8, 'voice')
        with patch.object(metrics.time, 'monotonic', return_value=11):
            metrics.mark('first_audio')
        with patch.object(metrics.time, 'monotonic', return_value=12):
            metrics.mark('first_audio');metrics.mark('complete')
        self.assertEqual(metrics.snapshot()['turn']['stages']['first_audio'], 3000)
        self.assertEqual(metrics.snapshot()['timings']['first_audio']['samples'], 1)

    def test_failed_recovery_backs_off_without_changing_voice_lock(self):
        device=SimpleNamespace(recover_input=Mock(side_effect=OSError), voiceprint='enrolled')
        with patch.object(health, '_ears', device):
            self.assertEqual(health.recover('microphone')['status'], 'failed')
            self.assertEqual(health.recover('microphone')['status'], 'waiting')
        device.recover_input.assert_called_once()
        self.assertEqual(device.voiceprint, 'enrolled')

    def test_recovery_monitor_only_reopens_failed_components(self):
        ears=SimpleNamespace(stream=SimpleNamespace(active=True), last_input=10, pause_seconds=1.2)
        speaker=SimpleNamespace(_player=SimpleNamespace(_stream=SimpleNamespace(active=False)))
        with patch.multiple(health, _ears=ears, _voice=speaker, _phase='ready'), \
             patch.object(health.time, 'monotonic', return_value=11), patch.object(health, 'recover') as recover:
            health.recovery_tick()
        recover.assert_called_once_with('output', automatic=True)

    def test_open_output_with_stalled_callbacks_is_recovered(self):
        speaker=SimpleNamespace(_player=SimpleNamespace(_stream=SimpleNamespace(active=True), last_callback=3))
        with patch.multiple(health, _ears=None, _voice=speaker, _phase='ready'), \
             patch.object(health.time, 'monotonic', return_value=10), patch.object(health, 'recover') as recover:
            health.recovery_tick()
        recover.assert_called_once_with('output', automatic=True)


if __name__ == '__main__':
    unittest.main()
