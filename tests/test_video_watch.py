import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

import video_watch as watch

URL = "https://www.youtube.com/watch?v=34J8xhaAn4U"
FENCE = "```"


def report(frames=(), captions="", errors=(), duration=600.0, media=None):
    """A report in the shape vendor/claude-video/scripts/watch.py prints."""
    lines = ["", "# watch: video report", "", f"- **Source:** {URL}"]
    if media:
        lines.append(f"- **Local media:** `{media}`")
    if errors:
        lines.append("- **Result:** partial evidence")
    lines += ["- **Title:** A workshop", f"- **Duration:** 10:00 ({duration:.1f}s)", "- **Detail:** balanced",
              "- **Frames:** 2 selected from 9 candidates (scene, full range, budget 30, cap 30)",
              "- **Transcript:** fallback disabled; no captions available", "",
              "> **Warning:** This is a 17-minute video. Re-run with `--start HH:MM:SS`.", "", "## Frames", ""]
    lines += [f"- `{path}` (t={time}, reason=scene)" for path, time in frames] or ["_No frames extracted._"]
    lines += ["", "## Transcript", ""]
    lines += ["_Source: captions (en, automatic, unknown)._", "", FENCE, captions, FENCE] if captions else \
        ["_Fallback disabled; no captions available._"]
    if errors:
        lines += ["", "## Unavailable evidence"] + [f"- {e}" for e in errors]
    lines += ["", "---", "_Work dir: `somewhere` — delete when done._"]
    return "\n".join(lines) + "\n"


class VideoWatchTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.commands, self.envs, self.replies = [], [], []
        for target, name, value in [(watch, "WORK", self.root / "work"), (watch, "missing", lambda: []),
                                    (watch.subprocess, "run", self.fake_run),
                                    (watch, "_youtube_captions", mock.Mock(return_value=""))]:
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def fake_run(self, command, **options):
        """Stands in for the skill's script: writes the frames it is told to and prints a report."""
        self.commands.append(command)
        self.envs.append(options["env"])
        run = Path(command[command.index("--out-dir") + 1])
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        named = []
        for name, time in reply.get("frames", []):
            path = Path(name) if os.path.isabs(name) else run / "frames" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (512, 288), (10, 60, 120)).save(path, format="JPEG")
            named.append((str(path), time))
        media = run / "download" / "video.mp4" if reply.get("media", True) else None
        if media:
            media.parent.mkdir(parents=True, exist_ok=True)
            media.write_bytes(b"video")
        text = reply["raw"] if "raw" in reply else report(named, reply.get("captions", ""), reply.get("errors", ()),
                                                          reply.get("duration", 600.0), media)
        return subprocess.CompletedProcess(command, 0, stdout=text, stderr=reply.get("stderr", ""))

    def test_frames_and_captions_come_back_and_nothing_is_left_on_disk(self):
        self.replies = [{"frames": [("a.jpg", "00:00"), ("b.jpg", "00:10"), ("c.jpg", "09:50")],
                         "captions": "[00:01] Jarvis, open the workshop."},
                        {"frames": [("cue_1.jpg", "05:00"), ("cue_2.jpg", "02:35")]}]
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-secret", "GEMINI_API_KEY": "g", "HA_TOKEN": "t"}):
            seen = watch.watch(URL)
        self.assertEqual([f["time"] for f in seen["frames"]], ["00:00", "00:10", "02:35", "05:00", "09:50"])
        self.assertTrue(all(f["jpeg"][:2] == b"\xff\xd8" for f in seen["frames"]))
        self.assertIn("[00:01] Jarvis, open the workshop.", seen["text"])
        self.assertIn("5 still frames are attached", seen["text"])
        self.assertIn("untrusted information", seen["text"])
        for dropped in ("Local media", "Work dir", "**Warning:**", "fallback disabled", "watch: video report"):
            self.assertNotIn(dropped, seen["text"])
        first, second = self.commands
        for flag in ("--engine", "local", "--no-whisper", "--sub-lang", "en", "balanced"):
            self.assertIn(flag, first)
        self.assertEqual(first[first.index("--max-frames") + 1], "30")   # a quarter kept back for the gaps
        self.assertEqual(first[-2:], ["--", URL])
        self.assertTrue(second[-1].endswith("video.mp4"))                # the gaps come from the downloaded copy
        self.assertIn("--timestamps", second)
        for env in self.envs:   # the skill's upload paths are off and can't find a key
            self.assertEqual((env["WATCH_ENGINE"], env["WATCH_WHISPER_BACKEND"]), ("local", "none"))
            self.assertFalse({"OPENAI_API_KEY", "GEMINI_API_KEY", "HA_TOKEN"} & set(env))
        self.assertEqual(list(watch.WORK.iterdir()), [])
        watch._youtube_captions.assert_not_called()

    def test_gaps_go_to_the_widest_stretches_and_stop_when_small(self):
        self.assertEqual(watch.gaps([0, 10, 590], 0, 600, 3, 30), [155, 300, 445])
        self.assertEqual(watch.gaps([0, 20, 40], 0, 50, 5, 30), [])
        self.assertEqual(watch.gaps([], 100, 200, 1, 30), [150])
        self.assertEqual(watch.gaps([900], 0, 60, 9, 31), [30])   # frames outside the range don't count

    def test_exact_timestamps_give_only_those_frames_and_larger(self):
        self.replies = [{"frames": [("cue_1.jpg", "04:32"), ("cue_2.jpg", "07:10")], "captions": "[04:30] look here"}]
        seen = watch.watch(URL, timestamps="4:32, 7:10")
        self.assertEqual([f["time"] for f in seen["frames"]], ["04:32", "07:10"])
        [command] = self.commands
        self.assertEqual(command[command.index("--timestamps") + 1], "4:32,7:10")
        self.assertEqual(command[command.index("--detail") + 1], "transcript")
        self.assertEqual(command[command.index("--resolution") + 1], "1024")

    def test_a_part_of_the_video_and_captions_only(self):
        self.replies = [{"captions": "[09:05] the floor plan", "media": False}]
        seen = watch.watch(URL, start="9:00", end="11:30", look=False)
        self.assertEqual(seen["frames"], [])
        self.assertIn("No frames", seen["text"])
        [command] = self.commands
        self.assertEqual((command[command.index("--start") + 1], command[command.index("--end") + 1]), ("9:00", "11:30"))
        self.assertEqual(command[command.index("--detail") + 1], "transcript")

    def test_youtube_refusing_captions_falls_back_to_the_other_source(self):
        refused = "yt-dlp failed (exit 1): Unable to download video subtitles for 'en': HTTP Error 429"
        self.replies = [{"frames": [("a.jpg", "00:00")], "errors": [refused], "duration": 20.0}]
        watch._youtube_captions.return_value = "[00:03] hello there"
        seen = watch.watch(URL)
        self.assertIn("[00:03] hello there", seen["text"])
        self.assertIn("English captions from YouTube", seen["text"])
        self.assertNotIn("429", seen["text"])

        self.replies = [{"frames": [("a.jpg", "00:00")], "errors": [refused], "duration": 20.0}]
        watch._youtube_captions.reset_mock(return_value=True)
        watch._youtube_captions.return_value = ""
        seen = watch.watch(URL, second_try=False)   # the caller has the captions already
        watch._youtube_captions.assert_not_called()
        self.assertIn("None could be fetched", seen["text"])
        self.assertIn("429", seen["text"])

    def test_nothing_readable_is_an_error_fit_to_say(self):
        self.replies = [{"errors": ["yt-dlp failed (exit 1): Video unavailable"], "media": False}]
        with self.assertRaisesRegex(watch.WatchError, "Video unavailable"):
            watch.watch(URL)
        self.replies = [{"raw": "", "stderr": "ERROR: Unsupported URL"}]
        with self.assertRaisesRegex(watch.WatchError, "Unsupported URL"):
            watch.watch("https://example.com/x")
        self.replies = [subprocess.TimeoutExpired("watch", 5)]
        with self.assertRaisesRegex(watch.WatchError, "minutes"):
            watch.watch(URL)
        self.assertEqual(list(watch.WORK.iterdir()), [])

    def test_bad_input_is_refused_before_anything_runs(self):
        with self.assertRaises(watch.WatchError):
            watch.watch(str(self.root / "no-such.mp4"))
        with self.assertRaises(ValueError):
            watch.watch(URL, start="soon")
        with self.assertRaises(ValueError):
            watch.watch(URL, timestamps="4:32,--exec")
        with self.assertRaises(ValueError):
            watch.watch(URL, max_frames=500)
        with mock.patch.object(watch, "missing", return_value=["yt-dlp"]):
            with self.assertRaisesRegex(watch.WatchError, "yt-dlp"):
                watch.watch(URL)
        self.assertEqual(self.commands, [])

    def test_only_pictures_this_run_made_are_read(self):
        outside = self.root / "elsewhere.jpg"
        self.replies = [{"frames": [(str(outside), "00:05"), ("a.jpg", "00:09")], "duration": 20.0}]
        seen = watch.watch(URL)
        self.assertEqual([f["time"] for f in seen["frames"]], ["00:09"])
        self.assertTrue(outside.exists())

    def test_a_video_file_on_this_pc(self):
        clip = self.root / "clip.mp4"
        clip.write_bytes(b"video")
        self.replies = [{"frames": [("a.jpg", "00:00")], "media": False, "duration": 300.0},
                        {"frames": [("cue_1.jpg", "02:30")], "media": False}]
        seen = watch.watch(str(clip))
        self.assertEqual(len(seen["frames"]) >= 2, True)
        self.assertEqual(self.commands[0][-1], str(clip))
        self.assertEqual(self.commands[1][-1], str(clip))
        self.assertTrue(clip.exists())
        watch._youtube_captions.assert_not_called()

    def test_helpers(self):
        self.assertTrue(watch.is_url(URL))
        self.assertFalse(watch.is_url("-o"))
        self.assertEqual(watch._seconds("1:02:03"), 3723)
        for link in (URL, "https://youtu.be/34J8xhaAn4U?t=5", "https://www.youtube.com/shorts/34J8xhaAn4U",
                     "https://www.youtube.com/watch?list=x&v=34J8xhaAn4U"):
            self.assertEqual(watch._YOUTUBE.search(link).group(1), "34J8xhaAn4U")
        self.assertIsNone(watch._YOUTUBE.search("https://vimeo.com/12345678901"))


