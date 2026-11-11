"""Work that carries on while the owner is away. Real git in temp folders; a fake agent; no background threads,
so nothing here can outlive its patches and write to the owner's real data."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import away_jobs
import tools


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


class FakeSessions:
    """Stands in for the agent manager: records what was started, and lets a test act as the agent."""

    def __init__(self):
        self.running, self.started, self.prepared, self.cancelled = False, [], [], []
        self.models, self.sandboxes = [], []
        self.reply = None
        self.facts = {"commands": 3, "failed_commands": 1, "files": 2, "checks": 1, "failed_checks": 0, "latest": "running tests"}

    def prepare_unattended(self, name, project, folder, model="", sandbox=None):
        self.prepared.append((name, project, str(folder)))
        self.models.append(model)
        self.sandboxes.append(sandbox)
        return ""

    def start(self, task, name="", mode="research", resume=False, fresh=False, folder="", effort=""):
        self.started.append(dict(task=task, name=name, mode=mode, fresh=fresh, folder=folder, effort=effort))
        if self.reply:
            return self.reply
        self.running = True
        return f"{name} started. Jarvis will tell you when it finishes."

    def is_running(self, name=""):
        return self.running

    def progress_facts(self, name):
        return self.facts if self.running else None

    def cancel(self, name=""):
        self.cancelled.append(name)


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "project"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "app.py").write_text("print('real')\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "first")
        self.now = 1000.0
        self.texts, self.said, self.archived = [], [], []
        self.idle = 9999
        self.out_of_room = True   # the owner has left the room, so texts go out (whereabouts.py decides for real)
        self.sessions = FakeSessions()
        self.queue = self.make_queue()
        patcher = mock.patch("preferences.read", return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.check = mock.patch.object(away_jobs, "sandboxed", return_value=(0, "Ran 7 tests\nOK"))
        self.sandbox = self.check.start()
        self.addCleanup(self.check.stop)

    def make_queue(self):
        queue = away_jobs.AwayQueue(sessions=self.sessions, store=self.root / "jobs.json", root=self.root / "builds",
                                    notify=self.texts.append, clock=lambda: self.now, idle=lambda: self.idle,
                                    announce=self.said.append, may_text=lambda: self.out_of_room,
                                    archive=lambda *args: self.archived.append(args))
        queue.spawn = lambda work, *args: work(*args)  # runs in line: a test can't leave a thread behind
        return queue

    def add_build(self, request="make the widget", **kwargs):
        kwargs.setdefault("project", str(self.repo))
        job = self.queue.add(request, "build", **kwargs)
        self.queue.tick()
        return job

    def agent_finishes(self, job, outcome="done", report="All built.", files=None):
        """Act as the agent: leave files in the private copy, then report."""
        for name, content in (files or {}).items():
            path = Path(job["workspace"]) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        self.sessions.running = False
        return self.queue.session_done({"name": away_jobs.SESSION, "task": "x", "ok": outcome in ("done", "partial"),
                                        "report": report, "outcome": outcome, "evidence": "Jarvis observed: 3 commands."})


REPORT = """## Spoken summary
Workflow automation for local businesses is the one to try first, sir.
## Key findings
- It needs no audience. https://example.com/a
## What this means for the owner
It fits ten hours a week.
## Recommendation
Start with two paying pilots. The strongest argument against is slow sales.
## Open questions
None.
## Sources
https://example.com/a
"""


class FableTest(Base):
    """A job queued on Claude Fable 5.2 runs as a full agent, with files and tools, in a folder of its own."""

    def setUp(self):
        super().setUp()
        import knowledge
        self.vault = self.root / "vault"
        self.vault.mkdir()
        for patcher in (mock.patch.object(knowledge, "VAULT", self.vault), mock.patch("research._owner", return_value="Works ten hours a week.")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def add_research(self, request="which AI business should I start", **kwargs):
        job = self.queue.add(request, "research", model="fable", **kwargs)
        self.queue.tick()
        return job

    def test_fable_research_is_an_agent_in_its_own_folder_not_a_web_only_run(self):
        with mock.patch("research.start") as web_only:
            job = self.add_research(why="income")
        web_only.assert_not_called()
        folder = Path(job["workspace"])
        self.assertTrue(folder.is_relative_to(self.root / "builds"))
        self.assertEqual(self.sessions.models, ["fable"])
        started = self.sessions.started[0]
        self.assertEqual((started["mode"], started["fresh"], started["folder"], started["effort"]), ("work", True, str(folder), "high"))
        for expected in ("which AI business should I start", "Why they want it: income", "Works ten hours a week.", "REPORT.md",
                         "## Recommendation", "Read anywhere; write only here", "run commands", str(self.vault)):
            self.assertIn(expected, started["task"])
        self.assertIn("Started on Claude Fable 5.2", self.texts[0])
        self.assertIn("writes only there", self.texts[0])

    def test_its_report_goes_to_the_vault_and_the_summary_is_what_is_told(self):
        job = self.add_research()
        self.agent_finishes(job, report="I recommend workflow automation.", files={"REPORT.md": REPORT, "numbers.csv": "a,b\n"})
        self.assertEqual(job["status"], "done")
        note = self.vault / job["vault_note"]
        content = note.read_text(encoding="utf-8")
        self.assertIn("Claude Fable 5.2 working unattended with the web, files and tools", content)
        self.assertIn("## Recommendation", content)
        self.assertIn("not checked by Jarvis", content)
        self.assertIn("Workflow automation for local businesses is the one to try first", self.texts[-1])
        self.assertIn(job["vault_note"], self.texts[-1])
        self.assertIn("Its working files are in", self.texts[-1])
        self.assertNotIn("re-ran its tests", self.texts[-1])            # research isn't judged by tests
        self.sandbox.assert_not_called()

    def test_done_without_a_report_goes_back_then_counts_as_partial(self):
        job = self.add_research()
        self.agent_finishes(job, files={"notes.txt": "thoughts\n"})
        self.queue.tick()
        self.assertEqual(job["status"], "running")                       # sent back for the report
        self.assertIn("REPORT.md is missing", self.sessions.started[-1]["task"])
        for n in range(away_jobs.MAX_ROUNDS):
            if job["status"] != "running":
                break
            self.agent_finishes(job, files={"notes.txt": f"more {n}\n"})
            self.queue.tick()
        self.assertEqual(job["status"], "partial")
        self.assertNotIn("vault_note", job)

    def test_a_fable_build_keeps_every_step_of_the_build_pipeline(self):
        job = self.queue.add("make the widget", "build", project=str(self.repo), model="Fable 5.2")
        self.queue.tick()
        self.assertEqual(self.sessions.models, ["fable"])
        self.assertIn("You can search and read the web", self.sessions.started[0]["task"])
        self.assertIn("private copy", self.texts[0])
        self.agent_finishes(job, files={"widget.py": "x = 1\n", "tests/test_widget.py": "import unittest\n"})
        self.assertEqual(job["status"], "done")
        self.assertTrue(self.sandbox.called)                             # Jarvis still re-runs the tests himself
        self.assertIn(job["branch"], git(self.repo, "branch", "--list", job["branch"]))
        self.assertEqual(git(self.repo, "rev-parse", "--abbrev-ref", "HEAD"), "main")   # delivered as a branch, never merged

    def test_codex_stays_the_default_and_other_models_are_refused(self):
        job = self.add_build()
        self.assertEqual((job["model"], self.sessions.models), ("", [""]))
        self.assertIn("You have no web browsing tool", self.sessions.started[0]["task"])
        self.assertEqual(self.sessions.started[0]["effort"], "")
        with self.assertRaises(ValueError) as refused:
            self.queue.add("something else to build", "build", model="haiku")
        self.assertIn("Codex (leave the model blank) or on fable", str(refused.exception))

    def test_one_agent_job_at_a_time_and_stop_reaches_it(self):
        first = self.add_research()
        second = self.add_build()
        self.assertEqual((first["status"], second["status"]), ("running", "queued"))
        self.assertEqual(self.queue.stop(), 2)
        self.assertEqual(self.sessions.cancelled, [away_jobs.SESSION])

    def test_claude_codes_time_limit_message_carries_on_like_codexs(self):
        job = self.add_research()
        self.agent_finishes(job, outcome="failed", report="The task ran out of time after 30 minutes.")
        self.queue.tick()
        self.assertEqual(job["status"], "running")
        self.assertEqual(job["round"], 2)


class BuildTest(Base):
    def test_works_in_a_private_copy_and_your_project_is_untouched(self):
        (self.repo / "app.py").write_text("print('unsaved work')\n")
        job = self.add_build()
        copy = Path(job["workspace"])
        self.assertTrue(copy.is_relative_to(self.root / "builds"))
        self.assertEqual(self.sessions.started[0]["folder"], str(copy))
        self.assertTrue(self.sessions.started[0]["fresh"])
        self.assertEqual(self.sessions.started[0]["mode"], "work")
        self.assertEqual(git(copy, "remote"), "")  # git push has nowhere to go
        self.assertIn("real", (copy / "app.py").read_text())  # made from the last commit
        self.agent_finishes(job, files={"widget.py": "x = 1\n", "app.py": "print('changed')\n"})
        self.assertEqual((self.repo / "app.py").read_text(), "print('unsaved work')\n")
        self.assertEqual(git(self.repo, "rev-parse", "--abbrev-ref", "HEAD"), "main")
        self.assertFalse((self.repo / "widget.py").exists())

    def test_finished_work_comes_back_as_an_unmerged_branch(self):
        job = self.add_build()
        before = git(self.repo, "rev-parse", "main")
        self.agent_finishes(job, files={"widget.py": "x = 1\n"})
        self.assertEqual(job["status"], "done")
        self.assertEqual(git(self.repo, "rev-parse", "main"), before)
        self.assertIn("widget.py", git(self.repo, "show", "--name-only", "--format=", job["branch"]))
        self.assertEqual(git(self.repo, "log", "-1", "--format=%an", job["branch"]), "Jarvis")
        self.assertIn("not merged", self.texts[-1])

    def test_text_says_what_was_checked_and_labels_the_report_as_a_claim(self):
        job = self.add_build()
        (Path(job["workspace"]) / "tests").mkdir()
        (Path(job["workspace"]) / "tests" / "test_a.py").write_text("")
        self.agent_finishes(job, files={"widget.py": "x\n"}, report="It works perfectly.")
        self.assertIn("I re-ran its tests myself: passed (7)", self.texts[-1])
        self.assertIn("Its report (its own words): It works perfectly.", self.texts[-1])
        self.assertTrue(self.sandbox.called)

    def test_no_tests_is_never_reported_as_a_pass(self):
        job = self.add_build()
        self.agent_finishes(job, files={"widget.py": "x\n"})
        self.assertEqual(job["status"], "done")
        self.assertIn("Not independently checked", self.texts[-1])
        self.assertNotIn("passed", self.texts[-1])
        self.sandbox.assert_not_called()

    def test_saying_done_without_changing_anything_isnt_finished(self):
        job = self.add_build()
        self.agent_finishes(job, report="Done, it's all built.")
        self.assertEqual(job["status"], "partial")
        self.assertIn("changed no files", self.texts[-1])
        self.assertIn("Nothing was changed", self.texts[-1])

    def test_failing_tests_go_back_to_the_agent(self):
        job = self.add_build()
        (Path(job["workspace"]) / "tests").mkdir()
        (Path(job["workspace"]) / "tests" / "test_a.py").write_text("")
        self.sandbox.return_value = (1, "Ran 7 tests\nFAILED (failures=2): widget is wrong")
        self.agent_finishes(job, files={"widget.py": "x\n"})
        self.assertEqual(job["status"], "queued")
        self.assertIn("Sent back", self.texts[-1])
        self.queue.tick()
        self.assertEqual(len(self.sessions.started), 2)
        second = self.sessions.started[1]
        self.assertFalse(second["fresh"])  # same conversation, same folder
        self.assertIn("widget is wrong", second["task"])
        self.sandbox.return_value = (0, "Ran 7 tests\nOK")
        self.agent_finishes(job, files={"widget.py": "fixed\n"})
        self.assertEqual(job["status"], "done")

    def test_tests_still_failing_at_the_last_attempt_is_partial_not_done(self):
        job = self.add_build()
        (Path(job["workspace"]) / "tests").mkdir()
        (Path(job["workspace"]) / "tests" / "test_a.py").write_text("")
        self.sandbox.return_value = (1, "FAILED")
        for attempt in range(away_jobs.MAX_ROUNDS):
            self.agent_finishes(job, files={"widget.py": f"{attempt}\n"})
            self.queue.tick()
        self.assertEqual(job["status"], "partial")
        self.assertIn("they failed", self.texts[-1])
        self.assertEqual(len(self.sessions.started), away_jobs.MAX_ROUNDS)

    def test_tests_run_only_in_the_sandbox_with_no_fallback(self):
        self.check.stop()
        self.addCleanup(self.check.start)
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "tests").mkdir()
            (Path(folder) / "tests" / "test_a.py").write_text("")
            with mock.patch("agent_sessions.executable", return_value="codex.exe"), \
                    mock.patch("subprocess.Popen") as popen:
                popen.return_value.communicate.return_value = ("windows sandbox failed: no", None)
                popen.return_value.returncode = 1
                result = away_jobs.run_check(folder, "")
            self.assertEqual(result["state"], "none")
            self.assertIn("couldn't be run", result["detail"])
            self.assertEqual(popen.call_count, 1)
            launched = popen.call_args[0][0]
            self.assertEqual(launched[:2], ["codex.exe", "sandbox"])
            self.assertIn('sandbox_mode="workspace-write"', launched)

    def commit_a_test(self):
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "test_a.py").write_text("")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "tests")

    def test_failures_from_before_it_began_arent_blamed_on_the_agent(self):
        self.commit_a_test()
        known = "ERROR: test_dpapi (tests.test_a.T.test_dpapi)\nRan 9 tests\nFAILED (errors=1)"
        self.sandbox.return_value = (1, known)
        job = self.add_build()
        self.assertEqual(job["before"]["failures"], ["test_dpapi (tests.test_a.T.test_dpapi)"])
        self.agent_finishes(job, files={"widget.py": "x\n"})
        self.assertEqual(job["status"], "done")
        self.assertIn("passed (9), apart from 1 that already failed", self.texts[-1])

    def test_a_new_failure_beside_an_old_one_still_goes_back(self):
        self.commit_a_test()
        self.sandbox.return_value = (1, "ERROR: test_dpapi (x)\nFAILED (errors=1)")
        job = self.add_build()
        self.sandbox.return_value = (1, "ERROR: test_dpapi (x)\nFAIL: test_widget (x)\nFAILED (errors=2)")
        self.agent_finishes(job, files={"widget.py": "x\n"})
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["check"]["new_failures"], ["test_widget (x)"])

    def test_tests_broken_before_it_began_cant_be_called_a_pass(self):
        self.commit_a_test()
        self.sandbox.return_value = (1, "ImportError: no such module")
        job = self.add_build()
        self.agent_finishes(job, files={"widget.py": "x\n"})
        self.assertEqual(job["status"], "done")
        self.assertIn("Not independently checked", self.texts[-1])
        self.assertNotIn("passed", self.texts[-1])

    def test_what_a_test_run_leaves_behind_isnt_committed_as_the_agents_work(self):
        self.commit_a_test()

        def messy(command, cwd, timeout=None):
            (Path(cwd) / "junk.tmp").write_text("left by tests")
            return 0, "Ran 1 test\nOK"
        self.sandbox.side_effect = messy
        job = self.add_build()
        self.agent_finishes(job, files={"widget.py": "x\n"})
        self.assertFalse((Path(job["workspace"]) / "junk.tmp").exists())
        self.assertNotIn("junk.tmp", git(job["workspace"], "log", "--name-only", "--format="))
        self.assertIn("widget.py", git(job["workspace"], "log", "--name-only", "--format="))

    def test_partial_with_progress_continues_and_without_progress_stops(self):
        job = self.add_build()
        self.agent_finishes(job, "partial", "Got half done.", files={"a.py": "1\n"})
        self.assertEqual(job["status"], "queued")
        self.queue.tick()
        self.agent_finishes(job, "partial", "Still stuck.")
        self.assertEqual(job["status"], "partial")
        self.assertIn("stopped making progress", self.texts[-1])

    def test_a_turn_hitting_the_time_limit_carries_on(self):
        job = self.add_build()
        self.agent_finishes(job, "failed", "Codex could not finish: Codex reached the 30-minute task limit.", files={"a.py": "1\n"})
        self.assertEqual(job["status"], "queued")
        self.queue.tick()
        self.assertFalse(self.sessions.started[1]["fresh"])

    def test_blocked_stops_and_says_what_it_needs_and_the_next_job_starts(self):
        job = self.add_build()
        second = self.queue.add("second job", "build", project=str(self.repo))
        self.agent_finishes(job, "blocked", "I need you to sign in to Stripe.")
        self.assertEqual(job["status"], "blocked")
        self.assertIn("Blocked, needs you", self.texts[-1])
        self.assertIn("sign in to Stripe", self.texts[-1])
        self.queue.tick()
        self.assertEqual(second["status"], "running")

    def test_only_one_build_at_a_time(self):
        self.add_build()
        second = self.queue.add("second job", "build", project=str(self.repo))
        self.queue.tick()
        self.assertEqual(second["status"], "queued")
        self.assertEqual(len(self.sessions.started), 1)

    def test_something_new_gets_its_own_folder_and_no_repo_of_yours_is_involved(self):
        job = self.queue.add("build a landing page", "build")
        self.queue.tick()
        copy = Path(job["workspace"])
        self.assertTrue(copy.is_relative_to(self.root / "builds"))
        self.assertIn("a new empty project", self.sessions.started[0]["task"])
        self.agent_finishes(job, files={"index.html": "<h1>hi</h1>\n"})
        self.assertEqual(job["status"], "done")
        self.assertIn(str(copy), self.texts[-1])

    def test_credentials_are_left_out_of_the_commit(self):
        job = self.add_build()
        self.agent_finishes(job, files={"widget.py": "x\n", "secrets.pem": "key\n"})
        names = git(job["workspace"], "show", "--name-only", "--format=", "HEAD")
        self.assertIn("widget.py", names)
        self.assertNotIn("secrets.pem", names)
        self.assertIn("secrets.pem", self.texts[-1])

    def test_a_change_to_jarvis_safety_rules_is_called_out(self):
        job = self.add_build()
        with self.queue.lock:
            job["project"] = "Jarvis"
        self.agent_finishes(job, files={"cc_guard.py": "# weaker\n"})
        self.assertIn("safety rules (cc_guard.py)", self.texts[-1])

    def test_uncommitted_files_are_warned_about(self):
        (self.repo / "new.py").write_text("x\n")
        job = self.add_build()
        self.assertEqual(job["dirty"], 1)
        self.assertIn("uncommitted", self.texts[0])

    def test_refuses_a_project_outside_git_rather_than_work_in_the_real_folder(self):
        plain = self.root / "plain"
        plain.mkdir()
        with self.assertRaisesRegex(ValueError, "isn't in git"):
            self.queue.add("make it", "build", project=str(plain))

    def test_refuses_a_repo_with_no_commits_because_the_copy_would_be_empty(self):
        empty = self.root / "empty"
        empty.mkdir()
        git(empty, "init", "-q")
        (empty / "work.py").write_text("x\n")
        with self.assertRaisesRegex(ValueError, "never had a commit"):
            self.queue.add("make it", "build", project=str(empty))

    def test_unknown_project_and_duplicates_are_refused(self):
        with self.assertRaisesRegex(ValueError, "don't know a project"):
            self.queue.add("make it", "build", project="Nonexistent")
        self.queue.add("make the widget", "build", project=str(self.repo))
        with self.assertRaisesRegex(ValueError, "already in the queue"):
            self.queue.add("Make  the widget", "build", project=str(self.repo))

    def test_when_every_agent_slot_is_taken_it_waits(self):
        self.sessions.reply = "4 agents are already running (a, b, c, d). Wait for one to finish or stop one."
        job = self.add_build()
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["round"], 0)
        self.sessions.reply = None
        self.queue.tick()
        self.assertEqual(job["status"], "running")
        self.assertEqual(job["round"], 1)

    def test_a_refused_start_fails_honestly(self):
        self.sessions.reply = "Codex is not installed."
        job = self.add_build()
        self.assertEqual(job["status"], "failed")
        self.assertIn("Codex is not installed", self.texts[-1])

    def test_finished_build_is_saved_to_the_vault(self):
        job = self.add_build()
        self.agent_finishes(job, files={"a.py": "1\n"})
        self.assertEqual(self.archived[0][:3], ("away build", "make the widget", True))

    def test_other_sessions_reports_arent_taken(self):
        self.add_build()
        self.assertFalse(self.queue.session_done({"name": "Frontier", "ok": True, "report": "x", "outcome": "done"}))


class ProgressTest(Base):
    def test_texts_on_a_timer_with_only_what_was_observed(self):
        job = self.add_build()
        self.assertIn("Started", self.texts[0])
        count = len(self.texts)
        self.now += 19 * 60
        self.queue.tick()
        self.assertEqual(len(self.texts), count)
        self.now += 2 * 60
        self.queue.tick()
        latest = self.texts[-1]
        self.assertEqual(len(self.texts), count + 1)
        self.assertIn("21 min in", latest)
        self.assertIn("3 commands (1 failed)", latest)
        self.assertIn("2 files edited", latest)
        self.assertNotRegex(latest.lower(), r"nearly|almost|remaining|percent|%|eta")
        self.assertEqual(job["status"], "running")

    def test_says_so_when_nothing_has_happened_since_the_last_text(self):
        self.add_build()
        for _ in range(2):
            self.now += 21 * 60
            self.queue.tick()
        self.assertIn("No new commands", self.texts[-1])

    def test_progress_interval_can_be_turned_off(self):
        with mock.patch("preferences.read", return_value={"away_work": {"progress_minutes": 0}}):
            self.add_build()
            count = len(self.texts)
            self.now += 500 * 60
            self.queue.tick()
            self.assertEqual(len(self.texts), count)

    def test_a_failed_text_never_stops_the_work(self):
        self.queue.notify = mock.Mock(side_effect=OSError("offline"))
        with mock.patch.object(away_jobs, "TEXT_RETRY_SECONDS", 0):
            job = self.add_build()
            self.assertEqual(job["status"], "running")
            self.assertEqual(self.queue.notify.call_count, away_jobs.TEXT_ATTEMPTS)
            self.assertIn("Couldn't text", self.queue.describe())

    def test_status_gives_no_estimate(self):
        self.add_build()
        status = self.queue.describe()
        self.assertIn("attempt 1 of", status)
        self.assertIn("no estimate", status)


class StopAndRecoveryTest(Base):
    def test_stop_cancels_the_build_and_nothing_else_starts(self):
        job = self.add_build()
        second = self.queue.add("second job", "build", project=str(self.repo))
        self.queue.stop()
        self.assertEqual(self.sessions.cancelled, [away_jobs.SESSION])
        self.assertEqual(second["status"], "stopped")
        self.agent_finishes(job, "stopped", "Stopped, as you asked.")
        self.assertEqual(job["status"], "stopped")
        self.queue.tick()
        self.assertEqual(len(self.sessions.started), 1)

    def test_the_stop_word_during_a_build_also_holds_the_queue(self):
        job = self.add_build()
        second = self.queue.add("second job", "build", project=str(self.repo))
        self.agent_finishes(job, "stopped", "Stopped.")
        self.queue.tick()
        self.assertEqual(second["status"], "queued")
        self.queue.resume()
        self.queue.tick()
        self.assertEqual(job["status"], "running")

    def test_resume_carries_on_in_the_same_copy(self):
        job = self.add_build()
        folder = job["workspace"]
        self.agent_finishes(job, "stopped", "Stopped.", files={"a.py": "1\n"})
        self.assertEqual(self.queue.resume(), 1)
        self.queue.tick()
        self.assertEqual(job["workspace"], folder)
        self.assertFalse(self.sessions.started[-1]["fresh"])
        self.assertIn("carry on", self.sessions.started[-1]["task"])

    def test_stopped_while_the_copy_is_being_made_doesnt_start(self):
        job = self.queue.add("make the widget", "build", project=str(self.repo))
        original = self.queue._prepare

        def stop_during(target):
            original(target)
            self.queue.stop()
        with mock.patch.object(self.queue, "_prepare", stop_during):
            self.queue.tick()
        self.assertEqual(self.sessions.started, [])
        self.assertEqual(job["status"], "stopped")

    def test_a_restart_picks_up_in_the_same_copy_and_conversation(self):
        job = self.add_build()
        folder = job["workspace"]
        again = self.make_queue()
        again.recover()
        again.tick()
        revived = next(j for j in again.jobs if j["id"] == job["id"])
        self.assertEqual(revived["workspace"], folder)
        self.assertFalse(self.sessions.started[-1]["fresh"])
        self.assertIn("restarted", self.sessions.started[-1]["task"])

    def test_a_restart_loop_cant_keep_spending_the_plan(self):
        job = self.add_build()
        with self.queue.lock:
            job["round"] = away_jobs.MAX_ROUNDS + 1
            self.queue._save()
        again = self.make_queue()
        again.recover()
        self.assertEqual(again.jobs[0]["status"], "failed")

    def test_a_usage_limit_waits_an_hour_instead_of_failing(self):
        job = self.add_build()
        self.agent_finishes(job, "failed", "Codex could not finish: You've hit your usage limit.")
        self.assertEqual(job["status"], "queued")
        self.assertIn("usage limit", self.texts[-1])
        self.queue.tick()
        self.assertEqual(len(self.sessions.started), 1)
        self.now += away_jobs.RETRY_AFTER_LIMIT + 1
        self.queue.tick()
        self.assertEqual(len(self.sessions.started), 2)

    def test_stopped_from_the_panel_isnt_left_running_forever(self):
        job = self.add_build()
        self.sessions.running = False
        self.now += 1
        self.queue.tick()
        self.assertEqual(job["status"], "running")  # its report may be on the way
        self.now += away_jobs.GRACE_SECONDS + 1
        self.queue.tick()
        self.assertEqual(job["status"], "stopped")

    def test_store_survives_and_a_new_queue_reads_it(self):
        job = self.add_build()
        saved = json.loads((self.root / "jobs.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["jobs"][0]["id"], job["id"])


class BriefTest(Base):
    def finish_one(self):
        job = self.add_build()
        self.agent_finishes(job, files={"a.py": "1\n"})
        return job

    def test_says_nothing_while_youre_away(self):
        self.finish_one()
        self.queue.tick()
        self.assertEqual(self.said, [])

    def test_tells_you_once_when_youre_back(self):
        self.finish_one()
        self.idle = 5
        self.queue.tick()
        self.queue.tick()
        self.assertEqual(len(self.said), 1)
        self.assertIn("make the widget finished", self.said[0]["say"])
        self.assertIn("texted you the details", self.said[0]["say"])
        self.assertIn("own claim", self.said[0]["note"])

    def test_doesnt_claim_a_text_went_out_when_it_didnt(self):
        self.finish_one()
        self.queue.text_problem = "Telegram isn't set up."
        self.idle = 5
        self.queue.tick()
        self.assertNotIn("texted", self.said[0]["say"])


class ResearchTest(Base):
    def test_runs_with_wider_limits_and_texts_the_result(self):
        finished = {}

        def fake_start(topic, why="", on_done=None, **limits):
            finished.update(on_done=on_done, limits=limits, topic=topic, why=why)
            return {"id": "r"}
        with mock.patch("research.start", fake_start):
            job = self.queue.add("ways an AI company earns income", "research", why="the owner's goal")
            self.queue.tick()
        self.assertEqual(job["status"], "running")
        self.assertEqual(finished["limits"]["searches"], away_jobs.RESEARCH_SEARCHES)
        self.assertIn("Started researching", self.texts[-1])
        finished["on_done"]({"ok": True, "summary": "Three options look real.", "note": "Research/x.md"})
        self.assertEqual(job["status"], "done")
        self.assertIn("Three options look real", self.texts[-1])
        self.assertIn("Research/x.md", self.texts[-1])
        self.assertEqual(self.sessions.started, [])  # research never uses a build agent

    def test_a_detailed_brief_reaches_the_researcher_whole(self):
        import research
        brief = "Compare the options. " * 60 + "Finish with a ranked shortlist."
        self.assertGreater(len(brief), 1000)
        with mock.patch.object(research, "STORE", self.root / "research.json"), \
                mock.patch.object(research, "_work") as work:
            research.start(brief, background=False)
        self.assertTrue(work.call_args[0][0]["topic"].endswith("Finish with a ranked shortlist."))

    def test_failed_research_says_so(self):
        finished = {}

        def fake_start(topic, why="", on_done=None, **limits):
            finished["on_done"] = on_done
        with mock.patch("research.start", fake_start):
            job = self.queue.add("something to find", "research")
            self.queue.tick()
        finished["on_done"]({"ok": False, "summary": "It ran out of time.", "note": ""})
        self.assertEqual(job["status"], "failed")
        self.assertIn("Failed", self.texts[-1])

    def test_busy_research_waits(self):
        with mock.patch("research.start", side_effect=ValueError("2 research runs are already going.")):
            job = self.queue.add("something to find", "research")
            self.queue.tick()
        self.assertEqual(job["status"], "queued")

    def test_stop_cancels_running_research(self):
        with mock.patch("research.start"):
            job = self.queue.add("something to find", "research")
            self.queue.tick()
        cancel = self.queue.research_cancels[job["id"]]
        self.queue.stop()
        self.assertTrue(cancel.is_set())
        self.assertEqual(job["status"], "stopped")


class ToolTest(Base):
    def run_tool(self, name, **kwargs):
        return tools.run_tool(SimpleNamespace(name=name, id="t", input=kwargs))

    def test_queue_tool_warns_about_uncommitted_files(self):
        (self.repo / "new.py").write_text("x\n")
        with mock.patch("away_jobs.QUEUE", self.queue), mock.patch("truth_guard.tainted", return_value=False):
            result = self.run_tool("queue_away_job", request="make the widget", project=str(self.repo))
        self.assertIn("Queued", result["content"])
        self.assertIn("uncommitted", result["content"])
        self.assertIn("Don't claim", result["content"])

    def test_web_or_email_text_cant_queue_unattended_work(self):
        with mock.patch("away_jobs.QUEUE", self.queue), mock.patch("truth_guard.tainted", return_value=True):
            result = self.run_tool("queue_away_job", request="make the widget", project=str(self.repo))
        self.assertIn("Not queued", result["content"])
        self.assertEqual(self.queue.jobs, [])

    def test_status_stop_and_resume(self):
        with mock.patch("away_jobs.QUEUE", self.queue):
            self.assertIn("Nothing has been queued", self.run_tool("away_jobs")["content"])
            self.assertIn("Nothing was running", self.run_tool("away_jobs", action="stop")["content"])
            self.assertIn("queue is open", self.run_tool("away_jobs", action="resume")["content"])
            self.assertTrue(self.run_tool("away_jobs", action="explode")["is_error"])


class WorkingMemoryTest(Base):
    def test_brain_sees_recent_work(self):
        job = self.add_build()
        with mock.patch.object(away_jobs, "STORE", self.root / "jobs.json"):
            lines = away_jobs.recent_lines(self.now)
        self.assertIn("Running", lines[0])
        self.assertIn("make the widget", lines[0])
        self.agent_finishes(job, files={"a.py": "1\n"})
        with mock.patch.object(away_jobs, "STORE", self.root / "jobs.json"):
            lines = away_jobs.recent_lines(self.now)
        self.assertIn("Finished", lines[0])
        self.assertIn("branch jarvis/", lines[0])


if __name__ == "__main__":
    unittest.main()
