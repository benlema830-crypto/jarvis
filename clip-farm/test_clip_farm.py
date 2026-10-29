import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import clip_farm as farm


class HighlightTests(unittest.TestCase):
    def test_distinct_peaks_rank_and_do_not_overlap(self):
        levels = [0.01] * 180
        levels[20], levels[100], levels[150] = 0.5, 1, 0.7
        clips = farm.rank_highlights(levels, [0] * 180, 90, 15, 3)
        self.assertEqual([c["peak"] for c in clips], [50.25, 75.25, 10.25])
        for a in clips:
            self.assertGreaterEqual(a["start"], 0)
            self.assertLessEqual(a["end"], 90)
            self.assertEqual(a["end"] - a["start"], 15)
        for a, b in zip(sorted(clips, key=lambda c: c["start"]),
                        sorted(clips, key=lambda c: c["start"])[1:]):
            self.assertLessEqual(a["end"], b["start"])

    def test_chat_can_change_winner(self):
        levels = [0.01] * 160
        levels[20], levels[120] = 1, 0.8
        chat = [0] * 160
        chat[120] = 10
        clips = farm.rank_highlights(levels, chat, 80, 15, 1, 0.7)
        self.assertEqual(clips[0]["peak"], 60.25)

    def test_flat_audio_has_no_fabricated_highlights(self):
        self.assertEqual(farm.rank_highlights([0] * 40, [0] * 40, 20, 15, 5), [])

    def test_edge_peak_is_clamped_and_short_sources_rejected_by_cli(self):
        clips = farm.rank_highlights([0] * 39 + [1], [0] * 40, 20, 15, 5)
        self.assertEqual(clips[0]["start"], 5)
        self.assertEqual(len(clips), 1)

    def test_chat_formats_offset_and_invalid_timestamp(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "chat.json"
            path.write_text(json.dumps({"comments": [{"content_offset_seconds": 10}]}))
            rates = farm.chat_rates(path, 80, 10)
            self.assertEqual(rates[40], 0.2)
            self.assertEqual(rates[20], 0)
            path.write_text('[{"time_seconds": "nan"}]')
            with self.assertRaises(ValueError):
                farm.chat_rates(path, 80)

    def test_srt_times_clamped_and_markup_removed(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "caption.srt"
            word = SimpleNamespace(start=-1, end=20, word="Hello {bad} <tag>")
            segment = SimpleNamespace(words=[word])
            self.assertEqual(farm.write_srt([segment], path, 15), 1)
            output = path.read_text()
            self.assertIn("00:00:00,000 --> 00:00:15,000", output)
            self.assertNotIn("{", output)
            with self.assertRaises(FileExistsError):
                farm.write_srt([], path, 15)

    def test_invalid_cli_ranges_and_url_permission(self):
        for args in (["missing.mp4", "--duration", "5"],
                     ["missing.mp4", "--top", "0"],
                     ["https://example.invalid/video", "--no-captions"]):
            with self.assertRaises(ValueError):
                farm.main(args)


if __name__ == "__main__":
    unittest.main()