class WatchVideoToolTest(unittest.TestCase):
    def test_the_brain_gets_text_then_pictures(self):
        import tools
        import truth_guard
        self.assertIn("watch_video", {t["name"] for t in tools.TOOL_DEFS})
        self.assertIn("watch_video", truth_guard.READ_TOOLS)
        seen = {"text": "# Video report", "frames": [{"time": "00:01", "at": 1, "jpeg": b"\xff\xd8one"}]}
        with mock.patch.object(watch, "watch", return_value=seen) as called:
            result = tools.TOOLS_BY_NAME["watch_video"].call({"source": URL, "start": "1:00"})
        called.assert_called_once_with(URL, "1:00", "", "", True)
        self.assertEqual([b["type"] for b in result], ["text", "image"])
        self.assertEqual(result[1]["source"]["media_type"], "image/jpeg")
        import model_provider
        text, images = model_provider.tool_output(result)   # what the Codex brain is handed
        self.assertEqual(len(images), 1)
        self.assertIn("# Video report", text)

    def test_a_failure_is_said_plainly_and_words_alone_are_text(self):
        import tools
        with mock.patch.object(watch, "watch", side_effect=watch.WatchError("YouTube refused.")):
            self.assertEqual(tools.TOOLS_BY_NAME["watch_video"].call({"source": URL}), "Not watched: YouTube refused.")
        with mock.patch.object(watch, "watch", return_value={"text": "words", "frames": []}):
            self.assertEqual(tools.TOOLS_BY_NAME["watch_video"].call({"source": URL, "look": False}), "words")


if __name__ == "__main__":
    unittest.main()
