"""An agent cut off at its time limit still reports where it got to, instead of losing everything it did."""
import unittest
from unittest import mock

import away_jobs
import terminal


class CutOffTest(unittest.TestCase):
    def run_agent(self, answers, minutes=0, session="s1"):
        """Run a worker whose Claude Code gives `answers` in turn; {} is a run that was killed. `minutes` is the
        limit: 0 means every run counts as out of time."""
        worker = terminal.TerminalWorker(cwd="C:/job")
        calls, done, timers = [], [], []
        worker.on_done = done.append

        def fake(prompt, resumed):
            calls.append((prompt, resumed))
            worker.session_id = session   # the real run learns it from Claude Code's first event
            return answers[len(calls) - 1]

        class Timer:
            def __init__(self, seconds, call):
                timers.append(seconds)
                self.daemon = False

            def start(self):
                pass

            def cancel(self):
                pass
        with mock.patch.object(worker, "_claude", fake), mock.patch.object(terminal, "write_settings"), \
                mock.patch.object(terminal.hud, "emit"), mock.patch.object(terminal.task_effort, "record"), \
                mock.patch.object(terminal, "MAX_MINUTES", minutes), mock.patch.object(terminal.threading, "Timer", Timer):
            worker._run("Build the importer", None)
        return calls, done[0], timers

    def test_a_cut_off_agent_is_asked_once_for_its_report_in_the_same_conversation(self):
        calls, done, timers = self.run_agent([{}, {"result": "The loader is built; the readme isn't.\nOUTCOME: partial",
                                                   "session_id": "s1"}])
        self.assertEqual([c[1] for c in calls], [None, "s1"])        # the second run resumes the first
        self.assertEqual(calls[1][0], terminal.WRAP_UP)
        self.assertIn("Do no more of the work", terminal.WRAP_UP)
        self.assertEqual(timers, [0, terminal.WRAP_MINUTES * 60])    # a short clock of its own for the report
        self.assertEqual(done["outcome"], "partial")
        self.assertFalse(done["ok"])
        self.assertEqual(done["report"], terminal.CUT_OFF + "The loader is built; the readme isn't.")
        self.assertTrue(away_jobs.TIMED_OUT.search(done["report"]))  # an away job still sees a timeout and goes back

    def test_its_report_is_never_taken_for_an_approval_request(self):
        # Seen in a real run: the report said "APPROVAL NEEDED: none", and the owner was asked a question.
        with mock.patch.object(terminal.approvals, "ask") as ask:
            calls, done, _ = self.run_agent([{}, {"result": "APPROVAL NEEDED: none.\nStep one is done.\nOUTCOME: partial",
                                                  "session_id": "s1"}])
        ask.assert_not_called()
        self.assertEqual(len(calls), 2)
        self.assertEqual(done["outcome"], "partial")
        self.assertNotIn(terminal.MARKER, done["report"])
        self.assertIn("Step one is done.", done["report"])
        self.assertIn("Don't ask for approval", terminal.WRAP_UP)

    def test_cut_off_again_while_reporting_ends_it_as_before(self):
        calls, done, _ = self.run_agent([{}, {}])
        self.assertEqual(len(calls), 2)                               # asked once, never in a loop
        self.assertEqual((done["outcome"], done["report"]), ("failed", "The task ran out of time after 0 minutes."))

    def test_with_no_conversation_to_resume_there_is_nothing_to_ask(self):
        calls, done, _ = self.run_agent([{}], session=None)
        self.assertEqual(len(calls), 1)
        self.assertIn("ran out of time", done["report"])

    def test_a_run_that_died_before_the_limit_is_not_called_a_timeout(self):
        calls, done, _ = self.run_agent([{}], minutes=30)
        self.assertEqual(len(calls), 1)
        self.assertEqual(done["report"], "Claude Code stopped unexpectedly without a report.")

    def test_a_stop_from_the_owner_is_not_followed_by_a_report_request(self):
        worker = terminal.TerminalWorker(cwd="C:/job")
        calls, done = [], []
        worker.on_done = done.append

        def fake(prompt, resumed):
            calls.append(prompt)
            worker.session_id = "s1"
            worker._cancel.set()          # the owner said stop, which is also how the run got killed
            return {}
        with mock.patch.object(worker, "_claude", fake), mock.patch.object(terminal, "write_settings"), \
                mock.patch.object(terminal.hud, "emit"), mock.patch.object(terminal.task_effort, "record"), \
                mock.patch.object(terminal, "MAX_MINUTES", 0):
            worker._run("Build the importer", None)
        self.assertEqual(len(calls), 1)
        self.assertEqual(done[0]["outcome"], "stopped")

    def test_an_ordinary_finish_is_untouched(self):
        calls, done, timers = self.run_agent([{"result": "Built and tested.\nOUTCOME: done", "session_id": "s1"}], minutes=30)
        self.assertEqual((len(calls), timers), (1, [30 * 60]))
        self.assertEqual((done["outcome"], done["report"], done["ok"]), ("done", "Built and tested.", True))

    def test_every_agent_is_told_its_limit_and_not_to_wait_on_slow_things(self):
        for rules in (terminal.RULES, terminal.UNATTENDED_RULES, terminal.SANDBOX_RULES):
            text = rules.format(off_limits="")
            self.assertIn(f"You are stopped after {terminal.MAX_MINUTES} minutes", text)
            self.assertIn("Don't spend that time waiting on something slow", text)


if __name__ == "__main__":
    unittest.main()
