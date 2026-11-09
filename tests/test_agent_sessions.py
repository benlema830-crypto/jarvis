import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import agent_sessions as sessions
import cc_guard
import terminal


class FakeConnection:
    calls = []
    status = "completed"
    def __init__(self, cwd, callback, cancel=None, isolate_mcp=False, unattended=False):
        FakeConnection.isolated = isolate_mcp
        FakeConnection.unattended = unattended
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
    def test_telegram_session_completion_keeps_origin_after_request_ends(self):
        import response_routing
        queue = response_routing.CommandQueue()
        self.manager.open('Frontier')
        self.manager.on_done = lambda r: queue.put({'label': 'Finished', 'say': r['report'], 'report': True})
        with mock.patch.object(sessions, 'Connection', FakeConnection):
            with response_routing.telegram_turn(101):
                self.manager.start('Research the next task', 'Frontier', 'research')
            self.manager.thread.join(timeout=5)
        self.assertFalse(self.manager.thread.is_alive())
        report = queue.get_nowait()
        self.assertEqual(report['telegram'], 101)
        self.assertIn('recommend', report['say'])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patcher = mock.patch('preferences.PATH', self.root / 'preferences.json')
        patcher.start()
        self.addCleanup(patcher.stop)
        for patch in (mock.patch.object(sessions, "STORE", self.root / "sessions.json"),
                      mock.patch.object(sessions.working_memory, "SESSIONS", self.root / "sessions.json"),
                      mock.patch.object(sessions.working_memory, "PROJECT_LOG", self.root / "project_log.jsonl"),
                      mock.patch.object(sessions.working_memory, "HANDOFFS", self.root / "handoffs"),
                      mock.patch.object(sessions.working_memory, "journal", return_value=([], [])),
                      mock.patch.object(sessions, "PROJECT", self.root),
                      mock.patch.object(sessions, "executable", return_value="codex.exe"),
                      mock.patch.object(sessions.hud, "emit")):
            patch.start()
            self.addCleanup(patch.stop)
        self.manager = sessions.SessionManager()
        FakeConnection.calls = []
        FakeConnection.status = "completed"

    def test_unattended_work_never_asks_anyone_and_says_so_to_codex(self):
        folder = self.root / "copy"
        folder.mkdir()
        self.assertEqual(self.manager.prepare_unattended("Away Builder", "Widget", folder), "")
        with mock.patch.object(sessions, "Connection", FakeConnection):
            reply = self.manager.start("Build it", "Away Builder", "work", fresh=True, folder=str(folder))
            self.assertIn("started", reply)
            self.manager.thread.join(timeout=5)
        self.assertTrue(FakeConnection.unattended)
        started = [p for m, p in FakeConnection.calls if m == "thread/start"][0]
        turn = [p for m, p in FakeConnection.calls if m == "turn/start"][0]
        self.assertEqual(started["approvalPolicy"], "never")
        self.assertEqual(turn["approvalPolicy"], "never")
        self.assertEqual(turn["sandboxPolicy"]["writableRoots"], [str(folder)])

    def test_attended_work_still_asks(self):
        self.manager.open("Frontier")
        with mock.patch.object(sessions, "Connection", FakeConnection):
            self.manager.start("Build it", "Frontier", "work")
            self.manager.thread.join(timeout=5)
        self.assertFalse(FakeConnection.unattended)
        turn = [p for m, p in FakeConnection.calls if m == "turn/start"][0]
        self.assertEqual(turn["approvalPolicy"], "untrusted")

    def test_unattended_approval_and_question_never_reach_the_speaker(self):
        folder = self.root / "copy"
        folder.mkdir()
        self.manager.prepare_unattended("Away Builder", "Widget", folder)
        worker = self.manager._begin("away builder")
        entry = self.manager.entries["away builder"]
        entry.update(status="running", thread_id="t", mode="work")
        sent = []
        worker.connection = mock.Mock(send=sent.append)
        with mock.patch.object(sessions.approvals, "ask") as ask:
            answer = worker._approval({"method": "item/commandExecution/requestApproval", "params": {"command": "dir"}})
            self.assertEqual(answer, {"decision": "decline"})
            worker._event({"id": 9, "method": "item/tool/requestUserInput",
                           "params": {"questions": [{"id": "q", "question": "Which colour?"}]}})
            ask.assert_not_called()
        said = sent[0]["result"]["answers"]["q"]["answers"][0]
        self.assertIn("owner is away", said)
        self.manager.workers.clear()

    def test_unattended_connection_has_no_web_search_or_secrets(self):
        with mock.patch.object(sessions.subprocess, "Popen") as popen,                 mock.patch.object(sessions, "isolation_args", return_value=["--disable", "apps"]),                 mock.patch.dict(sessions.os.environ, {"HOME_ASSISTANT_TOKEN": "x", "PATH": "p"}),                 mock.patch.object(sessions.threading, "Thread"):
            sessions.Connection(str(self.root), lambda event: None, unattended=True)
            command, env = popen.call_args[0][0], popen.call_args[1]["env"]
        self.assertIn('web_search="disabled"', command)
        self.assertIn("--disable", command)  # outside tools off too
        self.assertNotIn("HOME_ASSISTANT_TOKEN", env)
        self.assertIn("PATH", env)

    def test_progress_facts_only_while_running(self):
        self.manager.open("Frontier")
        self.assertIsNone(self.manager.progress_facts("Frontier"))
        worker = self.manager._begin("frontier")
        worker.seen.update(commands=4, failed_commands=1, files={"a", "b"})
        facts = self.manager.progress_facts("Frontier")
        self.assertEqual((facts["commands"], facts["failed_commands"], facts["files"]), (4, 1, 2))
        self.manager.workers.clear()

    def test_open_is_preparation_not_execution(self):
        with mock.patch.object(sessions, "Connection") as conn:
            self.assertIn("ready", self.manager.open())
            self.assertFalse(self.manager.running)
            conn.assert_not_called()
        self.assertEqual(sessions.SessionManager().snapshot()["selected"], "frontier")

    def test_pause_preserves_session_context_and_resume_inspects_existing_work(self):
        self.manager.open('Frontier')
        worker=self.manager._begin('frontier')
        entry=self.manager.entries['frontier']
        entry.update(status='running',thread_id='saved-thread',task='Fix the save path',mode='work')
        worker.connection=mock.Mock()
        worker.turn_id='turn-1'
        self.manager.control('pause','Frontier')
        self.assertTrue(worker.pause_requested.is_set())
        self.assertEqual(entry['status'],'pausing')
        worker.connection.request.assert_called_once_with('turn/interrupt',{'threadId':'saved-thread','turnId':'turn-1'})
        self.manager.workers.clear();entry['status']='paused'
        with mock.patch.object(self.manager,'start',return_value='Resuming') as start:
            self.manager.control('resume','Frontier')
        start.assert_called_once_with('Fix the save path','Frontier','work',resume=True)
        self.assertEqual(entry['thread_id'],'saved-thread')

    def test_milestones_are_real_bounded_and_snapshot_copies_nested_entries(self):
        self.manager.open('Frontier');worker=self.manager._begin('frontier')
        entry=self.manager.entries['frontier'];entry['thread_id']='ours'
        worker._event({'method':'item/started','params':{'threadId':'other','item':{'id':'wrong','type':'commandExecution','command':'private'}}})
        self.assertFalse(entry.get('timeline'))
        for i in range(70):self.manager.milestone(entry,'Running checks','finished',str(i),'python -m unittest')
        self.assertEqual(len(entry['timeline']),60)
        snap=self.manager.snapshot();snap['sessions'][0]['timeline'][0]['label']='changed'
        self.assertNotEqual(entry['timeline'][0]['label'],'changed')

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

    def test_a_worker_outliving_its_test_cannot_touch_the_real_store(self):
        """A worker that outlived its patch once wrote test sessions over the owner's real file (2026-11-04)."""
        self.manager.open()
        real = sessions.HERE / "data" / "agent_sessions.json"
        with mock.patch.object(sessions, "STORE", real):  # as it is once the test's patch has been undone
            with mock.patch.object(sessions.os, "replace") as replace:
                self.manager._save()
        self.assertNotEqual(replace.call_args.args[1], real)
        self.assertEqual(replace.call_args.args[1], self.root / "sessions.json")

    def test_saving_retries_while_something_is_reading_the_file(self):
        self.manager.open()
        with mock.patch.object(sessions.os, "replace", side_effect=[PermissionError(), PermissionError(), None]) as replace, \
             mock.patch.object(sessions.time, "sleep"):
            self.manager._save()
        self.assertEqual(replace.call_count, 3)

    def test_a_running_session_cannot_start_twice(self):
        self.manager.open()
        self.manager._begin("frontier")
        self.assertIn("still working", self.manager.start("another task"))

    def other_project(self, name="Second"):
        """A second session in its own folder."""
        folder = self.root / name
        folder.mkdir()
        self.manager.entries[name.casefold()] = {"name": name, "project": name, "cwd": str(folder), "provider": "codex",
                                                 "thread_id": None, "status": "ready", "task": ""}

    def test_different_projects_run_at_once(self):
        self.manager.open()
        self.other_project()
        release = threading.Event()
        done = []
        self.manager.on_done = done.append

        class Slow(FakeConnection):
            def receive(self):
                release.wait(5)
                return next(self.events)
        with mock.patch.object(sessions, "Connection", Slow):
            self.assertIn("started", self.manager.start("Build the rocket", "Frontier", "work"))
            first = self.manager.thread
            self.assertIn("started", self.manager.start("Build the other thing", "Second", "work"))
            second = self.manager.thread
            self.assertEqual(set(self.manager.workers), {"frontier", "second"})
            release.set()
            first.join(5), second.join(5)
        self.assertFalse(self.manager.running)
        self.assertEqual({d["name"] for d in done}, {"Frontier", "Second"})
        self.assertEqual(self.manager.entries["frontier"]["status"], "completed")
        self.assertEqual(self.manager.entries["second"]["status"], "completed")

    def test_two_writers_in_one_folder_are_refused_but_readers_are_not(self):
        self.manager.open()
        same = dict(self.manager.entries["frontier"], name="Other")
        self.manager.entries["other"] = same
        self.manager._begin("frontier")
        self.manager.entries["frontier"]["mode"] = "work"
        refused = self.manager.start("edit things", "Other", "work")
        self.assertIn("overwrite", refused)
        self.assertIn("Frontier", refused)
        self.assertNotIn("other", self.manager.workers)
        with mock.patch.object(sessions, "Connection", FakeConnection):
            self.assertIn("started", self.manager.start("just look", "Other", "research"))
            self.manager.thread.join(3)

    def test_there_is_a_limit_on_running_agents(self):
        self.manager.open()
        for i in range(sessions.MAX_WORKERS):
            self.other_project(f"Busy {i}")
            self.manager._begin(f"busy {i}")
            self.manager.entries[f"busy {i}"]["mode"] = "research"
        self.assertIn("already running", self.manager.start("one more", "Frontier"))

    def test_stop_by_name_leaves_the_others_running_and_blank_stops_all(self):
        self.manager.open()
        self.other_project()
        first, second = self.manager._begin("frontier"), self.manager._begin("second")
        self.manager.cancel("Second")
        self.assertFalse(first.cancelled.is_set())
        self.assertTrue(second.cancelled.is_set())
        self.manager.cancel()
        self.assertTrue(first.cancelled.is_set())

    def steering(self, reply):
        self.manager.open()
        worker = self.manager._begin("frontier")
        self.manager.entries["frontier"].update(thread_id="t1", mode="work", status="running")
        worker.turn_id = "turn-1"
        conn = worker.connection = mock.Mock()

        def request(method, params):
            self.assertEqual(method, "turn/steer")
            self.assertEqual((params["threadId"], params["expectedTurnId"]), ("t1", "turn-1"))
            worker._event({"id": 7, **reply})  # the reply arrives on the worker's own loop
            return 7
        conn.request.side_effect = request
        return worker, conn

    def test_a_message_reaches_a_running_agent_without_stopping_it(self):
        worker, conn = self.steering({"result": {"turnId": "turn-1"}})
        result = self.manager.message("the chair should stay", "Frontier")
        self.assertIn("Delivered", result)
        self.assertFalse(worker.cancelled.is_set())
        self.assertIn("frontier", self.manager.workers)
        self.assertIn("the chair should stay", conn.request.call_args.args[1]["input"][0]["text"])

    def test_a_refused_message_is_not_reported_as_delivered(self):
        self.steering({"error": {"message": "turn already finished"}})
        result = self.manager.message("too late", "Frontier")
        self.assertNotIn("Delivered", result)
        self.assertIn("turn already finished", result)

    def test_message_to_an_idle_session_says_nothing_was_delivered(self):
        self.manager.open()
        self.assertIn("nothing was delivered", self.manager.message("hello", "Frontier"))

    def test_message_with_several_running_asks_which(self):
        self.manager.open()
        self.other_project()
        self.manager._begin("frontier"), self.manager._begin("second")
        self.assertIn("Say which", self.manager.message("hello"))

    def test_claude_sessions_admit_they_cannot_take_a_message(self):
        self.manager.open()
        self.manager.entries["frontier"]["provider"] = "claude"
        self.manager._begin("frontier")
        self.assertIn("Nothing was delivered", self.manager.message("hello", "Frontier"))

    def finish_with(self, report):
        class Reporting(FakeConnection):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.events = iter([
                    {"method": "item/completed", "params": {"item": {"id": "a", "type": "agentMessage", "phase": "final_answer", "text": report}}},
                    {"method": "turn/completed", "params": {"turn": {"id": "turn-1", "status": "completed"}}}])
        self.manager.open()
        done = self.manager.on_done = mock.Mock()
        with mock.patch.object(sessions, "Connection", Reporting):
            self.manager.start("Fix it", mode="work")
            self.manager.thread.join(3)
        return done.call_args.args[0], self.manager.entries["frontier"]

    def test_an_agent_that_says_it_was_blocked_is_not_recorded_as_finished(self):
        result, entry = self.finish_with("Studio isn't open, so I changed nothing.\n\nOUTCOME: blocked")
        self.assertFalse(result["ok"])
        self.assertEqual(result["outcome"], "blocked")
        self.assertEqual(entry["status"], "failed")
        self.assertEqual(result["report"], "Studio isn't open, so I changed nothing.")  # the line isn't read aloud
        log = json.loads((self.root / "project_log.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertFalse(log["ok"])

    def test_done_is_finished_and_partial_is_not(self):
        result, entry = self.finish_with("All of it works.\nOUTCOME: done")
        self.assertTrue(result["ok"])
        self.assertEqual(entry["status"], "completed")
        self.manager = sessions.SessionManager()
        result, _ = self.finish_with("Half of it works.\nOUTCOME: partial")
        self.assertFalse(result["ok"])
        self.assertEqual(result["outcome"], "partial")

    def test_being_blocked_does_not_teach_that_the_task_was_hard(self):
        with mock.patch.object(sessions.task_effort, "record") as record:
            self.finish_with("Studio isn't open.\nOUTCOME: blocked")
        self.assertTrue(record.call_args.args[3])  # the turn ran to its end

    def test_evidence_is_what_jarvis_watched_not_what_the_agent_said(self):
        self.manager.open()
        worker = self.manager._begin("frontier")
        self.manager.entries["frontier"].update(thread_id="t", mode="work")
        for item in ({"id": "1", "type": "commandExecution", "command": "dir", "exitCode": 0},
                     {"id": "2", "type": "commandExecution", "command": "python -m unittest", "exitCode": 1},
                     {"id": "3", "type": "fileChange", "changes": [{"path": str(self.root / "a.py")}]},
                     {"id": "4", "type": "mcpToolCall", "tool": "execute_luau"}):
            worker._event({"method": "item/completed", "params": {"item": item}})
        line = worker.evidence("work")
        self.assertIn("2 commands (1 failed)", line)
        self.assertIn("1 file changed", line)
        self.assertIn("1 test or build run (1 failed)", line)
        self.assertIn("1 connected-tool", line)

    def test_claimed_work_with_nothing_observed_is_flagged(self):
        self.manager.open()
        worker = self.manager._begin("frontier")
        self.assertIn("did no recorded work", worker.evidence("work"))
        self.assertNotIn("did no recorded work", worker.evidence("research"))

    def test_changed_files_do_not_carry_over_to_the_next_task(self):
        result, entry = self.finish_with("ok")
        entry["changed_files"] = ["old.py"]
        with mock.patch.object(sessions, "Connection", FakeConnection):
            self.manager.start("New task", "Frontier", "work")
            self.assertEqual(entry["changed_files"], [])
            self.manager.thread.join(3)

    def test_status_is_small_and_never_implies_an_estimate(self):
        self.manager.open()
        self.manager._begin("frontier")
        entry = self.manager.entries["frontier"]
        entry.update(status="running", mode="work", task="Build it", progress="Running tests")
        for i in range(60):
            self.manager.milestone(entry, "Running command", "finished", str(i), "x" * 2000)
        text = self.manager.status("Frontier")
        self.assertLess(len(text), 1500)
        self.assertIn("no estimate", text)
        self.assertIn("Running tests", text)

    def test_overview_stays_small_however_long_the_history(self):
        self.manager.open()
        entry = self.manager.entries["frontier"]
        entry.update(task="t" * 5000, report="r" * 5000, status="completed", outcome="blocked", evidence="seen")
        for i in range(60):
            self.manager.milestone(entry, "Step", "finished", str(i), "x" * 2000)
        text = self.manager.overview()
        self.assertLess(len(text), 600)
        self.assertIn("outcome blocked", text)

    def test_a_fresh_task_starts_a_new_conversation_and_can_use_another_folder(self):
        self.manager.open()
        self.manager.entries["frontier"]["thread_id"] = "old-thread"
        folder = self.root / "elsewhere"
        folder.mkdir()
        FakeConnection.calls = []
        with mock.patch.object(sessions, "Connection", FakeConnection), \
             mock.patch.dict(sessions.project_catalog.PROJECTS, {"Rocket Frontier": self.root}):
            self.manager.start("Unrelated job", "Frontier", "work", fresh=True, folder=str(folder))
            self.manager.thread.join(3)
            self.assertIn("thread/start", [m for m, _ in FakeConnection.calls])
            self.assertEqual(self.manager.entries["frontier"]["cwd"], str(folder))
            self.assertIn("No such folder", self.manager.start("x", "Frontier", "work", fresh=True, folder=str(folder / "nope")))
            self.assertIn("fresh", self.manager.start("x", "Frontier", "work", folder=str(folder)))
            self.manager.start("Back home", "Frontier", "work", fresh=True)
            self.manager.thread.join(3)
        self.assertEqual(self.manager.entries["frontier"]["cwd"], str(self.root))

    def test_real_questions_get_the_owners_words_not_an_automatic_yes(self):
        self.prepare_approval()
        worker = self.worker
        worker.connection = mock.Mock()
        event = {"id": 1, "method": "item/tool/requestUserInput", "params": {"questions": [{"id": "q", "question": "Which color?"}]}}
        with mock.patch.object(sessions.approvals, "ask", return_value=(True, "the red one")) as ask:
            worker._event(event)
        self.assertTrue(ask.call_args.kwargs["free_text"])
        sent = worker.connection.send.call_args.args[0]
        self.assertEqual(sent["result"]["answers"]["q"]["answers"], ["the red one"])

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
        self.manager.open()
        worker = self.manager._begin("frontier")
        worker.claude_worker = mock.Mock()
        self.manager.cancel()
        worker.claude_worker.cancel.assert_called_once()

    def test_child_agent_completion_cannot_finish_parent_task(self):
        self.prepare_approval()
        self.manager.entries["frontier"]["thread_id"] = "parent"
        self.worker.turn_id = "parent-turn"
        self.worker._event({"method": "turn/started", "params": {"threadId": "child", "turn": {"id": "child-turn"}}})
        self.worker._event({"method": "turn/completed", "params": {"threadId": "child", "turn": {"status": "completed"}}})
        self.assertEqual(self.worker.turn_id, "parent-turn")
        self.assertIsNone(self.worker._complete)

    def prepare_approval(self, mode="work"):
        self.manager.open()
        self.worker = self.manager._begin("frontier")
        self.manager.entries["frontier"]["mode"] = mode

    def approve_command(self, command, **params):
        return self.worker._approval({"method": "item/commandExecution/requestApproval", "params": {"command": command, **params}})

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
        self.worker._items["edit"] = {"changes": [{"path": str(self.root / "file.txt"), "kind": {"type": "update"}}]}
        event = {"method": "item/fileChange/requestApproval", "params": {"itemId": "edit"}}
        with mock.patch.object(sessions.approvals, "ask") as ask:
            self.assertEqual(self.worker._approval(event), {"decision": "accept"})
            ask.assert_not_called()
        self.worker._items["edit"]["changes"][0]["kind"]["type"] = "delete"
        with mock.patch.object(sessions.approvals, "ask", return_value=(False, "no")):
            self.assertEqual(self.worker._approval(event), {"decision": "decline"})

    def test_work_mode_matches_claude_bypass(self):
        self.prepare_approval()
        with mock.patch.object(sessions.approvals, "ask") as ask:
            self.assertEqual(self.approve_command("pip install requests", networkApprovalContext={"host": "pypi.org"},
                                                  additionalPermissions={"network": {"enabled": True}}), {"decision": "accept"})
            self.worker._items["edit"] = {"changes": [{"path": str(Path.home() / "Documents" / "notes.txt"), "kind": {"type": "add"}}]}
            event = {"method": "item/fileChange/requestApproval", "params": {"itemId": "edit"}}
            self.assertEqual(self.worker._approval(event), {"decision": "accept"})
            grant = {"network": {"enabled": True}, "fileSystem": {"write": [str(Path.home() / "Documents")]}}
            event = {"method": "item/permissions/requestApproval", "params": {"permissions": grant}}
            self.assertEqual(self.worker._approval(event), {"permissions": grant, "scope": "turn"})
            ask.assert_not_called()

    def test_sensitive_writes_still_ask(self):
        self.prepare_approval()
        self.worker._items["edit"] = {"changes": [{"path": str(Path.home() / ".ssh" / "config"), "kind": {"type": "update"}}]}
        event = {"method": "item/fileChange/requestApproval", "params": {"itemId": "edit"}}
        with mock.patch.object(sessions.approvals, "ask", return_value=(False, "no")) as ask:
            self.assertEqual(self.worker._approval(event), {"decision": "decline"})
            grant = {"fileSystem": {"entries": [{"access": "write", "path": {"type": "special", "value": {"kind": "root"}}}]}}
            event = {"method": "item/permissions/requestApproval", "params": {"permissions": grant}}
            self.assertEqual(self.worker._approval(event), {"permissions": {}, "scope": "turn"})
            self.assertEqual(ask.call_count, 2)

    def test_codex_changes_to_guard_files_are_undone(self):
        import os
        rules, records = self.root / "cc_guard.py", self.root / "cc_approvals.json"
        rules.write_text("RULES", encoding="utf-8")
        records.write_text("{}", encoding="utf-8")
        protected = {os.path.normcase(os.path.realpath(p)) for p in (rules, records)}
        with mock.patch.object(sessions.cc_guard, "PROTECTED", protected):
            self.prepare_approval()
            self.worker._protected, self.worker._tampered = sessions.protected_snapshot(self.root), set()
            records.write_text('{"claude": "approved by the user"}', encoding="utf-8")  # a Claude task's own write
            rules.write_text("weakened", encoding="utf-8")
            self.worker._guard_protected({"changes": []})
            self.assertEqual(rules.read_text(encoding="utf-8"), "RULES")
            self.assertIn("claude", records.read_text(encoding="utf-8"))
            records.write_text('{"self": "granted"}', encoding="utf-8")
            self.worker._guard_protected({"changes": [{"path": str(records)}]})
            self.assertEqual(records.read_text(encoding="utf-8"), "{}")
            self.assertEqual(self.worker._tampered, {"cc_guard.py", "cc_approvals.json"})

    def test_cancelled_approval_cannot_proceed(self):
        self.prepare_approval()
        self.worker.cancelled.set()
        self.assertEqual(self.approve_command("python test.py"), {"decision": "decline"})

    def test_stale_running_status_not_restored_as_live(self):
        self.manager.open()
        self.manager.entries["frontier"]["status"] = "running"
        self.manager._save()
        self.assertEqual(sessions.SessionManager().snapshot()["sessions"][0]["status"], "interrupted")

    def test_cancel_sends_correct_turn_and_thread(self):
        self.prepare_approval()
        self.manager.entries["frontier"]["thread_id"] = "thread1"
        self.worker.turn_id = "turn1"
        conn = self.worker.connection = mock.Mock()
        self.manager.cancel()
        conn.request.assert_called_once_with("turn/interrupt", {"threadId": "thread1", "turnId": "turn1"})

    def test_tasks_get_project_context_and_record_results(self):
        FakeConnection.calls = []
        self.manager.open()
        with mock.patch.object(sessions, "Connection", FakeConnection):
            self.manager.start("Find next task")
            self.manager.thread.join(3)
            first = next(p for m, p in FakeConnection.calls if m == "turn/start")["input"][0]["text"]
            self.assertNotIn("Context from Jarvis", first)  # nothing recorded yet
            FakeConnection.calls = []
            self.manager.start("Find the task after that")
            self.manager.thread.join(3)
        second = next(p for m, p in FakeConnection.calls if m == "turn/start")["input"][0]["text"]
        self.assertIn("Context from Jarvis", second)
        self.assertIn("I recommend fixing the save flow next.", second)  # the previous result
        self.assertIn("User request:\nFind the task after that", second)
        log = (self.root / "project_log.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(log), 2)
        self.assertEqual(json.loads(log[0])["project"], "Rocket Frontier")

    def test_searching_for_risky_words_is_not_risky(self):
        for command in ('rg -n "Remove-Item|shutdown" tools.py', 'Select-String -Pattern "Restart-Service" *.py',
                        'git log --grep "rm "', 'git branch -a'):
            self.assertEqual(cc_guard.decide("PowerShell", {"command": command}), ("allow", ""), command)
        for command in ('Get-ChildItem | Remove-Item', 'rg -n shutdown > out.txt', 'git branch -D old',
                        'Get-Content x; shutdown /r', 'cat a.txt && rm a.txt'):
            self.assertEqual(cc_guard.decide("PowerShell", {"command": command})[0] != "allow"
                             or not cc_guard.plain_read_command(command), True, command)
        self.assertEqual(cc_guard.decide("Bash", {"command": "rm -rf build"}), ("approval", "delete"))
        self.assertEqual(cc_guard.decide("Bash", {"command": "cat data/cc_approvals.json"})[0], "blocked")

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
