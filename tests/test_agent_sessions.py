import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agent_sessions as sessions
import cc_guard
import terminal


class FakeConnection:
    calls = []
    status = "completed"
    def __init__(self, cwd, callback, cancel=None, isolate_mcp=False):
        FakeConnection.isolated = isolate_mcp
        self.callback = callback
        self.events = iter([
            {"method": "item/completed", "params": {"item": {"id": "answer", "type": "agentMessage", "phase": "final_answer", "text": "I recommend fixing the save flow next."}}},
            {"method": "turn/completed", "params": {"turn": {"id": "turn-1", "status": self.status}}},
        ])
    def call(self, method, params):
        self.calls.append((method, params))
        if method.startswith("thread/"):
            return {"thread": {"id": "persisted-thread"}}
        if method == "turn/start":
            self.callback({"method": "turn/started", "params": {"turn": {"id": "turn-1"}}})
        return {}
    def send(self, payload): pass
    def request(self, method, params): self.calls.append((method, params))
    def receive(self): return next(self.events)
    def close(self): pass


class SessionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patcher = mock.patch('preferences.PATH', self.root / 'preferences.json')
        patcher.start()
        self.addCleanup(patcher.stop)
        for patch in (mock.patch.object(sessions, "STORE", self.root / "sessions.json"),
                      mock.patch.object(sessions, "PROJECT", self.root),
                      mock.patch.object(sessions, "executable", return_value="codex.exe"),
                      mock.patch.object(sessions.hud, "emit")):
            patch.start()
            self.addCleanup(patch.stop)
        self.manager = sessions.SessionManager()
        FakeConnection.calls = []
        FakeConnection.status = "completed"

    def test_open_is_preparation_not_execution(self):
        with mock.patch.object(sessions, "Connection") as conn:
            self.assertIn("ready", self.manager.open())
            self.assertFalse(self.manager.running)
            conn.assert_not_called()
        self.assertEqual(sessions.SessionManager().snapshot()["selected"], "frontier")

    def test_names_are_reused_case_insensitively_and_unknown_projects_rejected(self):
        self.manager.open("Frontier")
        self.manager.open("FRONTIER")
        self.assertEqual(len(self.manager.snapshot()["sessions"]), 1)
        self.assertIn("Configured projects", self.manager.open("Other", "unknown"))

    def test_jarvis_project_is_prepared_without_starting_or_retargeting(self):
        with mock.patch.object(sessions, "Connection") as conn:
            self.assertIn("ready in Jarvis", self.manager.open(project="Jarvis"))
            conn.assert_not_called()
        entry = self.manager.entries['jarvis builder']
        self.assertEqual(entry['cwd'], str(sessions.HERE))
        self.assertEqual(entry['project'], 'Jarvis')
        self.assertFalse(self.manager.running)
        self.assertIn('different project', self.manager.open('Jarvis Builder', 'Rocket Frontier'))
        self.assertEqual(entry['cwd'], str(sessions.HERE))

    def test_turn_completion_and_restart_resume(self):
        self.manager.open()
        done = self.manager.on_done = mock.Mock()
        with mock.patch.object(sessions, "Connection", FakeConnection):
            self.manager.start("Find next task")
            self.manager.thread.join(3)
            self.assertFalse(self.manager.running)
            self.assertTrue(done.call_args.args[0]["ok"])
            self.assertTrue(FakeConnection.isolated)  # research mode: no native MCP tools
            restored = sessions.SessionManager()
            restored.start("Implement it", mode="work")
            restored.thread.join(3)
            self.assertFalse(FakeConnection.isolated)  # work mode keeps the user's Codex tools
        methods = [m for m, _ in FakeConnection.calls]
        self.assertIn("thread/start", methods)
        self.assertIn("thread/resume", methods)
        turns = [p for m, p in FakeConnection.calls if m == "turn/start"]
        self.assertEqual(turns[0]["sandboxPolicy"]["type"], "readOnly")
        self.assertEqual(turns[1]["sandboxPolicy"]["type"], "workspaceWrite")
        self.assertEqual(restored.snapshot()["sessions"][0]["thread_id"], "persisted-thread")

    def test_failed_completion_is_not_success(self):
        FakeConnection.status = "failed"
        self.manager.open()
        done = self.manager.on_done = mock.Mock()
        with mock.patch.object(sessions, "Connection", FakeConnection):
            self.manager.start("Find next task")
            self.manager.thread.join(3)
        self.assertFalse(done.call_args.args[0]["ok"])
        self.assertEqual(self.manager.snapshot()["sessions"][0]["status"], "failed")

    def test_only_one_active_worker(self):
        self.manager.open()
        self.manager.active = "frontier"
        self.assertIn("still working", self.manager.start("another task"))

    def test_claude_session_has_separate_name_and_history(self):
        self.manager.open()
        with mock.patch.object(terminal, "_claude_exe", return_value="claude.exe"):
            self.manager.open(provider="claude")
            self.assertIn("different provider", self.manager.open("Frontier", provider="claude"))
        self.assertEqual(self.manager.entries["frontier claude"]["provider"], "claude")
        self.assertEqual(self.manager.entries["frontier"]["provider"], "codex")

    def test_claude_reports_and_persists_resume_id(self):
        def run(worker, task, session):
            self.assertEqual(worker.cwd, str(self.root))
            self.assertTrue(worker.research)
            self.assertIn("Read and follow", task)
            worker.session_id = session or "claude-session"
            worker.on_done({"ok": True, "report": "Next task identified."})
        with mock.patch.object(terminal, "_claude_exe", return_value="claude.exe"), \
             mock.patch.object(terminal.TerminalWorker, "_run", run):
            self.manager.open(provider="claude")
            self.manager.start("Find our next move")
            self.manager.thread.join(3)
        self.assertEqual(self.manager.entries["frontier claude"]["thread_id"], "claude-session")
        self.assertEqual(self.manager.entries["frontier claude"]["report"], "Next task identified.")
        self.assertFalse(self.manager.running)

    def test_claude_cli_uses_project_and_explicit_permission_mode(self):
        for research, mode in ((True, "plan"), (False, "bypassPermissions")):
            worker = terminal.TerminalWorker(cwd=str(self.root), research=research)
            proc = mock.Mock()
            proc.stdout = iter([json.dumps({"type": "result", "result": "Done", "session_id": "sid"})])
            with mock.patch.object(terminal, "_claude_exe", return_value="claude.exe"), \
                 mock.patch.object(terminal.subprocess, "Popen", return_value=proc) as popen:
                result = worker._claude("task", "sid")
            args = popen.call_args.args[0]
            self.assertEqual(args[args.index("--permission-mode") + 1], mode)
            self.assertEqual(args[args.index("--resume") + 1], "sid")
            self.assertEqual(popen.call_args.kwargs["cwd"], str(self.root))
            self.assertEqual(result["session_id"], "sid")

    def test_cancel_also_stops_claude_worker(self):
        self.manager.claude_worker = mock.Mock()
        self.manager.cancel()
        self.manager.claude_worker.cancel.assert_called_once()

    def test_child_agent_completion_cannot_finish_parent_task(self):
        self.prepare_approval()
        self.manager.entries["frontier"]["thread_id"] = "parent"
        self.manager.turn_id = "parent-turn"
        self.manager._event({"method": "turn/started", "params": {"threadId": "child", "turn": {"id": "child-turn"}}})
        self.manager._event({"method": "turn/completed", "params": {"threadId": "child", "turn": {"status": "completed"}}})
        self.assertEqual(self.manager.turn_id, "parent-turn")
        self.assertIsNone(self.manager._complete)

    def prepare_approval(self, mode="work"):
        self.manager.open()
        self.manager.active = "frontier"
        self.manager.entries["frontier"]["mode"] = mode

    def approve_command(self, command, **params):
        return self.manager._approval({"method": "item/commandExecution/requestApproval", "params": {"command": command, **params}})

    def test_routine_build_no_spoken_approval(self):
        self.prepare_approval()
        with mock.patch.object(sessions.approvals, "ask") as ask:
            self.assertEqual(self.approve_command("powershell -File fresh/Build.ps1"), {"decision": "accept"})
            ask.assert_not_called()

    def test_risky_action_requires_explicit_answer(self):
        self.prepare_approval()
        with mock.patch.object(sessions.approvals, "ask", return_value=(False, "no")) as ask:
            self.assertEqual(self.approve_command("git reset --hard"), {"decision": "decline"})
            ask.assert_called_once()
        with mock.patch.object(sessions.approvals, "ask", return_value=(True, "yes")):
            self.assertEqual(self.approve_command("git push origin main"), {"decision": "accept"})

    def test_research_cannot_auto_approve_unknown_command(self):
        self.prepare_approval("research")
        with mock.patch.object(sessions.approvals, "ask", return_value=(False, "no")):
            self.assertEqual(self.approve_command("python change.py"), {"decision": "decline"})

    def test_file_edits_inside_project_only_auto_approved(self):
        self.prepare_approval()
        self.manager._items["edit"] = {"changes": [{"path": str(self.root / "file.txt"), "kind": {"type": "update"}}]}
        event = {"method": "item/fileChange/requestApproval", "params": {"itemId": "edit"}}
        with mock.patch.object(sessions.approvals, "ask") as ask:
            self.assertEqual(self.manager._approval(event), {"decision": "accept"})
            ask.assert_not_called()
        self.manager._items["edit"]["changes"][0]["kind"]["type"] = "delete"
        with mock.patch.object(sessions.approvals, "ask", return_value=(False, "no")):
            self.assertEqual(self.manager._approval(event), {"decision": "decline"})

    def test_cancelled_approval_cannot_proceed(self):
        self.prepare_approval()
        self.manager.cancelled.set()
        self.assertEqual(self.approve_command("python test.py"), {"decision": "decline"})

    def test_stale_running_status_not_restored_as_live(self):
        self.manager.open()
        self.manager.entries["frontier"]["status"] = "running"
        self.manager._save()
        self.assertEqual(sessions.SessionManager().snapshot()["sessions"][0]["status"], "interrupted")

    def test_cancel_sends_correct_turn_and_thread(self):
        self.prepare_approval()
        self.manager.entries["frontier"]["thread_id"] = "thread1"
        self.manager.turn_id = "turn1"
        conn = self.manager.connection = mock.Mock()
        self.manager.cancel()
        conn.request.assert_called_once_with("turn/interrupt", {"threadId": "thread1", "turnId": "turn1"})

    def test_publication_and_destructive_git_guard(self):
        for command in ("git push origin main", "git reset --hard", "npm publish", "gh pr merge 5"):
            self.assertEqual(cc_guard.decide("Bash", {"command": command})[0], "approval")

    def test_current_installed_protocol_schemas(self):
        base = Path(sessions.HERE) / "data/codex-schema"
        if not base.exists():
            self.skipTest("Installed Codex schemas not generated")
        self.manager.open()
        with mock.patch.object(sessions, "Connection", FakeConnection):
            self.manager.start("Find next task")
            self.manager.thread.join(3)
        for method, params in FakeConnection.calls:
            filename = {"thread/start": "ThreadStartParams", "turn/start": "TurnStartParams"}.get(method)
            if filename:
                schema = json.loads((base / "v2" / (filename + ".json")).read_text())
                self.assertTrue(set(schema.get("required", [])) <= params.keys())
                self.assertTrue(params.keys() <= schema["properties"].keys())
                policies = schema["definitions"]["AskForApproval"]["oneOf"]
                self.assertIn(params["approvalPolicy"], policies[0]["enum"])
                if method == "thread/start":
                    self.assertIn(params["sandbox"], schema["definitions"]["SandboxMode"]["enum"])
                else:
                    variants = schema["definitions"]["SandboxPolicy"]["oneOf"]
                    self.assertTrue(any(params["sandboxPolicy"]["type"] in v["properties"]["type"]["enum"] for v in variants))
                    text_input = next(v for v in schema["definitions"]["UserInput"]["oneOf"] if v["title"] == "TextUserInput")
                    self.assertTrue(set(text_input["required"]) <= params["input"][0].keys())
