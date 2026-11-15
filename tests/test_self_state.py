"""Jarvis's live view of himself: when he started, what's waiting for a restart, what's pushed."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import self_state


class SelfStateTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        patcher = mock.patch.object(self_state, "STORE", Path(temp.name) / "self_state.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        self_state._cache.update(at=0.0, line="")
        self.git = {}
        git = mock.patch.object(self_state, "_git", side_effect=lambda *a, **k: self.git.get(a[0]))
        git.start()
        self.addCleanup(git.stop)

    def mark(self, commit="abc1234def", started=None):
        self_state.STORE.write_text(json.dumps({"pid": os.getpid(), "commit": commit,
                                                "started": started or time.time() - 60}), encoding="utf-8")

    def test_nothing_recorded_means_nothing_said(self):
        self.assertEqual(self_state.line(), "")

    def test_a_stopped_jarvis_is_not_described(self):
        self_state.STORE.write_text(json.dumps({"pid": 999999999, "started": time.time(), "commit": "x"}))
        self.assertIsNone(self_state.started())

    def test_up_to_date_and_pushed(self):
        self.mark()
        self.git.update({"log": "", "status": "", "rev-parse": "main", "rev-list": "0"})
        text = self_state.line()
        self.assertIn("nothing is waiting for a restart", text)
        self.assertIn("everything pushed to GitHub", text)
        self.assertIn("never say a tool you have needs a restart", text)

    def test_newer_commits_and_unpushed_work_are_named(self):
        self.mark()
        self.git.update({"log": "1111111 Add a thing\n2222222 Fix a thing", "status": "", "rev-parse": "main",
                         "rev-list": "2"})
        text = self_state.line()
        self.assertIn("2 commits made after you started (not live until a restart)", text)
        self.assertIn("2 commits not pushed", text)

    def test_mark_started_records_this_process(self):
        self.git["rev-parse"] = "feedface"
        state = self_state.mark_started()
        self.assertEqual(state["pid"], os.getpid())
        self.assertEqual(self_state.started()["commit"], "feedface")


if __name__ == "__main__":
    unittest.main()
