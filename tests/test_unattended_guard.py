"""The rules for a Claude agent working with nobody at the PC (an away job on Fable): refuse, never ask."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agent_sessions as sessions
import cc_guard
import terminal


class UnattendedRulesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "Jarvis Builds" / "job-1"   # a space in the path, as the real one has
        self.root.mkdir(parents=True)
        self.outside = Path(self.temp.name).resolve() / "Documents"
        self.outside.mkdir()

    def verdict(self, tool, **tool_input):
        return cc_guard.unattended(tool, tool_input, str(self.root))

    def shell(self, command):
        return self.verdict("PowerShell", command=command)[0]

    def test_ordinary_work_runs(self):
        for command in ("python -m unittest discover -s tests", "git status", "npm test", "mkdir out",
                        f"& '{self.outside}\\.venv\\Scripts\\python.exe' -m unittest",   # the project's own Python, by full path
                        f"Get-Content '{self.outside}\\notes.md'"):                       # reading elsewhere is allowed
            self.assertEqual(self.shell(command), "allow", command)
        self.assertEqual(self.verdict("Read", file_path=str(self.outside / "notes.md"))[0], "allow")
        self.assertEqual(self.verdict("Write", file_path=str(self.root / "REPORT.md"), content="x")[0], "allow")
        self.assertEqual(self.verdict("Edit", file_path=str(self.root / "src" / "app.py"))[0], "allow")

    def test_file_tools_write_only_inside_its_folder(self):
        verdict, why = self.verdict("Write", file_path=str(self.outside / "notes.md"), content="x")
        self.assertEqual(verdict, "blocked")
        self.assertIn("only inside", why)
        self.assertEqual(self.verdict("Edit", file_path=str(self.root / ".." / ".." / "Documents" / "x.py"))[0], "blocked")
        self.assertEqual(self.verdict("Write", file_path="", content="x")[0], "blocked")

    def test_what_would_need_a_yes_is_refused_not_asked(self):
        for command in ("winget install something", "git push origin main", "git reset --hard HEAD~3",
                        "Set-ItemProperty HKCU:\\Software\\x -Name y -Value 1", "powershell -enc AAAABBBBCCCCDDDDEEEE"):
            verdict, why = self.verdict("PowerShell", command=command)
            self.assertEqual(verdict, "blocked", command)
            self.assertIn("nobody is here to approve it", why)

    def test_it_may_tidy_its_own_folder_but_delete_nothing_else(self):
        self.assertEqual(self.shell("Remove-Item build -Recurse -Force"), "allow")
        self.assertEqual(self.shell(f"Remove-Item '{self.root}\\old.txt'"), "allow")     # full path, spaces and all
        for command in (f"Remove-Item '{self.outside}\\notes.md'", "Remove-Item ..\\other-job -Recurse",
                        "rm -rf ~/Documents", "Remove-Item $env:USERPROFILE\\x", "rm -rf /c/Users/someone"):
            self.assertEqual(self.shell(command), "blocked", command)

    def test_it_cannot_move_its_shell_out_of_the_folder(self):
        self.assertEqual(self.shell("cd src; python build.py"), "allow")
        for command in (f"cd '{self.outside}'; Remove-Item notes.md", "cd ..; del thing.txt", "Set-Location ~"):
            self.assertEqual(self.shell(command), "blocked", command)

    def test_credentials_files_cannot_be_read_but_may_be_written_about(self):
        self.assertEqual(self.verdict("Read", file_path=str(self.outside / ".env"))[0], "blocked")
        self.assertEqual(self.shell(f"Get-Content {self.outside}\\.env"), "blocked")
        self.assertEqual(self.verdict("Grep", pattern="TOKEN", path=str(self.outside / "credentials.json"))[0], "blocked")
        readme = self.verdict("Write", file_path=str(self.root / "README.md"), content="Copy .env.example to .env first.")
        self.assertEqual(readme[0], "allow")

    def test_work_apps_stay_off_limits(self):
        self.assertEqual(self.shell(r"Get-ChildItem C:\Users\x\AppData\Roaming\Microsoft\Teams")[0:7], "blocked")

    def test_the_hook_refuses_instead_of_pausing_when_the_folder_is_set(self):
        call = {"tool_name": "PowerShell", "tool_input": {"command": "winget install x"}, "session_id": "s"}
        out = io.StringIO()
        with mock.patch.dict(cc_guard.os.environ, {cc_guard.UNATTENDED_ROOT: str(self.root)}), \
                mock.patch.object(cc_guard.sys, "stdin", io.StringIO(json.dumps(call))), \
                mock.patch.object(cc_guard.sys, "stdout", out), \
                mock.patch.object(cc_guard, "record_pending") as pending, self.assertRaises(SystemExit):
            cc_guard.main()
        reason = json.loads(out.getvalue())["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertTrue(reason.startswith("BLOCKED:"))
        self.assertNotIn("APPROVAL NEEDED", reason)          # nothing to wait for
        pending.assert_not_called()                           # and nothing a later yes could unlock


class UnattendedRunTest(unittest.TestCase):
    def claude(self, worker, lines=None):
        lines = lines or ['{"type": "result", "session_id": "s1", "result": "Done.", "is_error": false}\n']
        process = mock.Mock(stdout=iter(lines), pid=1)
        with mock.patch.object(terminal, "_claude_exe", return_value="claude.exe"), \
                mock.patch.object(terminal.subprocess, "Popen", return_value=process) as popen, \
                mock.patch.object(terminal.hud, "emit"), \
                mock.patch.dict(terminal.os.environ, {"HA_TOKEN": "secret", "TELEGRAM_BOT_KEY": "k", "SAFE_VALUE": "1"}):
            worker._claude("Do the thing", None)
        return popen.call_args

    def test_an_unattended_run_has_no_tokens_no_connected_services_and_the_refusing_rules(self):
        worker = terminal.TerminalWorker(cwd="C:/job")
        worker.unattended_root = "C:/job"
        call = self.claude(worker)
        command, env = call.args[0], call.kwargs["env"]
        self.assertIn("--strict-mcp-config", command)
        rules = command[command.index("--append-system-prompt") + 1]
        self.assertIn("Nobody is at the PC", rules)
        self.assertNotIn("APPROVAL NEEDED", rules)
        self.assertEqual(env[cc_guard.UNATTENDED_ROOT], "C:/job")
        self.assertNotIn("HA_TOKEN", env)
        self.assertNotIn("TELEGRAM_BOT_KEY", env)
        self.assertIn("SAFE_VALUE", env)

    def test_an_ordinary_run_is_unchanged(self):
        call = self.claude(terminal.TerminalWorker(cwd="C:/job"))
        command, env = call.args[0], call.kwargs["env"]
        self.assertNotIn("--strict-mcp-config", command)
        self.assertNotIn(cc_guard.UNATTENDED_ROOT, env)
        self.assertIn("APPROVAL NEEDED", command[command.index("--append-system-prompt") + 1])

    def test_a_question_with_nobody_there_is_answered_no_without_being_spoken(self):
        worker = terminal.TerminalWorker(cwd="C:/job")
        worker.unattended_root = "C:/job"
        answers = [{"result": "APPROVAL NEEDED: May I install the package system-wide?", "session_id": "s1"},
                   {"result": "I left the install undone and finished the rest.\nOUTCOME: partial", "session_id": "s1"}]
        prompts, done = [], []
        worker.on_done = done.append

        def fake(prompt, session):
            prompts.append(prompt)
            return answers[len(prompts) - 1]
        with mock.patch.object(worker, "_claude", fake), mock.patch.object(terminal, "write_settings"), \
                mock.patch.object(terminal.approvals, "ask") as ask, mock.patch.object(terminal.hud, "emit"), \
                mock.patch.object(terminal.task_effort, "record"):
            worker._run("Build it", None)
        ask.assert_not_called()
        self.assertEqual(prompts[1], terminal.AWAY_ANSWER)
        self.assertEqual(done[0]["outcome"], "partial")


class UnattendedSessionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for patch in (mock.patch("preferences.PATH", self.root / "preferences.json"),
                      mock.patch.object(sessions, "STORE", self.root / "sessions.json"),
                      mock.patch.object(sessions.hud, "emit"),
                      mock.patch.object(sessions, "executable", return_value="codex.exe"),
                      mock.patch.object(sessions.terminal, "_claude_exe", return_value="claude.exe"),
                      mock.patch.object(sessions.threading, "Thread")):
            patch.start()
            self.addCleanup(patch.stop)
        self.manager = sessions.SessionManager()

    def test_an_away_session_runs_on_what_its_job_was_queued_with(self):
        self.assertEqual(self.manager.prepare_unattended("Away Builder", "Widget", self.root, "fable"), "")
        reply = self.manager.start("Build it", "Away Builder", "work", fresh=True, folder=str(self.root), model="haiku", effort="high")
        self.assertIn("Away Builder started on Claude Fable 5.2, high effort", reply)   # the per-task "haiku" is ignored
        entry = self.manager.entries["away builder"]
        self.assertEqual((entry["provider"], entry["model"]), ("claude", "claude-fable-5-2"))

    def test_codex_is_still_what_an_away_session_gets_by_default(self):
        self.manager.prepare_unattended("Away Builder", "Widget", self.root)
        self.manager.start("Build it", "Away Builder", "work", fresh=True, folder=str(self.root), model="fable")
        self.assertEqual(self.manager.entries["away builder"]["provider"], "codex")

    def test_the_claude_worker_is_told_it_is_unattended(self):
        self.manager.prepare_unattended("Away Builder", "Widget", self.root, "fable")
        entry = self.manager.entries["away builder"]
        entry.update(model="claude-fable-5-2", effort="high", name="Away Builder")
        worker = sessions.Worker(self.manager, "away builder")
        made = []

        class FakeTerminalWorker:
            def __init__(self, cwd=None, research=False):
                self.unattended_root, self.session_id = "", None
                made.append(self)

            def _run(self, prompt, session):
                self.on_done({"ok": True, "finished": True, "report": "Built.", "outcome": "done"})
        with mock.patch.object(sessions.terminal, "TerminalWorker", FakeTerminalWorker):
            worker._run_claude(entry, "Build it", "work")
        self.assertEqual(made[0].unattended_root, str(self.root))


if __name__ == "__main__":
    unittest.main()
