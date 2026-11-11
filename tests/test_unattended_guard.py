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

    def test_it_may_do_what_any_agent_may_and_a_message_to_others_is_asked(self):
        for command in ("winget install something", "git push origin main", "git reset --hard HEAD~3",
                        "Set-ItemProperty HKCU:\\Software\\x -Name y -Value 1", "powershell -enc AAAABBBBCCCCDDDDEEEE"):
            self.assertEqual(self.verdict("PowerShell", command=command), ("allow", ""), command)
        self.assertEqual(self.verdict("PowerShell", command='gh pr comment 3 --body "done"'), ("approval", cc_guard.MESSAGE))

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

    def test_apps_the_owner_put_off_limits_stay_so(self):
        command = r"Get-ChildItem C:\Users\x\AppData\Roaming\Microsoft\Teams"
        with mock.patch.dict(cc_guard.os.environ, {"JARVIS_BLOCK_WORK_APPS": "teams"}):
            self.assertEqual(self.shell(command)[0:7], "blocked")
        with mock.patch.dict(cc_guard.os.environ, {"JARVIS_BLOCK_WORK_APPS": ""}):
            self.assertEqual(self.shell(command), "allow")

    def hook(self, command, **env):
        call = {"tool_name": "PowerShell", "tool_input": {"command": command}, "session_id": "s"}
        out = io.StringIO()
        with mock.patch.dict(cc_guard.os.environ, {cc_guard.UNATTENDED_ROOT: str(self.root), **env}), \
                mock.patch.object(cc_guard.sys, "stdin", io.StringIO(json.dumps(call))), \
                mock.patch.object(cc_guard.sys, "stdout", out), \
                mock.patch.object(cc_guard, "record_pending") as pending, self.assertRaises(SystemExit):
            cc_guard.main()
        reason = json.loads(out.getvalue())["hookSpecificOutput"]["permissionDecisionReason"] if out.getvalue() else ""
        return reason, pending

    def test_the_hook_pauses_a_message_so_the_owner_can_be_texted(self):
        reason, pending = self.hook('gh pr comment 3 --body "done"')
        self.assertTrue(reason.startswith("PAUSED:"))
        self.assertIn("APPROVAL NEEDED", reason)
        pending.assert_called_once()
        reason, pending = self.hook("winget install x")               # nothing to pause: it just runs
        self.assertEqual(reason, "")

    def test_inside_the_sandbox_it_is_refused_because_no_yes_could_reach_it(self):
        reason, pending = self.hook('gh pr comment 3 --body "done"', **{cc_guard.SANDBOXED: "1"})
        self.assertTrue(reason.startswith("BLOCKED:"))
        self.assertIn("inside the sandbox", reason)
        self.assertNotIn("APPROVAL NEEDED", reason)
        pending.assert_not_called()

    def test_a_pause_is_still_reported_when_its_record_cant_be_written(self):
        call = {"tool_name": "PowerShell", "tool_input": {"command": 'gh pr comment 3 --body "x"'}, "session_id": "s"}
        out = io.StringIO()
        with mock.patch.object(cc_guard.sys, "stdin", io.StringIO(json.dumps(call))), \
                mock.patch.object(cc_guard.sys, "stdout", out), mock.patch.object(cc_guard, "approved", return_value=False), \
                mock.patch.object(cc_guard, "record_pending", side_effect=OSError("read-only")), self.assertRaises(SystemExit):
            cc_guard.main()
        self.assertIn("PAUSED", out.getvalue())                       # a crash here would have let it run


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
        self.assertIn("The owner is away from the PC", rules)
        self.assertIn("Jarvis texts", rules)                 # a question reaches them by text now
        self.assertIn("writing or deleting anywhere else is refused", rules)
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

    def away_run(self, worker, said):
        answers = [{"result": "APPROVAL NEEDED: May I email the supplier for a quote?", "session_id": "s1"},
                   {"result": "I left the email unsent and finished the rest.\nOUTCOME: partial", "session_id": "s1"}]
        prompts, done = [], []
        worker.on_done = done.append

        def fake(prompt, session):
            prompts.append(prompt)
            return answers[len(prompts) - 1]
        with mock.patch.object(worker, "_claude", fake), mock.patch.object(terminal, "write_settings"), \
                mock.patch.object(terminal.approvals, "ask", return_value=said) as ask, mock.patch.object(terminal.hud, "emit"), \
                mock.patch.object(terminal, "grant") as grant, mock.patch.object(terminal.task_effort, "record"):
            worker._run("Build it", None)
        return ask, grant, prompts, done

    def test_a_question_with_nobody_there_is_texted_to_the_owner(self):
        worker = terminal.TerminalWorker(cwd="C:/job")
        worker.unattended_root = "C:/job"
        ask, grant, prompts, done = self.away_run(worker, (False, "(no answer within ten minutes)"))
        self.assertEqual(ask.call_args.args[0], "May I email the supplier for a quote?")
        self.assertTrue(ask.call_args.kwargs["away"])        # ten minutes to answer by text, not two
        grant.assert_not_called()
        self.assertIn("said no", prompts[1])
        self.assertEqual(done[0]["outcome"], "partial")
        ask, grant, prompts, _ = self.away_run(worker, (True, "yes"))
        grant.assert_called_once()
        self.assertIn("said yes", prompts[1])

    def test_inside_the_sandbox_a_question_is_answered_no_without_asking(self):
        worker = terminal.TerminalWorker(cwd="C:/job")
        worker.unattended_root, worker.sandbox = "C:/job", {"read_only": []}
        ask, _, prompts, done = self.away_run(worker, (True, "yes"))
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
