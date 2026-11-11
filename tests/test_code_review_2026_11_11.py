"""Bugs found by the whole-codebase review on 2026-11-11 (docs/reviews/CODE-REVIEW-2026-11-11.md), one test each."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import agent
import agent_sessions as sessions
import attention
import cc_guard
import direct_tools
import jarvis
import memory
import terminal


class TwoWritersTest(unittest.TestCase):
    """A fresh task goes back to the project's folder. The clash check used the folder left over from the
    session's last task, so two agents could end up changing the same folder."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "project").mkdir()
        (self.root / "elsewhere").mkdir()
        for patch in (mock.patch("preferences.PATH", self.root / "preferences.json"),
                      mock.patch.object(sessions, "STORE", self.root / "sessions.json"),
                      mock.patch.object(sessions.hud, "emit"),
                      mock.patch.object(sessions, "executable", return_value="codex.exe"),
                      mock.patch("agent_models.default_choice", return_value="codex"),
                      mock.patch.dict(sessions.project_catalog.PROJECTS, {"Jarvis": self.root / "project"}),
                      mock.patch.object(sessions.threading, "Thread")):   # nothing really runs
            patch.start()
            self.addCleanup(patch.stop)
        self.manager = sessions.SessionManager()
        project = str(self.root / "project")
        self.manager.entries = {
            "builder": {"name": "Builder", "project": "Jarvis", "cwd": project, "provider": "codex", "thread_id": None,
                        "status": "ready", "task": ""},
            "tasks": {"name": "Tasks", "project": "Jarvis", "cwd": str(self.root / "elsewhere"), "provider": "codex",
                      "thread_id": "old", "status": "ready", "task": ""}}   # its last task ran in another folder
        self.manager._loaded = True

    def test_a_fresh_task_is_checked_against_the_folder_it_will_really_use(self):
        self.assertIn("started", self.manager.start("Change the project", "Builder", "work"))
        reply = self.manager.start("Also change the project", "Tasks", "work", fresh=True)
        self.assertIn("already changing files in that folder", reply)
        self.assertNotIn("tasks", self.manager.workers)

    def test_a_follow_up_still_runs_where_the_conversation_lives(self):
        self.assertIn("started", self.manager.start("Change the project", "Builder", "work"))
        self.assertIn("started", self.manager.start("Carry on over there", "Tasks", "work"))   # not fresh: stays elsewhere
        self.assertEqual(self.manager.entries["tasks"]["cwd"], str(self.root / "elsewhere"))

    def test_a_task_records_when_it_began(self):
        self.manager.start("Change the project", "Builder", "work")
        self.assertAlmostEqual(self.manager.entries["builder"]["started_at"], sessions.time.time(), delta=5)


class FailedTurnTest(unittest.TestCase):
    """respond() speaks its error. Callers that keep what was said must not keep that."""

    def test_respond_says_how_the_turn_went(self):
        brain, voice = mock.Mock(), mock.Mock()
        self.assertEqual(jarvis.respond(brain, voice, "hello", lambda s: None), "ok")
        brain.ask.side_effect = jarvis.Interrupted()
        self.assertEqual(jarvis.respond(brain, voice, "hello", lambda s: None), "interrupted")
        brain.ask.side_effect = jarvis.model_provider.ProviderError("My Claude plan's usage limit is reached.")
        said = []
        self.assertEqual(jarvis.respond(brain, voice, "hello", said.append), "failed")
        self.assertEqual(said, ["My Claude plan's usage limit is reached."])

    def test_a_failed_heartbeat_is_not_announced_as_a_finding(self):
        queued = []

        def respond(brain, voice, prompt, speak):
            speak("My Claude plan's usage limit is reached.")
            return "failed"
        with mock.patch.object(jarvis, "respond", respond), mock.patch.object(jarvis.hud.commands, "put", queued.append):
            jarvis.heartbeat_turn(mock.Mock(), mock.Mock(), {"prompt": "[HEARTBEAT] ..."})
        self.assertEqual(queued, [])

    def test_stop_during_a_sentence_is_an_interruption_not_a_sign_in_failure(self):
        brain = jarvis.Brain.__new__(jarvis.Brain)
        brain.config = {"provider": "claude_code", "model": "m"}
        brain.system, brain.messages, brain.cancel = "", [], threading.Event()
        brain._tool = None

        def cut_off(*args):
            raise jarvis.Interrupted()   # "stop" landed between a sentence arriving and being spoken
        for field, runner in (("_claude_code_brain", brain._run_claude_code), ("_codex_brain", brain._run_codex)):
            setattr(brain, field, mock.Mock(ask=cut_off))
            with self.assertRaises(jarvis.Interrupted):
                runner(lambda sentence: None)


