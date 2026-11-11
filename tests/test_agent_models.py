"""Jarvis chooses the model for each agent job: Claude Opus 5.5 by default, others when the job calls for it."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agent_models
import agent_sessions as sessions
import terminal


class ResolveTest(unittest.TestCase):
    def setUp(self):
        self.settings = {}
        patcher = mock.patch.object(agent_models.preferences, "read", lambda: dict(self.settings))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_blank_means_claude_opus_on_the_plan(self):
        plan = agent_models.resolve()
        self.assertEqual((plan["choice"], plan["provider"], plan["model"], plan["effort"], plan["env"]),
                         ("opus", "claude", "claude-opus-5-5", "", {}))
        self.assertEqual(agent_models.spoken(plan), "Claude Opus 5.5")

    def test_each_choice_and_effort(self):
        self.assertEqual(agent_models.resolve("sonnet", "low")["model"], "claude-sonnet-5-5")
        self.assertEqual(agent_models.resolve("haiku")["model"], "claude-haiku-5-5")
        codex = agent_models.resolve("codex", "high")
        self.assertEqual((codex["provider"], codex["model"], codex["effort"]), ("codex", "", "high"))
        self.assertEqual(agent_models.spoken(codex), "Codex, high effort")

    def test_what_people_say_is_understood(self):
        for said, choice in (("Claude", "opus"), ("Opus 5.5", "opus"), ("claude-sonnet-5-5", "sonnet"),
                             ("ChatGPT", "codex"), ("GPT", "codex"), ("auto", "opus"), ("default", "opus")):
            self.assertEqual(agent_models.resolve(said)["choice"], choice, said)
        self.assertEqual(agent_models.resolve("opus", "normal")["effort"], "")

    def test_unknown_models_and_efforts_are_refused_with_the_choices(self):
        with self.assertRaisesRegex(ValueError, "opus, sonnet, haiku, codex, local"):
            agent_models.resolve("gemini")
        with self.assertRaisesRegex(ValueError, "low, medium or high"):
            agent_models.resolve("opus", "maximum")

    def test_the_owner_can_change_the_default(self):
        self.settings = {"agent_model": "codex"}
        self.assertEqual(agent_models.resolve()["choice"], "codex")
        self.settings = {"agent_model": "something else"}
        self.assertEqual(agent_models.resolve()["choice"], "opus")

    def test_local_runs_claude_code_against_this_pc_only(self):
        with mock.patch.object(agent_models, "local_ready", return_value=""):
            plan = agent_models.resolve("local", "high")
        self.assertEqual((plan["provider"], plan["model"], plan["effort"]), ("claude", agent_models.LOCAL_AGENT, ""))
        self.assertEqual(plan["env"]["ANTHROPIC_BASE_URL"], "http://127.0.0.1:11435")
        self.assertEqual(plan["env"]["ANTHROPIC_API_KEY"], "")   # never a real key, never the internet

    def test_local_that_is_not_ready_says_why_instead_of_falling_back(self):
        with mock.patch.object(agent_models, "_local", side_effect=OSError()):
            with self.assertRaisesRegex(ValueError, "isn't running"):
                agent_models.resolve("local")
        with mock.patch.object(agent_models, "_local", return_value={"models": [{"name": "other:latest"}]}):
            with self.assertRaisesRegex(ValueError, "isn't installed"):
                agent_models.resolve("local")

    def test_local_copy_with_room_for_instructions_is_made_once_from_the_weights_on_disk(self):
        calls = []

        def api(path, payload=None, timeout=5):
            calls.append((path, payload))
            return {"models": [{"name": agent_models.LOCAL_BASE}]} if path == "/api/tags" else {"status": "success"}
        with mock.patch.object(agent_models, "_local", api):
            self.assertEqual(agent_models.local_ready(), "")
        self.assertEqual(calls[1][0], "/api/create")
        self.assertEqual(calls[1][1]["from"], agent_models.LOCAL_BASE)
        self.assertEqual(calls[1][1]["parameters"], {"num_ctx": 32768})
        with mock.patch.object(agent_models, "_local", return_value={"models": [{"name": agent_models.LOCAL_AGENT + ":latest"}]}) as api:
            self.assertEqual(agent_models.local_ready(), "")
            api.assert_called_once()   # already there: nothing is created again


class DispatchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = {}
        self.ran = []
        test = self

        def run(worker, task, session):  # stands in for a real Claude Code run
            test.ran.append({"model": worker.model, "effort": worker.fixed_effort, "env": dict(worker.env_extra),
                             "resume": session, "research": worker.research})
            worker.session_id = session or "claude-session"
            worker.on_done({"ok": True, "report": "Done."})
        for patch in (mock.patch("preferences.PATH", self.root / "preferences.json"),
                      mock.patch.object(agent_models.preferences, "read", lambda: dict(self.settings)),
                      mock.patch.object(sessions, "STORE", self.root / "sessions.json"),
                      mock.patch.object(sessions.working_memory, "SESSIONS", self.root / "sessions.json"),
                      mock.patch.object(sessions.working_memory, "PROJECT_LOG", self.root / "project_log.jsonl"),
                      mock.patch.object(sessions.working_memory, "HANDOFFS", self.root / "handoffs"),
                      mock.patch.object(sessions.working_memory, "journal", return_value=([], [])),
                      mock.patch.object(sessions.working_memory.knowledge, "VAULT", self.root / "vault"),
                      mock.patch.object(sessions, "PROJECT", self.root),
                      mock.patch.object(sessions, "executable", return_value="codex.exe"),
                      mock.patch.object(terminal, "_claude_exe", return_value="claude.exe"),
                      mock.patch.object(terminal.TerminalWorker, "_run", run),
                      mock.patch.object(sessions.hud, "emit")):
            patch.start()
            self.addCleanup(patch.stop)
        self.manager = sessions.SessionManager()

    def go(self, task="Find our next move", **options):
        reply = self.manager.start(task, **options)
        if self.manager.thread:
            self.manager.thread.join(3)
        return reply

    def test_an_agent_job_runs_on_opus_unless_told_otherwise(self):
        self.manager.open()
        reply = self.go()
        self.assertIn("Frontier started on Claude Opus 5.5.", reply)
        self.assertEqual(self.ran, [{"model": "claude-opus-5-5", "effort": "", "env": {}, "resume": None, "research": True}])
        entry = self.manager.entries["frontier"]
        self.assertEqual((entry["provider"], entry["model_choice"], entry["thread_id"], entry["report"]),
                         ("claude", "opus", "claude-session", "Done."))

    def test_jarvis_can_pick_a_lighter_model_and_an_effort(self):
        self.manager.open()
        reply = self.go("Rename one variable", mode="work", model="sonnet", effort="low")
        self.assertIn("Claude Sonnet 5.5, low effort", reply)
        self.assertEqual((self.ran[0]["model"], self.ran[0]["effort"], self.ran[0]["research"]), ("claude-sonnet-5-5", "low", False))

    def test_claude_models_share_one_conversation(self):
        self.manager.open()
        self.go()
        self.go("And the one after that", model="haiku")
        self.assertEqual(self.ran[1]["resume"], "claude-session")
        self.assertEqual(self.ran[1]["model"], "claude-haiku-5-5")

    def test_local_gets_its_own_conversation_and_address(self):
        self.manager.open()
        self.go()
        with mock.patch.object(agent_models, "local_ready", return_value=""):
            reply = self.go("Tidy a note", model="local")
        self.assertIn("the local model", reply)
        self.assertIn("new conversation", reply)
        self.assertIsNone(self.ran[1]["resume"])
        self.assertEqual(self.ran[1]["env"]["ANTHROPIC_BASE_URL"], "http://127.0.0.1:11435")

    def test_the_local_model_is_unloaded_when_its_job_ends_and_only_then(self):
        self.manager.open()
        with mock.patch.object(agent_models, "release_local") as release:
            self.go()
            release.assert_not_called()          # a Claude job never touches the local service
            with mock.patch.object(agent_models, "local_ready", return_value=""):
                self.go("Tidy a note", model="local")
            release.assert_called_once()

    def test_a_bad_choice_starts_nothing(self):
        self.manager.open()
        self.assertIn("Unknown agent model", self.go(model="gemini"))
        with mock.patch.object(agent_models, "local_ready", return_value="the local model service isn't running"):
            self.assertIn("can't be used right now", self.go(model="local"))
        self.assertEqual(self.ran, [])
        self.assertFalse(self.manager.running)

    def test_away_work_stays_in_codex_whatever_is_asked(self):
        folder = self.root / "copy"
        folder.mkdir()
        self.assertEqual(self.manager.prepare_unattended("Away Builder", "Widget", folder), "")
        started = []
        with mock.patch.object(sessions.Worker, "_run", lambda worker, task, mode: started.append(worker.entries[worker.active]["provider"])):
            self.go("Build it", name="Away Builder", mode="work", fresh=True, folder=str(folder), model="opus")
        self.assertEqual(started, ["codex"])
        self.assertEqual(self.ran, [])

    def test_the_tools_let_jarvis_choose(self):
        import tools
        for name in ("send_agent_task", "terminal_task"):
            schema = tools.TOOLS_BY_NAME[name].to_dict()["input_schema"]["properties"]
            self.assertIn("model", schema, name)
            self.assertIn("effort", schema, name)
            self.assertIn("Opus 5.5", schema["model"]["description"])
            self.assertIn("local", schema["model"]["description"])


class RunnerTest(unittest.TestCase):
    def test_the_model_effort_and_address_reach_claude_code(self):
        worker = terminal.TerminalWorker(cwd=tempfile.gettempdir())
        worker.model, worker.effort, worker.env_extra = "qwen3.5-agent", "", {"ANTHROPIC_BASE_URL": "http://127.0.0.1:11435"}
        proc = mock.Mock()
        proc.stdout = iter([json.dumps({"type": "result", "result": "Done", "session_id": "sid"})])
        with mock.patch.object(terminal, "_claude_exe", return_value="claude.exe"), \
                mock.patch.object(terminal.subprocess, "Popen", return_value=proc) as popen:
            worker._claude("task", None)
        args, env = popen.call_args.args[0], popen.call_args.kwargs["env"]
        self.assertEqual(args[args.index("--model") + 1], "qwen3.5-agent")
        self.assertNotIn("--effort", args)
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "http://127.0.0.1:11435")

    def test_a_test_can_never_start_the_real_claude_code(self):
        self.assertIsNone(terminal._claude_exe())
        self.assertEqual(terminal.TerminalWorker().start("made-up task"), "Claude Code isn't installed on this PC.")


if __name__ == "__main__":
    unittest.main()
