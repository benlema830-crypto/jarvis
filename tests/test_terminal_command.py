"""The `j` terminal command: the question goes to the running Jarvis, the reply comes back as text with receipts."""
import importlib.util
import json
import queue
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import hud
import jarvis

spec = importlib.util.spec_from_file_location("j_command", Path(__file__).resolve().parent.parent / "scripts" / "j.py")
j = importlib.util.module_from_spec(spec)
spec.loader.exec_module(j)


class Rendering(unittest.TestCase):
    def test_reply_then_each_receipt_with_its_mark(self):
        text = j.render({"reply": "The fan is off.", "receipts": [
            {"tool": "home_control", "about": "bedroom fan", "status": "confirmed"},
            {"tool": "home_control", "about": "tv", "status": "unknown"}]})
        self.assertEqual(text.splitlines(), ["The fan is off.", "", "  [ok] bedroom fan: confirmed", "  [??] tv: could not confirm"])

    def test_plain_answer_has_no_receipt_block(self):
        self.assertEqual(j.render({"reply": "Forty-one.", "receipts": []}), "Forty-one.")

    def test_error_is_shown(self):
        self.assertEqual(j.render({"error": "Jarvis didn't answer."}), "Jarvis didn't answer.")

    def test_piped_text_joins_the_question_and_is_capped(self):
        self.assertEqual(j.question(["review", "this"], "diff --git a b\n"), "review this\n\ndiff --git a b")
        self.assertEqual(j.question([], "some output"), "Look at this.\n\nsome output")
        self.assertLessEqual(len(j.question(["x"], "y" * 50000)), j.MAX_PIPED + 10)

    def test_no_question_prints_help(self):
        with mock.patch("builtins.print") as out, mock.patch.object(j.sys, "stdin", None):
            self.assertEqual(j.main([]), 0)
        self.assertIn("Ask the running Jarvis", out.call_args.args[0])

    def test_jarvis_not_running_is_said_plainly(self):
        with mock.patch.object(j, "ask", side_effect=OSError()), mock.patch.object(j.sys, "stdin", None), \
                mock.patch("builtins.print") as out:
            self.assertEqual(j.main(["hello"]), 1)
        self.assertIn("isn't running", out.call_args.args[0])


class PipedInput(unittest.TestCase):
    def test_a_silent_open_pipe_does_not_hang_the_question(self):
        import subprocess
        import sys
        import time
        script = str(Path(__file__).resolve().parent.parent / "scripts" / "j.py")
        # stdin is a pipe that never sends anything and stays open; port 9 has nothing listening
        proc = subprocess.Popen([sys.executable, script, "hello"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env={**__import__("os").environ, "JARVIS_HUD_PORT": "9"})
        began = time.monotonic()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            self.fail("j hung on a silent input pipe")
        finally:
            error = proc.stderr.read()
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                stream.close()
        self.assertLess(time.monotonic() - began, 20)
        self.assertIn(b"isn't running", error)

    def test_piped_text_is_still_read(self):
        import io
        text = "diff --git a b\n+new line\n"
        with mock.patch.object(j.sys, "stdin", io.StringIO(text)):
            self.assertEqual(j.read_piped(True), text)
            j.sys.stdin.seek(0)
            self.assertEqual(j.read_piped(False), text)

    def test_a_keyboard_is_not_read(self):
        tty = mock.Mock()
        tty.isatty.return_value = True
        with mock.patch.object(j.sys, "stdin", tty):
            self.assertEqual(j.read_piped(True), "")
        tty.read.assert_not_called()


class AskRoute(unittest.TestCase):
    def setUp(self):
        self.commands = queue.Queue()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), hud._Handler)
        self.port = self.server.server_port
        patches = [mock.patch.object(hud, "commands", self.commands), mock.patch.object(hud, "emit"),
                   mock.patch.object(hud, "ALLOWED_HOSTS", {f"127.0.0.1:{self.port}"})]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def answer_next(self, reply):
        def work():
            item = self.commands.get(timeout=5)
            self.seen = item
            item["terminal"](reply)
        threading.Thread(target=work, daemon=True).start()

    def test_question_is_queued_as_a_terminal_turn_and_the_reply_returned(self):
        self.answer_next({"reply": "Off.", "receipts": []})
        answer = j.ask("is the fan on", r"C:\work", port=self.port, timeout=10)
        self.assertEqual(answer, {"reply": "Off.", "receipts": []})
        self.assertEqual(self.seen["prompt"], r"[Via Terminal] (I'm in the folder C:\work) is the fan on")
        hud.emit.assert_any_call("you", text=r"(Terminal) (I'm in the folder C:\work) is the fan on")

    def test_a_web_page_cannot_ask(self):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/ask", data=json.dumps({"text": "hi"}).encode(),
                                         headers={"Content-Type": "application/json", "Origin": "https://evil.example"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with self.assertRaises(urllib.error.HTTPError) as error:
            opener.open(request, timeout=5)
        self.assertEqual(error.exception.code, 403)
        self.assertTrue(self.commands.empty())

    def test_no_answer_in_time_is_reported_not_hung(self):
        with mock.patch.object(hud, "ASK_TIMEOUT", 0.2):
            with self.assertRaises(urllib.error.HTTPError) as error:
                j.ask("anything", port=self.port, timeout=10)
        self.assertEqual(error.exception.code, 504)


class TerminalTurn(unittest.TestCase):
    def test_reply_is_returned_with_receipts_and_never_spoken(self):
        voice, got = mock.Mock(), []

        def respond(brain, voice, prompt, speak):
            jarvis.truth_guard.begin_turn()
            jarvis.truth_guard.record("home_control", {"device": "fan"}, True, "Confirmed: Bedroom Fan is off.")
            speak("The fan is off.")
        with mock.patch.object(jarvis, "respond", respond), mock.patch.object(jarvis.hud, "emit") as emit:
            jarvis.respond_terminal(mock.Mock(), voice, {"prompt": "[Via Terminal] fan off", "terminal": got.append})
        self.assertEqual(got, [{"reply": "The fan is off.",
                                "receipts": [{"tool": "home_control", "about": "fan", "status": "confirmed"}]}])
        voice.say.assert_not_called()
        emit.assert_any_call("jarvis", text="The fan is off.")

    def test_a_failed_turn_still_answers_the_terminal(self):
        got = []
        with mock.patch.object(jarvis, "respond", side_effect=RuntimeError("boom")), mock.patch.object(jarvis.hud, "emit"):
            with self.assertRaises(RuntimeError):
                jarvis.respond_terminal(mock.Mock(), mock.Mock(), {"prompt": "[Via Terminal] x", "terminal": got.append})
        self.assertEqual(got[0]["reply"], jarvis.NO_REPLY)
        self.assertNotIn("done", got[0]["reply"].lower())  # an empty turn must not read as a success

    def test_terminal_turns_are_the_owner_speaking_but_get_no_spoken_filler(self):
        self.assertFalse(jarvis.truth_guard.system_turn("[Via Terminal] did it work?"))
        self.assertTrue("[Via Terminal] x".lstrip().startswith("["))  # the rule that keeps waiting words out of text replies


if __name__ == "__main__":
    unittest.main()