class HeldUpdatesTest(unittest.TestCase):
    """Held updates used to be cleared when a greeting was written, not when it was said."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = mock.patch.object(attention, "STORE", Path(self.temp.name) / "attention.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        with mock.patch.object(attention, "cap", return_value=0):
            attention.decide("Builder finished", "It reports the feature is done.", input_idle=10)

    def test_a_greeting_that_failed_puts_them_back(self):
        items = attention.take()
        self.assertEqual(len(items), 1)
        self.assertEqual(attention.held(), [])
        self.assertEqual(attention.restore(), 1)
        self.assertEqual([i["label"] for i in attention.held()], ["Builder finished"])
        self.assertEqual(attention.restore(), 0)   # only once

    def test_a_greeting_that_was_said_clears_them(self):
        attention.take()
        attention.delivered()
        self.assertEqual(attention.restore(), 0)
        self.assertEqual(attention.held(), [])

    def test_the_prompt_carries_the_mark_the_main_loop_looks_for(self):
        self.assertIn(attention.MARK, attention.lines(attention.held()))


class RecentMemoryTest(unittest.TestCase):
    def test_quiet_heartbeats_do_not_fill_the_recent_conversation(self):
        with tempfile.TemporaryDirectory() as temp, \
                mock.patch.object(memory, "RECENT_PATH", str(Path(temp) / "recent.json")), \
                mock.patch.object(memory, "PATH", str(Path(temp) / "memory.json")):
            memory.record_turn("[HEARTBEAT] This is your own hourly check...", "(quiet)")
            memory.record_turn("[HEARTBEAT] This is your own hourly check...", "The build branch has new commits, sir.")
            memory.record_turn("what's the weather", "Clear and cold.")
            kept = [item["assistant"] for item in memory._recent()]
        self.assertEqual(kept, ["The build branch has new commits, sir.", "Clear and cold."])


class SecretSearchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".env").write_text("HA_TOKEN=abc123secret\n", encoding="utf-8")
        (self.root / "notes.txt").write_text("the token is in the env file\n", encoding="utf-8")

    def test_naming_the_credentials_file_itself_is_refused(self):
        with self.assertRaises(ValueError) as refused:
            direct_tools.search_text(".", str(self.root / ".env"))
        self.assertIn("credentials file", str(refused.exception))

    def test_matches_inside_credentials_files_are_dropped_whichever_searcher_runs(self):
        found = [f"{self.root / '.env.local'}:1: HA_TOKEN=abc123secret", f"{self.root / 'key.pem'}:2: token",
                 f"{self.root / 'notes.txt'}:1: the token is in the env file"]
        fake = mock.Mock(stdout="\n".join(found))
        with mock.patch.object(direct_tools.shutil, "which", return_value="rg.exe"), \
                mock.patch.object(direct_tools.subprocess, "run", return_value=fake):
            result = direct_tools.search_text("token", str(self.root))
        self.assertIn("notes.txt", result)
        self.assertNotIn("abc123secret", result)
        self.assertNotIn("key.pem", result)

    def test_one_rule_for_what_counts_as_a_credentials_file(self):
        self.assertIs(direct_tools.SECRET_FILE, cc_guard.SECRET_FILE)


class ScreenAgentScriptTest(unittest.TestCase):
    def run_script(self, script):
        worker = agent.Agent.__new__(agent.Agent)
        worker.log = []
        done = mock.Mock(stdout="ok", stderr="", returncode=0)
        with mock.patch.object(agent.hud, "emit"), mock.patch.object(agent.subprocess, "run", return_value=done) as run:
            text = worker._powershell(script, "look at a folder")[0]["text"]
        return text, run

    def test_a_read_only_script_cannot_read_off_limits_work_data(self):
        text, run = self.run_script(r"Get-ChildItem 'C:\Users\x\AppData\Roaming\Microsoft\Teams'")
        self.assertIn("BLOCKED", text)
        run.assert_not_called()

    def test_an_ordinary_read_still_runs_without_asking_and_without_jarviss_tokens(self):
        with mock.patch.dict(agent.os.environ, {"HA_TOKEN": "secret", "SAFE_VALUE": "1"}):
            text, run = self.run_script("Get-ChildItem HKLM:\\Software | Select-Object -First 3")
        self.assertIn("Exit code 0", text)
        env = run.call_args.kwargs["env"]
        self.assertNotIn("HA_TOKEN", env)
        self.assertIn("SAFE_VALUE", env)


class AgentBillingGuardTest(unittest.TestCase):
    """An agent run ends before its first request if Claude Code would bill an API key instead of the plan."""

    def run_claude(self, source, env_extra=None):
        worker = terminal.TerminalWorker()
        worker.env_extra = env_extra or {}
        lines = ['{"type": "system", "subtype": "init", "session_id": "s1", "apiKeySource": "%s"}\n' % source,
                 '{"type": "result", "session_id": "s1", "result": "Did it.\\nOUTCOME: done", "is_error": false}\n']
        process = mock.Mock(stdout=iter(lines), pid=1)
        process.poll.return_value = None
        with mock.patch.object(terminal, "_claude_exe", return_value="claude.exe"), \
                mock.patch.object(terminal.subprocess, "Popen", return_value=process), \
                mock.patch.object(terminal.subprocess, "run") as kill, \
                mock.patch.object(terminal.hud, "emit"):
            return worker._claude("Do the thing", None), kill

    def test_on_the_plan_it_runs(self):
        result, kill = self.run_claude("none")
        self.assertFalse(result.get("is_error"))
        kill.assert_not_called()

    def test_with_an_api_key_in_play_it_is_stopped_and_says_why(self):
        result, kill = self.run_claude("ANTHROPIC_API_KEY")
        self.assertTrue(result["is_error"])
        self.assertIn("won't spend API credits", result["result"])
        self.assertIn("taskkill", kill.call_args.args[0])

    def test_the_local_model_is_not_mistaken_for_a_paid_key(self):
        result, kill = self.run_claude("ANTHROPIC_AUTH_TOKEN", env_extra={"ANTHROPIC_BASE_URL": "http://127.0.0.1:11435"})
        self.assertFalse(result.get("is_error"))


if __name__ == "__main__":
    unittest.main()
