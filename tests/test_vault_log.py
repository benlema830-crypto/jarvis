import datetime
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import knowledge
import vault_log


class VaultLogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for target, value in ((knowledge, ("VAULT", root / "vault")),
                              (vault_log, ("TRANSCRIPTS", root / "transcripts"))):
            patcher = mock.patch.object(target, *value)
            patcher.start()
            self.addCleanup(patcher.stop)
        (root / "vault").mkdir()
        (root / "transcripts").mkdir()
        self.root = root

    def day_log(self, day, lines):
        stamp = datetime.datetime.fromisoformat(day + "T10:00").timestamp()
        with open(self.root / "transcripts" / f"{day}.jsonl", "w", encoding="utf-8") as f:
            for i, (kind, text) in enumerate(lines):
                f.write(json.dumps({"type": kind, "t": stamp + i, "text": text}) + "\n")

    def test_report_note_is_created_and_never_overwritten(self):
        first = vault_log.save_report("screen agent", "Make a Spotify playlist called Focus", True, "Playlist made.", 1793000000)
        second = vault_log.save_report("screen agent", "Make a Spotify playlist called Focus", False, "Couldn't.", 1793000000)
        self.assertTrue(first.startswith("Reports/") and first != second)
        text = knowledge.read(first)["content"]
        self.assertIn("Playlist made.", text)
        self.assertIn("status: finished", text)

    def test_journal_uses_summary_and_links_that_days_reports(self):
        day = "2026-10-25"
        self.day_log(day, [("you", "Turn off the RGB"), ("jarvis", "Done."), ("event", "ignored")])
        vault_log.save_report("terminal task", "Turn off the RGB", True, "Done.",
                              datetime.datetime.fromisoformat(day + "T11:00").timestamp())
        with mock.patch.object(vault_log, "_summarize", return_value="## Summary\nRGB turned off.") as summarize:
            path = vault_log.write_day(day)
        rows = summarize.call_args.args[1]
        self.assertEqual([who for _, who, _ in rows], ["You", "Jarvis"])
        content = knowledge.read(path)["content"]
        self.assertIn("RGB turned off.", content)
        self.assertIn("[[Reports/2026-10-25 1100 Turn off the RGB]]", content)
        self.assertIsNone(vault_log.write_day(day))  # an existing day is left alone

    def test_without_codex_the_day_is_a_plain_list(self):
        self.day_log("2026-10-24", [("you", "What's the weather?"), ("jarvis", "Rain.")])
        with mock.patch.object(vault_log, "_summarize", return_value=None):
            path = vault_log.write_day("2026-10-24")
        self.assertIn("What's the weather?", knowledge.read(path)["content"])

    def test_catch_up_skips_today_and_quiet_days(self):
        today = datetime.date(2026, 10, 26)
        self.day_log("2026-10-26", [("you", "today")])
        self.day_log("2026-10-25", [("you", "yesterday")])
        self.day_log("2026-10-23", [("jarvis", "only Jarvis spoke")])
        with mock.patch.object(vault_log, "_summarize", return_value="## Summary\nok"):
            written = vault_log.catch_up(today)
        self.assertEqual(written, ["Journal/2026-10-25.md"])


if __name__ == "__main__":
    unittest.main()
