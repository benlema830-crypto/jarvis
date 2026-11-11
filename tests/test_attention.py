"""When Jarvis may speak up unasked: said now, or held and delivered together later."""
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import attention
import jarvis


class Isolated(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = {}
        for patch in (mock.patch.object(attention, "STORE", Path(self.temp.name) / "attention.json"),
                      mock.patch.object(attention.preferences, "read", lambda: dict(self.settings))):
            patch.start()
            self.addCleanup(patch.stop)

    def decide(self, label="Builder finished", spoke=None, idle=10, today="2026-11-10"):
        return attention.decide(label, "The report.", since_owner_spoke=spoke, input_idle=idle, today=today)


class DecideTest(Isolated):
    def test_in_conversation_it_is_always_said_and_costs_nothing(self):
        self.settings = {"interruptions": {"daily_cap": 0}}
        for _ in range(8):
            self.assertEqual(self.decide(spoke=30), "say")
        self.assertEqual(attention.snapshot()["spoken_today"], 0)

    def test_there_is_no_daily_limit_unless_the_owner_sets_one(self):
        self.assertIsNone(attention.cap())
        self.assertEqual([self.decide(f"Update {n}", spoke=3600) for n in range(12)], ["say"] * 12)
        self.assertEqual(attention.held(), [])

    def test_with_a_limit_set_updates_past_it_are_held(self):
        self.settings = {"interruptions": {"daily_cap": 5}}
        said = [self.decide(f"Update {n}", spoke=3600) for n in range(7)]
        self.assertEqual(said, ["say"] * 5 + ["hold"] * 2)
        held = attention.held()
        self.assertEqual([i["label"] for i in held], ["Update 5", "Update 6"])
        self.assertEqual(held[0]["why"], "today's limit reached")

    def test_nobody_at_the_pc_means_hold_without_spending_the_budget(self):
        self.assertEqual(self.decide(idle=1200), "hold")
        self.assertEqual(attention.held()[0]["why"], "nobody at the PC")
        self.assertEqual(attention.snapshot()["spoken_today"], 0)

    def test_budget_resets_next_day_but_held_updates_carry_over(self):
        self.settings = {"interruptions": {"daily_cap": 5}}
        for n in range(6):
            self.decide(f"Update {n}", spoke=3600)
        self.assertEqual(self.decide("Tomorrow's", spoke=3600, today="2026-11-11"), "say")
        with mock.patch.object(attention.datetime, "date") as date:
            date.today.return_value.isoformat.return_value = "2026-11-11"
            self.assertEqual([i["label"] for i in attention.held()], ["Update 5"])

    def test_owner_settings(self):
        self.settings = {"interruptions": {"daily_cap": -1}}
        self.assertEqual(self.decide(idle=99999), "say")          # -1: never hold
        self.settings = {"interruptions": {"daily_cap": 0}}
        self.assertEqual(self.decide(spoke=3600), "hold")         # 0: hold everything unprompted
        self.settings = {"interruptions": {"daily_cap": "lots"}}
        self.assertEqual(attention.cap(), attention.DAILY_CAP)    # nonsense falls back to the default

    def test_take_delivers_once_and_lines_read_plainly(self):
        self.decide("Builder finished", idle=1200)
        self.decide("Daily review", idle=1200)
        items = attention.take()
        text = attention.lines(items)
        self.assertIn("2 updates held", text)
        self.assertIn("Builder finished: The report.", text)
        self.assertIn("their own claims", text)
        self.assertEqual(attention.take(), [])
        self.assertEqual(attention.lines([]), "")

    def test_tests_never_read_the_real_store(self):
        with mock.patch.object(attention, "STORE", attention.DEFAULT_STORE):
            self.assertEqual(attention.held(), [])
            self.assertEqual(attention.snapshot()["spoken_today"], 0)

    def test_tests_never_write_the_real_store(self):
        with mock.patch.object(attention, "STORE", attention.DEFAULT_STORE):
            before = attention.DEFAULT_STORE.read_bytes() if attention.DEFAULT_STORE.exists() else None
            attention._save({"day": "x", "spoken": 99, "held": []})
            after = attention.DEFAULT_STORE.read_bytes() if attention.DEFAULT_STORE.exists() else None
        self.assertEqual(before, after)


class MainLoopTest(Isolated):
    def hold(self, item, last_user=0.0, idle=10):
        brain = mock.Mock()
        with mock.patch.object(jarvis.activity, "_idle_seconds", return_value=idle), mock.patch.object(jarvis.hud, "emit") as emit:
            result = jarvis.hold_update(brain, item, SimpleNamespace(last_user=last_user))
        return result, brain, emit

    def test_a_report_with_nobody_there_is_held_noted_and_shown(self):
        item = {"label": "Builder finished", "say": "All done.", "report": True, "note": "[TASK FINISHED] x"}
        held, brain, emit = self.hold(item, idle=3600)
        self.assertTrue(held)
        emit.assert_called_with("event", text="Held for later: Builder finished")
        note, said = brain.note.call_args.args
        self.assertIn("HELD", note)
        self.assertTrue(said.startswith("(Not said aloud yet.)"))   # his record never says he told the owner
        self.assertEqual(attention.held()[0]["label"], "Builder finished")

    def test_a_report_during_a_conversation_is_spoken(self):
        held, brain, _ = self.hold({"label": "Builder finished", "say": "All done.", "report": True}, last_user=time.time() - 20)
        self.assertFalse(held)
        brain.note.assert_not_called()

    def test_reminders_questions_and_requests_are_never_held(self):
        for item in ({"label": "Reminder: trash", "prompt": "[REMINDER DUE] ...", "chime": True},
                     {"label": "Needs your OK", "say": "May I delete it?", "chime": True},
                     {"label": "Morning wake-up", "alarm": 4, "prompt": "..."},
                     {"label": "Upcoming event", "say": "Dentist in fifteen minutes.", "chime": True}):
            held, _, _ = self.hold(item, idle=99999)
            self.assertFalse(held, item["label"])
        self.assertEqual(attention.held(), [])

    def test_an_unreadable_idle_time_does_not_break_the_loop(self):
        with mock.patch.object(jarvis.activity, "_idle_seconds", side_effect=OSError()), mock.patch.object(jarvis.hud, "emit"):
            self.assertFalse(jarvis.hold_update(mock.Mock(), {"label": "x", "say": "y", "report": True},
                                                SimpleNamespace(last_user=0.0)))

    def test_welcome_back_delivers_held_updates_together_and_clears_them(self):
        self.decide("Builder finished", idle=1200)
        with mock.patch.object(jarvis.context, "upcoming_events", return_value="Nothing."), \
                mock.patch.object(jarvis.context, "weather", return_value="Clear."), \
                mock.patch.object(jarvis, "_upcoming_reminders", return_value="None."):
            text = jarvis.gather_greeting_context()
            again = jarvis.gather_greeting_context()
        self.assertIn("1 update held", text)
        self.assertIn("Builder finished", text)
        self.assertNotIn("held", again)

    def test_the_tool_reads_and_clears(self):
        import tools
        self.decide("Daily review", idle=1200)
        self.assertIn("Daily review", tools.held_updates.call({}))
        self.assertEqual(tools.held_updates.call({}), "Nothing is being held.")


if __name__ == "__main__":
    unittest.main()
