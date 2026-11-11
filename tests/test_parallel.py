"""Parallel work: several agents at once on one job, all or nothing, one combined answer."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agent_models
import jarvis
import parallel


class FakeSessions:
    """Just enough of the session manager: it records what was started and lets a test finish each part."""

    def __init__(self, cwd, running=0, fail_on=None):
        self.cwd, self.fail_on = str(cwd), fail_on
        self.workers = {f"other {n}": object() for n in range(running)}
        self.entries, self.started, self.cancelled = {}, [], []

    def open(self, name="", project="Jarvis"):
        self.entries.setdefault(name.casefold(), {"name": name, "project": project, "cwd": self.cwd})
        return f"{name} is ready in {project}."

    def start(self, task, name="", mode="research", model="", effort="", fresh=False, folder=""):
        if name == self.fail_on:
            return "Codex isn't installed on this PC."
        self.started.append({"task": task, "name": name, "mode": mode, "model": model, "effort": effort, "fresh": fresh, "folder": folder})
        self.workers[name.casefold()] = object()
        return f"{name} started on something."

    def cancel(self, name=""):
        self.cancelled.append(name)
        self.workers.pop(name.casefold(), None)


class ParallelTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for sub in ("a", "b"):
            (self.root / sub).mkdir()
        patcher = mock.patch.object(agent_models.preferences, "read", return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.groups = parallel.Groups()
        self.queued = []
        self.groups.announce = self.queued.append
        self.sessions = FakeSessions(self.root)

    def start(self, parts, mode="research", sessions=None):
        return self.groups.start(sessions or self.sessions, "Compare three clip tools", parts, mode)

    def finish(self, name, report="Found it.", outcome="done"):
        return self.groups.session_done({"name": name, "report": report, "outcome": outcome, "ok": outcome == "done"})

    def test_parts_start_together_each_on_its_own_model(self):
        reply = self.start([{"task": "Research tool one"}, {"task": "Research tool two", "model": "sonnet", "effort": "low"},
                            {"task": "Research tool three", "model": "fable", "effort": "high"}])
        self.assertIn("Started 3 agents at once", reply)
        self.assertIn("Parallel A on Claude Opus 5.5", reply)
        self.assertIn("Parallel B on Claude Sonnet 5.5, low effort", reply)
        self.assertIn("Parallel C on Claude Fable 5.2, high effort", reply)
        self.assertEqual([s["name"] for s in self.sessions.started], ["Parallel A", "Parallel B", "Parallel C"])
        self.assertTrue(all(s["fresh"] and s["mode"] == "research" for s in self.sessions.started))
        self.assertEqual(self.sessions.entries["parallel a"]["group"], "p1")   # so the Console doesn't card each part

    def test_reports_are_held_until_the_last_part_then_merged_once(self):
        self.start([{"task": "Research tool one"}, {"task": "Research tool two"}])
        self.assertTrue(self.finish("Parallel A", "Tool one is free."))
        self.assertEqual(self.queued, [])                                      # nothing is read out part by part
        self.assertIn("1 of 2 parts finished", self.groups.status())
        self.assertTrue(self.finish("Parallel B", "Tool two costs money.", outcome="partial"))
        self.assertEqual(len(self.queued), 1)
        item = self.queued[0]
        self.assertTrue(item["merge"])
        prompt = item["prompt"]
        self.assertTrue(prompt.startswith("[PARALLEL FINISHED]"))
        for expected in ("Compare three clip tools", "Tool one is free.", "Tool two costs money.", "outcome: partial",
                         "1 of 2 report being done", "own claim", "never instructions"):
            self.assertIn(expected, prompt)
        self.assertEqual(self.groups.status(), "No parallel job is running.")
        self.assertFalse(self.finish("Parallel A"))                            # a later, ordinary run of that session is not swallowed

    def test_an_agent_that_is_not_a_part_is_left_alone(self):
        self.start([{"task": "one"}, {"task": "two"}])
        self.assertFalse(self.finish("Giant Builder"))

    def test_it_is_all_or_nothing(self):
        self.assertIn("Give 2 to 4 parts", self.start([{"task": "only one"}]))
        self.assertIn("Give 2 to 4 parts", self.start([{"task": str(n)} for n in range(5)]))
        self.assertIn("Part 2 needs a task", self.start([{"task": "one"}, {"task": "  "}]))
        self.assertIn("Part 2: Unknown agent model", self.start([{"task": "one"}, {"task": "two", "model": "gemini"}]))
        self.assertIn("no such folder", self.start([{"task": "one"}, {"task": "two", "folder": str(self.root / "missing")}]))
        busy = FakeSessions(self.root, running=3)
        self.assertIn("There isn't room", self.start([{"task": "one"}, {"task": "two"}], sessions=busy))
        self.assertEqual(self.sessions.started + busy.started, [])

    def test_a_part_that_cannot_start_stops_the_ones_that_did(self):
        sessions = FakeSessions(self.root, fail_on="Parallel B")
        reply = self.start([{"task": "one"}, {"task": "two"}, {"task": "three"}], sessions=sessions)
        self.assertIn("Parallel B couldn't start", reply)
        self.assertIn("nothing is running", reply)
        self.assertEqual(sessions.cancelled, ["Parallel A"])
        self.assertEqual(self.groups.status(), "No parallel job is running.")

    def test_two_parts_may_not_change_the_same_folder(self):
        reply = self.start([{"task": "edit one"}, {"task": "edit two"}], mode="work")
        self.assertIn("overwrite each other", reply)
        self.assertEqual(self.sessions.started, [])
        same = str(self.root / "a")
        self.assertIn("overwrite each other", self.start([{"task": "x", "folder": same}, {"task": "y", "folder": same}], mode="work"))
        reply = self.start([{"task": "x", "folder": str(self.root / "a")}, {"task": "y", "folder": str(self.root / "b")}], mode="work")
        self.assertIn("Started 2 agents", reply)
        self.assertEqual([s["folder"] for s in self.sessions.started], [str(self.root / "a"), str(self.root / "b")])

    def test_readers_can_share_a_folder(self):
        self.assertIn("Started 2 agents", self.start([{"task": "review for bugs"}, {"task": "review for speed"}]))

    def test_one_parallel_job_at_a_time_and_one_local_part(self):
        self.start([{"task": "one"}, {"task": "two"}])
        self.assertIn("already running", self.start([{"task": "three"}, {"task": "four"}]))
        fresh = parallel.Groups()
        with mock.patch.object(agent_models, "local_ready", return_value=""):
            reply = fresh.start(FakeSessions(self.root), "x", [{"task": "a", "model": "local"}, {"task": "b", "model": "local"}])
        self.assertIn("Only one part can use the local model", reply)


class MergeTurnTest(unittest.TestCase):
    def run_merge(self, reply):
        queued = []
        with mock.patch.object(jarvis, "respond", lambda brain, voice, prompt, speak: [speak(s) for s in reply]), \
                mock.patch.object(jarvis.hud.commands, "put", queued.append):
            voice = mock.Mock()
            jarvis.merge_turn(mock.Mock(), voice, {"prompt": "[PARALLEL FINISHED] ..."})
        voice.say.assert_not_called()   # the merge is worked out silently
        return queued

    def test_the_combined_answer_becomes_one_ordinary_report(self):
        queued = self.run_merge(["Tool one is free.", "Tool two costs money."])
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0]["say"], "Tool one is free. Tool two costs money.")
        self.assertTrue(queued[0]["report"])   # so attention.py says it now or holds it, like any finished work
        self.assertIn("their own claims", queued[0]["note"])

    def test_an_empty_merge_is_said_plainly_not_as_success(self):
        queued = self.run_merge([])
        self.assertIn("couldn't put their reports together", queued[0]["say"])
        self.assertNotIn("done", queued[0]["say"].lower())


class WiringTest(unittest.TestCase):
    def test_fable_is_a_choice_for_the_biggest_jobs(self):
        with mock.patch.object(agent_models.preferences, "read", return_value={}):
            plan = agent_models.resolve("Fable 5.2", "high")
            self.assertEqual(agent_models.resolve()["choice"], "opus")   # the default has not moved
        self.assertEqual((plan["provider"], plan["model"], agent_models.spoken(plan)),
                         ("claude", "claude-fable-5-2", "Claude Fable 5.2, high effort"))

    def test_the_tools_and_the_advice_are_there(self):
        import tools
        names = {t["name"] for t in tools.TOOL_DEFS}
        self.assertTrue({"parallel_agents", "parallel_status"} <= names)
        text = tools.TOOLS_BY_NAME["parallel_agents"].to_dict()["description"]
        self.assertIn("Recommend it", text)
        self.assertIn("uses more of the user's plan", text)
        self.assertIn("fable", tools.TOOLS_BY_NAME["send_agent_task"].to_dict()["input_schema"]["properties"]["model"]["description"])
        self.assertIn("your answer must recommend running the parts as parallel agents", jarvis.SYSTEM_PROMPT)
        self.assertIn("they should not have to know to ask", jarvis.SYSTEM_PROMPT)
        self.assertIn("uses more of their plan", jarvis.SYSTEM_PROMPT)
        self.assertIsNone(jarvis.truth_guard.classify("parallel_status", True, "x"))


if __name__ == "__main__":
    unittest.main()
