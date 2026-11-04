"""The conversation's own shell and file tools: real output, the same guard as agents, and honest results."""
import os
import queue
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import approvals
import direct_tools as direct
import hud
import tools
import truth_guard


def run(name, **args):
    return tools.run_tool(SimpleNamespace(name=name, id="t", input=args))


class DirectToolTest(unittest.TestCase):
    def setUp(self):
        truth_guard.begin_turn()
        direct.cancel.clear()
        temp = tempfile.TemporaryDirectory(dir=Path.home())  # inside the guard's allowed folder
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.file = self.root / "notes.txt"
        self.file.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
        self.prefs = mock.patch("preferences.read", return_value={"auto_approve": "routine"})
        self.prefs.start()
        self.addCleanup(self.prefs.stop)


class RunCommandTest(DirectToolTest):
    def test_returns_real_output_exit_code_and_runs_in_the_folder(self):
        result = run("run_command", command="Write-Output hello; (Get-Location).Path", folder=str(self.root))
        self.assertFalse(result.get("is_error"), result)
        self.assertIn("Exit code 0", result["content"])
        self.assertIn("hello", result["content"])
        self.assertIn(self.root.name, result["content"])

    def test_a_failing_command_reports_failure_not_success(self):
        result = run("run_command", command="Write-Output partial; exit 3")["content"]
        self.assertIn("Exit code 3", result)
        self.assertIn("partial", result)

    def test_quotes_and_special_characters_survive(self):
        result = run("run_command", command="""Write-Output "a 'b' $(1+1) é" """)["content"]
        self.assertIn("a 'b' 2 é", result)

    def test_timeout_says_it_did_not_finish(self):
        result = run("run_command", command="Write-Output started; Start-Sleep 30", timeout=1)["content"]
        self.assertIn("did NOT finish", result)
        self.assertNotIn("Exit code 0", result)

    def test_stop_ends_a_running_command(self):
        timer = threading.Timer(0.5, direct.cancel.set)
        timer.start()
        self.addCleanup(timer.cancel)
        began = time.monotonic()
        result = run("run_command", command="Start-Sleep 30", timeout=60)["content"]
        self.assertLess(time.monotonic() - began, 15)
        self.assertIn("Stopped by the user", result)

    def test_does_not_inherit_api_keys(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-secret", "HA_TOKEN": "tok-secret", "KEEP_THIS": "visible"}):
            result = run("run_command", command="Write-Output \"[$env:ANTHROPIC_API_KEY][$env:HA_TOKEN][$env:KEEP_THIS]\"")["content"]
        self.assertIn("[][][visible]", result)

    def test_off_limits_and_credentials_are_refused(self):
        for command in ("Get-Content C:\\Users\\Lemab\\Jarvis\\.env", "type data\\telegram-token.dpapi",
                        "Get-Content 'C:\\x\\Microsoft\\Teams\\a.txt'", "cat data/cc_approvals.json", "gc ~/.ssh/id_rsa"):
            result = run("run_command", command=command)
            self.assertTrue(result.get("is_error"), command)
        self.assertFalse(run("run_command", command="Write-Output '.env.example'").get("is_error"))
        self.assertFalse(run("run_command", command="Select-String credentials tools.py").get("is_error"))


class ApprovalTest(DirectToolTest):
    def setUp(self):
        super().setUp()
        self.commands = queue.Queue()
        for patcher in (mock.patch.object(hud, "commands", self.commands),
                        mock.patch.object(approvals, "on_question",
                                          lambda text: self.commands.put({"label": "Needs your OK", "say": text}))):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(lambda: approvals.answer("no") if approvals.waiting() else None)

    def in_turn(self, name, **args):
        """Run as the main loop does: a tool may never wait for an answer inside the turn."""
        result = []
        turn = threading.Thread(target=lambda: result.append(run(name, **args)))
        turn.start()
        turn.join(10)
        self.assertFalse(turn.is_alive(), "The tool blocked the turn while waiting for approval.")
        return result[0]["content"]

    def test_delete_asks_and_runs_only_after_yes(self):
        target = self.root / "gone.txt"
        target.write_text("x", encoding="utf-8")
        result = self.in_turn("run_command", command=f"Remove-Item '{target}'")
        self.assertIn("nothing has changed", result)
        self.assertTrue(target.exists())
        self.commands.get(timeout=5)
        approvals.answer("yes")
        report = self.commands.get(timeout=20)
        self.assertIn("Exit code 0", report["prompt"])
        self.assertFalse(target.exists())

    def test_delete_refused_stays_undone(self):
        target = self.root / "kept.txt"
        target.write_text("x", encoding="utf-8")
        self.in_turn("run_command", command=f"Remove-Item '{target}'")
        self.commands.get(timeout=5)
        approvals.answer("no")
        self.assertIn("Not approved", self.commands.get(timeout=5)["say"])
        self.assertTrue(target.exists())

    def test_routine_kinds_run_at_once_under_the_owner_setting(self):
        with mock.patch.object(direct, "execute", return_value="Exit code 0 in 0.1s.\ninstalled") as execute:
            result = self.in_turn("run_command", command="winget install Foo")
        self.assertIn("installed", result)
        execute.assert_called_once()
        self.assertTrue(self.commands.empty())

    def test_changes_after_reading_email_or_the_web_always_ask_but_reading_does_not(self):
        truth_guard.note_tool("read_email")
        self.assertIn("alpha", run("read_file", path=str(self.file))["content"])
        self.assertIn("Exit code", self.in_turn("run_command", command="Get-Content '" + str(self.file) + "'"))
        self.assertIn("nothing has changed", self.in_turn("edit_file", path=str(self.file), old_text="alpha", new_text="HACKED"))
        self.assertIn("alpha", self.file.read_text(encoding="utf-8"))
        self.commands.get(timeout=5)
        approvals.answer("no")
        self.commands.get(timeout=5)
        self.assertIn("nothing has changed", self.in_turn("run_command", command="python evil.py"))
        self.commands.get(timeout=5)
        approvals.answer("no")
        self.commands.get(timeout=5)

    def test_all_mode_still_asks_after_untrusted_text(self):
        with mock.patch("preferences.read", return_value={"auto_approve": "all"}):
            truth_guard.note_tool("WebFetch")
            self.assertIn("nothing has changed", self.in_turn("write_file", path=str(self.root / "x.txt"), content="y"))
            self.assertFalse((self.root / "x.txt").exists())
            self.commands.get(timeout=5)
            approvals.answer("no")
            self.commands.get(timeout=5)


class FileToolTest(DirectToolTest):
    def test_read_numbers_lines_and_pages(self):
        result = run("read_file", path=str(self.file), start_line=2, max_lines=1)["content"]
        self.assertIn("2: beta", result)
        self.assertNotIn("alpha", result)
        self.assertIn("Showing lines 2-2 of 3", result)

    def test_read_lists_folders_and_reports_missing_and_binary(self):
        self.assertIn("notes.txt", run("read_file", path=str(self.root))["content"])
        self.assertTrue(run("read_file", path=str(self.root / "nope.txt")).get("is_error"))
        (self.root / "b.dat").write_bytes(b"\0\1\2")
        self.assertIn("binary", run("read_file", path=str(self.root / "b.dat"))["content"])

    def test_secrets_cannot_be_read_written_or_searched(self):
        env = self.root / ".env"
        env.write_text("ANTHROPIC_API_KEY=sk-secret\n", encoding="utf-8")
        for path in (env, self.root / "token.dpapi", self.root / "gmail.enc"):
            self.assertTrue(run("read_file", path=str(path)).get("is_error"), path)
        self.assertTrue(run("edit_file", path=str(env), old_text="a", new_text="b").get("is_error"))
        self.assertIn("No matches", run("search_text", pattern="sk-secret", folder=str(self.root))["content"])
        (self.root / ".env.example").write_text("FOO=\n", encoding="utf-8")
        self.assertFalse(run("read_file", path=str(self.root / ".env.example")).get("is_error"))

    def test_edit_changes_one_exact_place_and_checks_it(self):
        result = run("edit_file", path=str(self.file), old_text="beta", new_text="BETA")["content"]
        self.assertIn("checked on disk", result)
        self.assertEqual(self.file.read_text(encoding="utf-8"), "alpha\nBETA\ngamma\n")

    def test_edit_keeps_windows_line_endings(self):
        self.file.write_bytes(b"one\r\ntwo\r\nthree\r\n")
        run("edit_file", path=str(self.file), old_text="one\ntwo", new_text="ONE\nTWO")
        self.assertEqual(self.file.read_bytes(), b"ONE\r\nTWO\r\nthree\r\n")

    def test_edit_refuses_missing_or_repeated_text_and_changes_nothing(self):
        before = self.file.read_text(encoding="utf-8")
        self.assertIn("nothing was changed", run("edit_file", path=str(self.file), old_text="zeta", new_text="x")["content"])
        self.file.write_text("same same", encoding="utf-8")
        self.assertIn("appears 2 times", run("edit_file", path=str(self.file), old_text="same", new_text="x")["content"])
        self.assertEqual(self.file.read_text(encoding="utf-8"), "same same")
        self.assertNotEqual(before, "")

    def test_write_creates_folders_and_will_not_overwrite_unasked(self):
        target = self.root / "new" / "deep" / "file.txt"
        self.assertIn("checked on disk", run("write_file", path=str(target), content="hi")["content"])
        self.assertEqual(target.read_text(encoding="utf-8"), "hi")
        self.assertIn("already exists", run("write_file", path=str(target), content="other")["content"])
        self.assertEqual(target.read_text(encoding="utf-8"), "hi")
        run("write_file", path=str(target), content="other", overwrite=True)
        self.assertEqual(target.read_text(encoding="utf-8"), "other")

    def test_guard_files_cannot_be_edited(self):
        import cc_guard
        guard = cc_guard.__file__
        result = run("edit_file", path=guard, old_text="RISKY", new_text="SAFE")
        self.assertTrue(result.get("is_error"))
        self.assertIn("can't be changed", result["content"])

    def test_sensitive_folders_wait_for_the_owner(self):
        target = str(Path.home() / ".ssh" / "config")
        with mock.patch.object(tools, "_after_approval", return_value="asked") as ask:
            self.assertEqual(run("write_file", path=target, content="x")["content"], "asked")
        ask.assert_called_once()
        self.assertEqual(ask.call_args.kwargs["kind"], "change startup, credential or agent settings")

    def test_search_finds_text_and_says_when_nothing_matches(self):
        result = run("search_text", pattern="GAMMA", folder=str(self.root))["content"]
        self.assertIn("notes.txt", result)
        self.assertIn("gamma", result)
        self.assertIn("No matches", run("search_text", pattern="zzzz", folder=str(self.root))["content"])
        self.assertTrue(run("search_text", pattern="(", folder=str(self.root)).get("is_error"))

    def test_python_search_fallback(self):
        with mock.patch.object(direct.shutil, "which", return_value=None):
            self.assertIn("notes.txt", run("search_text", pattern="beta", folder=str(self.root), glob="*.txt")["content"])
            self.assertIn("No matches", run("search_text", pattern="beta", folder=str(self.root), glob="*.py")["content"])


if __name__ == "__main__":
    unittest.main()
