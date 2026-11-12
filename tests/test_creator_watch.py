import datetime
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import creator_watch as watch
import knowledge

TODAY = datetime.date.today().isoformat()
OLD = "2026-01-01"
REPORT = """## Spoken summary
He added a 3D workshop that Fable builds models in. Worth trying in our Holo view.
## What's new in his Jarvis
- A workshop [02:28]
## How he built it
three.js (inferred).
## Compared with our Jarvis
Missing.
## Worth adding
1. Workshop (large).
## Free resources
None."""


def video(ident, title, published=OLD, description=""):
    return {"id": ident, "title": title, "published": published, "description": description,
            "url": f"https://www.youtube.com/watch?v={ident}"}


class CreatorWatchTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root / "vault").mkdir()
        for target, field, value in [(knowledge, "VAULT", root / "vault"), (watch, "STORE", root / "watch.json")]:
            patcher = mock.patch.object(target, field, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.vault = root / "vault"
        self.real_transcript = watch.transcript
        self.real_frames = watch.frames
        self.feed = [video("a1", "My AI assistant Jarvis")]
        self.repos = [{"name": "holo-gestures", "pushed": "2026-09-01T00:00:00Z", "description": "", "url": "u"}]
        for name, fake in [("videos", lambda _: list(self.feed)), ("repos", lambda _: list(self.repos)),
                           ("commits", lambda *_: ["Add exploded views"]),
                           ("transcript", lambda _: "[00:01] Jarvis, open the workshop."),
                           ("frames", lambda _: list(self.pictures))]:
            patcher = mock.patch.object(watch, name, side_effect=fake)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.asked = []
        self.pictures = []   # no frames unless a test says so; the real ones download the video
        self.images = []

    def ask(self, system, text, label, images=None):
        self.asked.append((system, text))
        self.images.append(images)
        return REPORT

    def notes(self):
        return sorted(p.relative_to(self.vault).as_posix() for p in self.vault.rglob("*.md"))

    def test_first_check_only_records_what_exists(self):
        self.assertEqual(watch.check(self.ask), [])
        self.assertEqual(self.notes(), [])
        self.assertEqual(self.asked, [])
        self.assertEqual(watch.check(self.ask), [])  # nothing changed since

    def test_new_jarvis_video_is_written_up_and_announced(self):
        watch.check(self.ask)
        self.feed.insert(0, video("b2", "Fable 5.2 Just Took My JARVIS to a Whole New Level",
                                  description="Free pack https://www.skool.com/aiworkshop-lite\n"
                                              "Paid https://www.skool.com/aiworkshop"))
        news = watch.check(self.ask)
        self.assertEqual(len(news), 1)
        self.assertIn("3D workshop", news[0]["say"])
        [note] = news[0]["notes"]
        self.assertTrue(note.startswith("Research/Zubair watch/"))
        text = (self.vault / note).read_text(encoding="utf-8")
        self.assertIn("skool.com/aiworkshop-lite", text)
        self.assertNotIn("https://www.skool.com/aiworkshop\n", text)
        self.assertIn("paid community link removed", text)
        self.assertIn("[00:01] Jarvis, open the workshop.", text)
        self.assertIn("Transcript:", self.asked[0][1])
        self.assertEqual(watch.check(self.ask), [])  # not announced twice

    def test_codex_also_looks_at_frames_of_the_video(self):
        watch.check(self.ask)
        self.assertEqual(self.images, [])
        self.pictures = [{"time": "02:28", "at": 148, "jpeg": b"\xff\xd8one"}, {"time": "05:20", "at": 320, "jpeg": b"\xff\xd8two"}]
        self.feed.insert(0, video("h8", "Jarvis workshop"))
        news = watch.check(self.ask)
        self.assertEqual(self.images, [[b"\xff\xd8one", b"\xff\xd8two"]])
        self.assertIn("2 still frames", self.asked[0][1])
        text = (self.vault / news[0]["notes"][0]).read_text(encoding="utf-8")
        self.assertIn("source: Codex read the transcript and looked at 2 still frames", text)

    def test_codex_refusing_the_frames_falls_back_to_the_transcript(self):
        watch.check(self.ask)
        self.pictures = [{"time": "02:28", "at": 148, "jpeg": b"\xff\xd8one"}]
        self.feed.insert(0, video("i9", "Jarvis workshop"))
        news = watch.check(lambda system, text, label, images=None: None if images else REPORT)
        text = (self.vault / news[0]["notes"][0]).read_text(encoding="utf-8")
        self.assertIn("source: Codex read the transcript;", text)
        self.assertIn("3D workshop", news[0]["say"])

    def test_frames_that_cant_be_had_are_just_left_out(self):
        import video_watch
        with mock.patch.object(video_watch, "watch", side_effect=video_watch.WatchError("blocked")):
            self.assertEqual(self.real_frames("https://www.youtube.com/watch?v=x"), [])
        seen = {"text": "", "frames": [{"time": "00:01", "at": 1, "jpeg": b"j"}]}
        with mock.patch.object(video_watch, "watch", return_value=seen) as called:
            self.assertEqual(self.real_frames("https://www.youtube.com/watch?v=x"), seen["frames"])
        called.assert_called_once_with("https://www.youtube.com/watch?v=x", max_frames=watch.FRAMES, second_try=False)

    def test_other_videos_and_repo_changes_go_in_one_updates_note_without_ai(self):
        watch.check(self.ask)
        self.feed.insert(0, video("c3", "I Tested 8 AI Video Models"))
        self.repos[0] = dict(self.repos[0], pushed="2026-11-11T00:00:00Z")
        self.repos.append({"name": "new-thing", "pushed": "2026-11-11T00:00:00Z", "description": "A tool",
                           "url": "u2"})
        news = watch.check(self.ask)
        self.assertEqual(self.asked, [])
        [note] = news[0]["notes"]
        text = (self.vault / note).read_text(encoding="utf-8")
        for expected in ("I Tested 8 AI Video Models", "Repo updated", "Add exploded views", "New repo"):
            self.assertIn(expected, text)
        self.assertIn("GitHub", news[0]["say"])

    def test_brand_new_video_without_captions_is_retried(self):
        watch.check(self.ask)
        self.feed.insert(0, video("d4", "Jarvis gets hands", published=TODAY))
        with mock.patch.object(watch, "transcript", return_value=None):
            self.assertEqual(watch.check(self.ask), [])
        news = watch.check(self.ask)  # captions are up now
        self.assertEqual(len(news), 1)
        self.assertEqual(len(self.asked), 1)

    def test_youtube_refusing_the_transcript_means_try_later_even_for_old_videos(self):
        watch.check(self.ask)
        self.feed.insert(0, video("g7", "Jarvis offline"))
        with mock.patch.object(watch, "transcript", side_effect=watch.NoCaptionsYet("g7")):
            self.assertEqual(watch.check(self.ask), [])
        self.assertEqual(self.notes(), [])
        self.assertEqual(len(watch.check(self.ask)), 1)

    def test_transcript_sorts_missing_captions_from_refusals(self):
        import youtube_transcript_api as api
        with mock.patch.object(watch, "transcript", self.real_transcript):
            with mock.patch.object(api.YouTubeTranscriptApi, "fetch", side_effect=api.TranscriptsDisabled("x")):
                self.assertIsNone(watch.transcript("x"))
            with mock.patch.object(api.YouTubeTranscriptApi, "fetch", side_effect=api.IpBlocked("x")):
                with self.assertRaises(watch.NoCaptionsYet):
                    watch.transcript("x")

    def test_old_video_without_captions_is_still_noted(self):
        watch.check(self.ask)
        self.feed.insert(0, video("e5", "Jarvis offline"))
        with mock.patch.object(watch, "transcript", return_value=None):
            news = watch.check(self.ask)
        self.assertIn("no captions", news[0]["say"])
        self.assertEqual(self.asked, [])

    def test_failed_source_doesnt_flood_later(self):
        with mock.patch.object(watch, "videos", side_effect=watch.requests.ConnectionError()):
            watch.check(self.ask)
        state = json.loads(watch.STORE.read_text(encoding="utf-8"))
        self.assertFalse(state["creators"]["Zubair Trabzada"].get("ready"))
        self.assertEqual(watch.check(self.ask), [])  # the next full look is still only a baseline
        self.assertEqual(self.notes(), [])

    def test_codex_unavailable_still_saves_the_transcript(self):
        watch.check(self.ask)
        self.feed.insert(0, video("f6", "Jarvis update"))
        news = watch.check(lambda *_: None)
        text = (self.vault / news[0]["notes"][0]).read_text(encoding="utf-8")
        self.assertIn("Codex wasn't available", text)
        self.assertIn("open the workshop", text)

    def test_settings_and_describe(self):
        with mock.patch.object(watch.preferences, "read", return_value={"creator_watch": {"hours": 99}}):
            self.assertEqual(watch.settings(), {"enabled": True, "hours": watch.HOURS})
        with mock.patch.object(watch.preferences, "read", return_value={"creator_watch": {"enabled": False}}):
            self.assertFalse(watch.settings()["enabled"])
        self.assertIn("hasn't checked", watch.describe())
        watch.check(self.ask)
        self.assertIn("Nothing new", watch.describe())


if __name__ == "__main__":
    unittest.main()
