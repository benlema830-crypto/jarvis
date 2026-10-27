import io
import sys
import threading
import time
import unittest
from unittest import mock

import approvals
import reminders


class ApprovalPhrasingTest(unittest.TestCase):
    def test_natural_approvals_count_as_yes(self):
        for said in ["I approve.", "Approved.", "You have my approval.", "You may proceed.",
                     "Permission granted.", "Yes", "Go ahead"]:
            self.assertIs(approvals.classify_answer(said), True, said)

    def test_refusals_and_questions_never_count_as_yes(self):
        for said in ["I don't approve.", "You can't do that.", "I do not approve", "No, don't.", "Hold on"]:
            self.assertIs(approvals.classify_answer(said), False, said)
        for said in ["Do you approve?", "What is it?"]:
            self.assertIsNone(approvals.classify_answer(said), said)


class ReminderLoopTest(unittest.TestCase):
    def test_a_failed_save_does_not_stop_reminders(self):
        fired, calls = threading.Event(), []
        items = [{"id": "a", "message": "x", "due": 0, "timer": False, "created": 0}]
        def flaky_save(_):
            calls.append(1)
            if len(calls) == 1:
                raise PermissionError("locked")
        with mock.patch.object(reminders, "_load", side_effect=lambda: list(items)), \
             mock.patch.object(reminders, "_save", side_effect=flaky_save), \
             mock.patch("builtins.print"):
            stop = reminders.start(lambda r: fired.set())
            try:
                self.assertTrue(fired.wait(5))  # the first save failed, the next tick still delivered it
            finally:
                stop.set()
                time.sleep(1.1)  # let the thread exit before the real _load/_save come back


class OutputEncodingTest(unittest.TestCase):
    def test_reply_with_arrow_prints_through_a_cp1252_log(self):
        stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        stream.reconfigure(encoding="utf-8", errors="replace")  # what jarvis.py does at startup
        print("JARVIS: Step one → step two 🙂", file=stream, flush=True)


if __name__ == "__main__":
    unittest.main()
