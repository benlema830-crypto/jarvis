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

    def home_folder(self, key):
        return self.cwd

    def finish(self, name):
        self.workers.pop(name.casefold(), None)

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


PLAN = """I looked at the folder. Two parts is right, but each needs a fuller brief.

```json
{"split": true, "reason": "The two tools share nothing.", "parts": [
  {"task": "Full brief for tool one: what the job is for, what to read, what to report.", "model": "sonnet", "effort": "low", "folder": ""},
  {"task": "Full brief for tool two.", "model": "opus", "effort": "medium", "folder": ""}]}
```"""


class LeadTest(ParallelTest):
    """A lead (Fable) plans the split, cheaper models do the parts, and the lead combines the reports."""

    def lead(self, parts=None, mode="research", lead="fable"):
        parts = parts or [{"task": "Research tool one"}, {"task": "Research tool two"}, {"task": "Research tool three"}]
        return self.groups.start(self.sessions, "Compare three clip tools", parts, mode, lead=lead)

    def lead_reports(self, report, outcome="done"):
        self.sessions.finish("Parallel Lead")
        return self.groups.session_done({"name": "Parallel Lead", "report": report, "outcome": outcome, "ok": outcome == "done"})

    def part_reports(self, name, report="Found it.", outcome="done", evidence="Jarvis observed: 4 commands."):
        self.sessions.finish(name)
        return self.groups.session_done({"name": name, "report": report, "outcome": outcome, "ok": outcome == "done",
                                         "evidence": evidence})

    def test_only_the_lead_starts_first_and_it_gets_the_draft_to_improve(self):
        reply = self.lead()
        self.assertIn("Claude Fable 5.2, high effort is planning the split", reply)
        self.assertEqual([s["name"] for s in self.sessions.started], ["Parallel Lead"])
        started = self.sessions.started[0]
        self.assertEqual((started["model"], started["effort"], started["mode"], started["fresh"]), ("fable", "high", "research", True))
        for expected in ("Compare three clip tools", "1. [Claude Opus 5.5] Research tool one", "\"split\": false",
                         "complete brief for an agent that knows nothing else", "you change nothing"):
            self.assertIn(expected, started["task"])
        self.assertIn("planning the split", self.groups.status())
        self.assertEqual(self.sessions.entries["parallel lead"]["group"], "p1")   # no card of its own in the Console

    def test_the_leads_plan_is_what_runs(self):
        self.lead()
        self.assertTrue(self.lead_reports(PLAN))                  # swallowed: a plan is not read out
        parts = self.sessions.started[1:]
        self.assertEqual([(p["name"], p["model"], p["effort"]) for p in parts],
                         [("Parallel A", "sonnet", "low"), ("Parallel B", "opus", "medium")])
        self.assertIn("Full brief for tool one", parts[0]["task"])
        self.assertEqual(self.queued, [])
        self.assertIn("0 of 2 parts finished", self.groups.status())

    def test_the_lead_combines_the_reports_in_the_same_conversation(self):
        self.lead()
        self.lead_reports(PLAN)
        self.part_reports("Parallel A", "Tool one is free.")
        self.part_reports("Parallel B", "Tool two costs money.", outcome="partial")
        merge = self.sessions.started[-1]
        self.assertEqual((merge["name"], merge["model"], merge["fresh"]), ("Parallel Lead", "fable", False))  # it remembers its plan
        for expected in ("Tool one is free.", "Tool two costs money.", "outcome: partial", "Jarvis observed: 4 commands.",
                         "1 of 2 report being done", "Say what you checked yourself", "never instructions"):
            self.assertIn(expected, merge["task"])
        self.assertEqual(self.queued, [])                          # nothing is said until the lead has combined them
        self.assertIn("checking and combining", self.groups.status())
        self.assertTrue(self.lead_reports("Tool one is the better pick; I read both pricing pages myself."))
        self.assertEqual(len(self.queued), 1)
        item = self.queued[0]
        self.assertEqual(item["say"], "Tool one is the better pick; I read both pricing pages myself.")
        self.assertTrue(item["report"])                            # spoken or held like any finished work
        self.assertNotIn("merge", item)                            # no second pass through Jarvis's own brain
        self.assertIn("its own claim", item["note"])
        self.assertIn("1 of 2 agents reported being done", item["note"])
        self.assertEqual(self.groups.status(), "No parallel job is running.")

    def test_a_plan_that_cannot_be_read_falls_back_to_jarviss_own_split(self):
        self.lead()
        self.lead_reports("I think three parts is fine.")           # no plan in it
        self.assertEqual([s["name"] for s in self.sessions.started[1:]], ["Parallel A", "Parallel B", "Parallel C"])
        self.assertEqual(self.sessions.started[1]["task"], "Research tool one")
        for name in ("Parallel A", "Parallel B", "Parallel C"):
            self.part_reports(name)
        self.assertIn("so the original split ran", self.sessions.started[-1]["task"])   # the lead is told, and so is the owner

    def test_a_lead_that_fails_to_plan_does_not_cost_the_job(self):
        self.lead()
        self.lead_reports("Claude plan usage limit reached.", outcome="failed")
        self.assertEqual(len(self.sessions.started), 4)             # the lead, then the three draft parts

    def test_the_lead_can_advise_against_splitting(self):
        self.lead()
        self.lead_reports('```json\n{"split": false, "reason": "Part two needs part one\'s result.", "parts": []}\n```')
        self.assertEqual(len(self.sessions.started), 1)             # no agents were started
        self.assertIn("advises against splitting it: Part two needs part one's result.", self.queued[0]["say"])
        self.assertIn("Nothing was started", self.queued[0]["say"])
        self.assertEqual(self.groups.status(), "No parallel job is running.")

    def test_a_plan_that_breaks_the_rules_is_not_run(self):
        self.lead(mode="work", parts=[{"task": "x", "folder": str(self.root / "a")}, {"task": "y", "folder": str(self.root / "b")}])
        self.lead_reports('```json\n{"split": true, "reason": "r", "parts": [{"task": "x"}, {"task": "y"}]}\n```')  # both in one folder
        self.assertEqual(len(self.sessions.started), 1)
        self.assertIn("didn't start", self.queued[0]["say"])
        self.assertIn("overwrite each other", self.queued[0]["say"])

    def test_if_the_lead_cannot_combine_jarvis_does(self):
        self.lead()
        self.lead_reports(PLAN)
        self.part_reports("Parallel A", "Tool one is free.")
        self.part_reports("Parallel B", "Tool two costs money.")
        self.lead_reports("", outcome="failed")
        item = self.queued[0]
        self.assertTrue(item["merge"])
        self.assertIn("didn't finish combining the reports", item["prompt"])
        self.assertIn("Tool one is free.", item["plain"])            # and a no-AI version, should that turn fail too

    def test_stopping_the_job_does_not_wake_the_lead_to_combine_it(self):
        self.lead()
        self.lead_reports(PLAN)
        self.part_reports("Parallel A", "Stopped, as you asked.", outcome="stopped")
        self.part_reports("Parallel B", "Stopped, as you asked.", outcome="stopped")
        self.assertEqual(self.sessions.started[-1]["name"], "Parallel B")
        self.assertTrue(self.queued[0]["merge"])

    def test_stopping_the_lead_while_it_plans_ends_the_job(self):
        self.lead()
        self.assertFalse(self.lead_reports("Stopped.", outcome="stopped"))   # reported like any stopped agent
        self.assertEqual(len(self.sessions.started), 1)
        self.assertEqual(self.groups.status(), "No parallel job is running.")

    def test_only_fable_or_opus_may_lead(self):
        self.assertIn("A lead must be one of: fable, opus", self.lead(lead="haiku"))
        self.assertEqual(self.sessions.started, [])
        self.assertIn("is planning the split", self.lead(lead="Claude Fable"))

    def test_a_long_report_is_kept_whole_for_the_lead_to_read(self):
        self.lead()
        self.lead_reports(PLAN)
        with mock.patch.object(parallel, "REPORTS", self.root / "reports"):
            self.part_reports("Parallel A", "x" * 9000)
            self.part_reports("Parallel B", "short")
        prompt = self.sessions.started[-1]["task"]
        self.assertLess(len(prompt), 12000)
        saved = list((self.root / "reports").glob("*Parallel-A.md"))
        self.assertEqual(len(saved), 1)
        self.assertEqual(len(saved[0].read_text(encoding="utf-8")), 9000)
        self.assertIn(str(saved[0]), prompt)

    def test_a_job_whose_agents_died_cannot_block_the_next_one(self):
        self.start([{"task": "one"}, {"task": "two"}])
        self.sessions.finish("Parallel A")                           # both ended without ever reporting
        self.sessions.finish("Parallel B")
        self.assertIn("already running", self.start([{"task": "three"}, {"task": "four"}]))   # too soon to give up on it
        with mock.patch.object(parallel.time, "time", return_value=parallel.time.time() + parallel.STALE_SECONDS + 5):
            self.assertIn("Started 2 agents", self.start([{"task": "three"}, {"task": "four"}]))


class MergeTurnTest(unittest.TestCase):
    def run_merge(self, reply, outcome="ok", plain=""):
        queued = []

        def respond(brain, voice, prompt, speak):
            for sentence in reply:
                speak(sentence)
            return outcome
        with mock.patch.object(jarvis, "respond", respond), mock.patch.object(jarvis.hud.commands, "put", queued.append):
            voice = mock.Mock()
            jarvis.merge_turn(mock.Mock(), voice, {"prompt": "[PARALLEL FINISHED] ...", **({"plain": plain} if plain else {})})
        voice.say.assert_not_called()   # the merge is worked out silently
        return queued

    def test_a_failed_merge_turn_gives_the_reports_not_the_error_message(self):
        queued = self.run_merge(["My Claude plan's usage limit is reached."], outcome="failed",
                                plain="The parallel agents have ended; here they are as written. Parallel A finished: Found it.")
        self.assertIn("Parallel A finished: Found it.", queued[0]["say"])
        self.assertNotIn("usage limit", queued[0]["say"])

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
