"""The Linux sandbox for a Claude agent working while the owner is away (wsl_sandbox.py and sandbox/)."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import agent_sessions as sessions
import away_jobs
import terminal
import tools
import wsl_sandbox
from tests.test_away_jobs import Base as AwayBase

HERE = Path(wsl_sandbox.__file__).resolve().parent
GOOD = {"user": "agent", "root": False, "sudo": False, "windows_drives": [], "windows_programs": False,
        "bwrap": True, "socat": True, "claude": True, "settings_locked": True, "guard_locked": True}


def load(name):
    spec = importlib.util.spec_from_file_location(f"sandbox_{name}", HERE / "sandbox" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReadyTest(unittest.TestCase):
    def problem(self, facts=GOOD, signed_in=True, distros=("JarvisSandbox",)):
        def run(*command, **kwargs):
            if command[-1].endswith("check.py"):
                return 0, json.dumps(facts)
            return (0 if signed_in else 1), json.dumps({"loggedIn": signed_in, "authMethod": "claude.ai" if signed_in else "none"})
        with mock.patch.object(wsl_sandbox, "_exe", return_value="wsl.exe"), \
                mock.patch.object(wsl_sandbox, "distros", return_value=list(distros)), \
                mock.patch.object(wsl_sandbox, "run", run):
            return wsl_sandbox.problem()

    def test_a_test_run_never_reaches_the_real_sandbox(self):
        self.assertIsNone(wsl_sandbox._exe())
        self.assertIn("isn't installed", wsl_sandbox.problem())
        self.assertEqual(wsl_sandbox.run("/bin/true")[0], None)
        with self.assertRaises(RuntimeError):
            wsl_sandbox.launch("/work/job", "task", "rules")

    def test_ready_only_when_set_up_locked_down_and_signed_in(self):
        self.assertEqual(self.problem(), "")
        self.assertIn("hasn't been set up", self.problem(distros=("Ubuntu",)))
        not_signed_in = self.problem(signed_in=False)
        self.assertIn("isn't signed in to your Claude plan", not_signed_in)
        self.assertIn("auth login", not_signed_in)

    def test_a_sandbox_someone_loosened_is_not_trusted(self):
        for change, words in (({"windows_drives": ["/mnt/c"]}, "a Windows drive is mounted in it (/mnt/c)"),
                              ({"sudo": True}, "administrator rights"),
                              ({"root": True}, "administrator rights"),
                              ({"windows_programs": True}, "can start Windows programs"),
                              ({"bwrap": False}, "packages Claude Code's sandbox needs"),
                              ({"claude": False}, "Claude Code isn't installed"),
                              ({"settings_locked": False}, "the agent could change them"),
                              ({"guard_locked": False}, "the agent could change them")):
            with self.subTest(change=change):
                problem = self.problem(facts={**GOOD, **change})
                self.assertIn("isn't safe to use", problem)
                self.assertIn(words, problem)
        self.assertIn("self-check didn't answer", self.problem(facts={}))


class ShareTest(unittest.TestCase):
    def prepare(self, replies, workspace=r"C:\Users\Owner\Documents\Jarvis Builds\ai business-3", read_only=()):
        calls = []

        def run(*command, root=False, text_in="", timeout=120):
            calls.append(SimpleNamespace(command=command, root=root, text_in=text_in))
            return replies.get(command[-1].rsplit("/", 1)[-1], (0, ""))
        with mock.patch.object(wsl_sandbox, "run", run):
            return wsl_sandbox.prepare(workspace, read_only), calls

    def test_only_the_jobs_folder_is_shared_and_documents_only_to_read(self):
        folder, calls = self.prepare({"prepare.py": (0, '{"ok": true, "mounted": []}')},
                                     read_only=[r"C:\Users\Owner\Documents"])
        self.assertEqual(folder, "/work/ai-business-3")
        spec = json.loads(calls[-1].text_in)
        self.assertEqual(spec["shares"], [
            {"windows": r"C:\Users\Owner\Documents\Jarvis Builds\ai business-3", "at": "/work/ai-business-3", "writable": True},
            {"windows": r"C:\Users\Owner\Documents", "at": "/owner/Documents", "writable": False}])
        self.assertTrue(calls[-1].root)                                   # only root can mount

    def test_the_rules_inside_are_refreshed_from_the_repo_before_every_run(self):
        _, calls = self.prepare({"prepare.py": (0, '{"ok": true}')})
        written = {call.command[-1]: call for call in calls if call.command[0].endswith("tee")}
        self.assertEqual(set(written), {*wsl_sandbox.INSTALLED.values(), wsl_sandbox.GUARD})
        self.assertTrue(all(call.root for call in written.values()))
        self.assertEqual(written[wsl_sandbox.GUARD].text_in, (HERE / "cc_guard.py").read_text(encoding="utf-8"))

    def test_a_folder_that_cant_be_shared_stops_the_run(self):
        with self.assertRaises(RuntimeError) as failed:
            self.prepare({"prepare.py": (1, '{"ok": false, "error": "CalledProcessError: mount"}')})
        self.assertIn("CalledProcessError: mount", str(failed.exception))
        with self.assertRaises(RuntimeError) as failed:
            self.prepare({"cc_guard.py": (1, "tee: permission denied")})
        self.assertIn("couldn't write /opt/jarvis/cc_guard.py", str(failed.exception))

    def test_the_task_goes_in_on_standard_input_and_no_windows_variables_ride_along(self):
        process = mock.Mock()
        with mock.patch.object(wsl_sandbox, "_exe", return_value="wsl.exe"), \
                mock.patch.object(wsl_sandbox.subprocess, "Popen", return_value=process) as popen, \
                mock.patch.dict(wsl_sandbox.os.environ, {"WSLENV": "HA_TOKEN/u", "HA_TOKEN": "secret"}):
            wsl_sandbox.launch("/work/job", 'Say "hi"\nthen stop', "the rules", model="claude-fable-5-2", effort="high", resume="s1")
        command, env = popen.call_args.args[0], popen.call_args.kwargs["env"]
        self.assertEqual(command, ["wsl.exe", "-d", "JarvisSandbox", "-u", "agent", "-e", "/usr/bin/python3", "/opt/jarvis/run_agent.py"])
        self.assertNotIn("WSLENV", env)
        spec = json.loads(process.stdin.write.call_args.args[0])
        self.assertEqual((spec["cwd"], spec["prompt"], spec["rules"], spec["model"], spec["effort"], spec["resume"]),
                         ("/work/job", 'Say "hi"\nthen stop', "the rules", "claude-fable-5-2", "high", "s1"))
        process.stdin.close.assert_called_once()


class FilesInsideTest(unittest.TestCase):
    """What is installed into the distro. Its behaviour there was checked for real on 2026-11-11; these keep the
    files from drifting."""

    def test_claude_codes_own_sandbox_is_on_and_cant_be_skipped(self):
        settings = json.loads((HERE / "sandbox" / "managed-settings.json").read_text(encoding="utf-8"))
        box = settings["sandbox"]
        self.assertEqual((box["enabled"], box["failIfUnavailable"], box["allowUnsandboxedCommands"]), (True, True, False))
        self.assertTrue(box["network"]["strictAllowlist"])                # bypass mode would otherwise allow any host
        self.assertIn("~/.claude/.credentials.json", box["filesystem"]["denyRead"])
        hook = settings["hooks"]["PreToolUse"][0]
        self.assertEqual(hook["matcher"], terminal.GUARDED_TOOLS)
        self.assertIn(wsl_sandbox.GUARD, hook["hooks"][0]["command"])

    def test_the_distro_is_made_without_windows_drives_or_windows_programs(self):
        script = (HERE / "sandbox" / "provision.sh").read_text(encoding="utf-8")
        for line in ("[automount]\nenabled=false", "[interop]\nenabled=false", "default=agent", "passwd -l root", "bubblewrap socat"):
            self.assertIn(line, script)
        self.assertNotIn("sudo ", script.split("EOF")[0].split("gpasswd")[0].split("set -euo")[1])

    def test_shares_go_only_where_a_jobs_shares_belong(self):
        prepare = load("prepare")
        with mock.patch.object(prepare.subprocess, "run") as run, mock.patch.object(prepare.os, "makedirs"):
            prepare.share(r"C:\job", "/work/job", True)
            prepare.share(r"C:\Users\Owner\Documents", "/owner/Documents", False)
            for bad in ("/home/agent/x", "/work/../etc", "/work/a/b", "/mnt/c"):
                with self.assertRaises(ValueError):
                    prepare.share(r"C:\\", bad, True)
        options = [call.args[0][-1] for call in run.call_args_list]
        self.assertEqual(len(options), 2)
        self.assertNotIn(",ro", options[0])
        self.assertTrue(options[1].endswith(",ro"))                       # read-only is the mount's, not a rule's

    def test_the_self_check_reports_a_windows_drive_mounted_outside_a_jobs_shares(self):
        check = load("check")
        mounts = ("C:\\\\ /mnt/c 9p rw,aname=drvfs;path=C:\\\\ 0 0\n"
                  "C:\\\\job /work/job 9p rw,aname=drvfs;path=C:\\\\job 0 0\n"
                  "drivers /usr/lib/wsl/drivers 9p ro,aname=drivers 0 0\n")
        with mock.patch("builtins.open", mock.mock_open(read_data=mounts)):
            self.assertEqual(check.windows_drives(), ["/mnt/c"])


class RunTest(unittest.TestCase):
    def worker(self):
        worker = terminal.TerminalWorker(cwd=r"C:\builds\job")
        worker.unattended_root, worker.sandbox = r"C:\builds\job", {"read_only": [r"C:\Users\Owner\Documents"]}
        worker.model, worker.effort = "claude-fable-5-2", "high"
        return worker

    def test_a_sandboxed_run_starts_inside_and_never_on_windows(self):
        process = mock.Mock(stdout=iter(['{"type": "system", "subtype": "init", "session_id": "s1", "apiKeySource": "none"}\n',
                                         '{"type": "result", "session_id": "s1", "result": "Done.", "is_error": false}\n']), pid=1)
        with mock.patch.object(wsl_sandbox, "prepare", return_value="/work/job") as prepare, \
                mock.patch.object(wsl_sandbox, "launch", return_value=process) as launch, \
                mock.patch.object(wsl_sandbox, "stop") as stop, \
                mock.patch.object(terminal.subprocess, "Popen") as on_windows, mock.patch.object(terminal.hud, "emit"):
            result = self.worker()._claude("Research it", "s0")
        self.assertEqual(result["result"], "Done.")
        on_windows.assert_not_called()
        prepare.assert_called_once_with(r"C:\builds\job", [r"C:\Users\Owner\Documents"])
        sent = launch.call_args.kwargs
        self.assertEqual((sent["cwd"], sent["prompt"], sent["model"], sent["effort"], sent["resume"], sent["permission_mode"]),
                         ("/work/job", "Research it", "claude-fable-5-2", "high", "s0", "bypassPermissions"))
        self.assertIn("inside a Linux sandbox", sent["rules"])
        self.assertIn("Nobody is at the PC", sent["rules"])
        self.assertNotIn("on their Windows PC.", sent["rules"])
        stop.assert_called_once()                                         # nothing it started outlives the run

    def test_the_billing_guard_still_ends_a_run_that_would_use_an_api_key(self):
        process = mock.Mock(stdout=iter(['{"type": "system", "subtype": "init", "session_id": "s1", "apiKeySource": "ANTHROPIC_API_KEY"}\n']), pid=1)
        process.poll.return_value = 0
        with mock.patch.object(wsl_sandbox, "prepare", return_value="/work/job"), mock.patch.object(wsl_sandbox, "stop"), \
                mock.patch.object(wsl_sandbox, "launch", return_value=process), mock.patch.object(terminal.hud, "emit"):
            result = self.worker()._claude("Research it", None)
        self.assertTrue(result["is_error"])
        self.assertIn("won't spend API credits", result["result"])

    def test_a_sandbox_that_cant_be_made_ready_fails_the_run_instead_of_running_outside_it(self):
        with mock.patch.object(wsl_sandbox, "prepare", side_effect=RuntimeError("couldn't share the job's folder")), \
                mock.patch.object(wsl_sandbox, "launch") as launch, mock.patch.object(wsl_sandbox, "stop") as stop, \
                mock.patch.object(terminal.subprocess, "Popen") as on_windows:
            result = self.worker()._claude("Research it", None)
        self.assertTrue(result["is_error"])
        self.assertIn("couldn't share the job's folder", result["result"])
        launch.assert_not_called()
        on_windows.assert_not_called()
        stop.assert_called_once()

    def test_stopping_a_sandboxed_run_shuts_the_sandbox_down(self):
        worker = self.worker()
        worker._proc = mock.Mock(pid=1)
        worker._proc.poll.return_value = None
        with mock.patch.object(terminal.subprocess, "run"), mock.patch.object(wsl_sandbox, "stop") as stop:
            worker._kill()
        stop.assert_called_once()
        plain = terminal.TerminalWorker(cwd="C:/job")
        plain._proc = worker._proc
        with mock.patch.object(terminal.subprocess, "run"), mock.patch.object(wsl_sandbox, "stop") as stop:
            plain._kill()
        stop.assert_not_called()


class SessionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for patch in (mock.patch("preferences.PATH", self.root / "preferences.json"),
                      mock.patch.object(sessions, "STORE", self.root / "sessions.json"),
                      mock.patch.object(sessions.hud, "emit"),
                      mock.patch.object(sessions.threading, "Thread")):
            patch.start()
            self.addCleanup(patch.stop)
        self.manager = sessions.SessionManager()

    def test_the_sandbox_choice_is_kept_with_the_session_and_only_for_claude(self):
        choice = {"read_only": ["C:/Users/Owner/Documents"]}
        self.manager.prepare_unattended("Away Builder", "Widget", self.root, "fable", choice)
        self.assertEqual(self.manager.entries["away builder"]["sandbox"], choice)
        self.manager.prepare_unattended("Away Builder", "Widget", self.root, "", choice)    # Codex has its own sandbox
        self.assertIsNone(self.manager.entries["away builder"]["sandbox"])
        self.manager.prepare_unattended("Away Builder", "Widget", self.root, "fable")       # and it doesn't linger
        self.assertIsNone(self.manager.entries["away builder"]["sandbox"])

    def test_the_claude_worker_is_told_to_run_inside(self):
        choice = {"read_only": []}
        self.manager.prepare_unattended("Away Builder", "Widget", self.root, "fable", choice)
        entry = self.manager.entries["away builder"]
        entry.update(model="claude-fable-5-2", effort="high", name="Away Builder")
        made = []

        class FakeTerminalWorker:
            def __init__(self, cwd=None, research=False):
                self.unattended_root, self.sandbox, self.session_id = "", None, None
                made.append(self)

            def _run(self, prompt, session):
                self.on_done({"ok": True, "finished": True, "report": "Built.", "outcome": "done"})
        with mock.patch.object(sessions.terminal, "TerminalWorker", FakeTerminalWorker):
            sessions.Worker(self.manager, "away builder")._run_claude(entry, "Build it", "work")
        self.assertEqual((made[0].unattended_root, made[0].sandbox), (str(self.root), choice))


class AwayJobTest(AwayBase):
    """A Fable away job goes into the sandbox when it is ready, and says which way it ran."""

    def setUp(self):
        super().setUp()
        import knowledge
        self.documents = self.root / "Documents"
        self.vault = self.documents / "JARVIS Knowledge"
        self.vault.mkdir(parents=True)
        self.why_not = ""
        self.queue.sandbox_problem = lambda: self.why_not
        for patcher in (mock.patch.object(knowledge, "VAULT", self.vault), mock.patch.object(away_jobs, "DOCUMENTS", self.documents),
                        mock.patch("research._owner", return_value="Works ten hours a week.")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_fable_research_runs_inside_with_documents_shared_to_read(self):
        job = self.queue.add("which AI business should I start", "research", model="fable")
        self.queue.tick()
        self.assertEqual(self.sessions.sandboxes, [{"read_only": [str(self.documents)]}])
        self.assertTrue(job["sandbox"])
        task = self.sessions.started[0]["task"]
        self.assertIn("their notes are in /owner/Documents/JARVIS Knowledge", task)
        self.assertIn("their projects\n  are under /owner/Documents)", task)
        self.assertNotIn(str(self.documents), task)                       # no Windows path the agent can't reach
        self.assertIn("inside the Linux sandbox", self.texts[0])
        self.assertIn("change only its own folder", self.texts[0])

    def test_a_fable_build_runs_inside_with_only_its_private_copy(self):
        job = self.queue.add("make the widget", "build", project=str(self.repo), model="fable")
        self.queue.tick()
        self.assertEqual(self.sessions.sandboxes, [{"read_only": []}])
        task = self.sessions.started[0]["task"]
        self.assertIn("You are in a Linux sandbox and the owner's PC is Windows", task)
        self.assertNotIn("python.exe", task)
        self.assertIn("private copy inside the Linux sandbox", self.texts[0])
        self.agent_finishes(job, files={"widget.py": "x = 1\n", "tests/test_widget.py": "import unittest\n"})
        self.assertEqual(job["status"], "done")
        self.assertTrue(self.sandbox.called)                              # Jarvis still re-runs the tests on Windows

    def test_when_the_sandbox_isnt_ready_the_job_runs_under_the_rules_and_says_so(self):
        self.why_not = "Claude Code inside the Linux sandbox isn't signed in to your Claude plan"
        job = self.queue.add("which AI business should I start", "research", model="fable")
        self.queue.tick()
        self.assertEqual(self.sessions.sandboxes, [None])
        self.assertNotIn("sandbox", job)
        self.assertIn(str(self.vault), self.sessions.started[0]["task"])
        self.assertIn("Held by rules only, not the sandbox: Claude Code inside the Linux sandbox isn't signed in", self.texts[0])

    def test_a_check_that_breaks_counts_as_not_ready(self):
        self.queue.sandbox_problem = mock.Mock(side_effect=OSError("wsl.exe vanished"))
        self.queue.add("which AI business should I start", "research", model="fable")
        self.queue.tick()
        self.assertEqual(self.sessions.sandboxes, [None])
        self.assertIn("couldn't be checked", self.texts[0])

    def test_codex_jobs_never_ask_about_it(self):
        self.queue.sandbox_problem = mock.Mock(return_value="")
        self.add_build()
        self.queue.sandbox_problem.assert_not_called()
        self.assertEqual(self.sessions.sandboxes, [None])

    def test_the_queue_tool_tells_jarvis_which_way_it_will_run(self):
        def queue_it(request):
            with mock.patch("away_jobs.QUEUE", self.queue), mock.patch("truth_guard.tainted", return_value=False):
                return tools.run_tool(SimpleNamespace(name="queue_away_job", id="t", input={
                    "request": request, "kind": "research", "model": "fable"}))["content"]
        self.assertIn("inside the Linux sandbox: only that folder is shared with this PC",
                      queue_it("which AI business should I start"))
        self.why_not = "the Linux sandbox hasn't been set up"
        reply = queue_it("what would a clipping channel earn")
        self.assertIn("under rules rather than a sandbox, because the Linux sandbox hasn't been set up", reply)
        self.assertIn("Tell the user that", reply)

    def test_a_report_that_is_a_link_to_another_file_is_not_read(self):
        job = self.queue.add("which AI business should I start", "research", model="fable")
        self.queue.tick()
        secret = self.root / "secret.txt"
        secret.write_text("## Spoken summary\nThe owner's private notes.\n")
        try:
            (Path(job["workspace"]) / "REPORT.md").symlink_to(secret)
        except OSError:
            self.skipTest("this account can't create links")
        self.sessions.running = False
        self.queue.session_done({"name": away_jobs.SESSION, "task": "x", "ok": True, "report": "Done.", "outcome": "done",
                                 "evidence": ""})
        self.assertNotIn("vault_note", job)
        self.assertNotEqual(job.get("report"), "The owner's private notes.")


if __name__ == "__main__":
    unittest.main()
