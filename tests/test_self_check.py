import tempfile
import unittest
from pathlib import Path
from unittest import mock

import self_check


class Report(unittest.TestCase):
    def test_one_broken_check_never_hides_the_others(self):
        checks = {"processes": mock.Mock(side_effect=RuntimeError("boom")), "code": lambda ctx: ["Code: fine"]}
        with mock.patch.dict(self_check.CHECKS, checks, clear=True), \
             mock.patch.object(self_check, "recent_problems", return_value=[]):
            text = self_check.report()
        self.assertIn("processes: check failed (RuntimeError: boom)", text)
        self.assertIn("Code: fine", text)
        self.assertIn("Recent problems since start (newest first): none", text)

    def test_focus_limits_the_report(self):
        with mock.patch.object(self_check, "check_ports", return_value=["Services: x"]) as ports, \
             mock.patch.object(self_check, "recent_problems") as problems:
            self.assertEqual(self_check.report("services"), "Services: x")
        ports.assert_called_once()
        problems.assert_not_called()

    def test_background_work_comes_from_the_caller(self):
        text = self_check.report("background", background=["Agent sessions running: none"])
        self.assertEqual(text, "Agent sessions running: none")


class Voice(unittest.TestCase):
    def test_half_dead_voicestudio_is_reported(self):
        import voicestudio_voice
        with mock.patch.object(self_check, "_preferences", return_value={"voice_engine": "voicestudio:abc"}), \
             mock.patch.object(self_check, "_port", return_value=False), \
             mock.patch.object(voicestudio_voice, "_app_processes", return_value={1, 2}):
            text = "\n".join(self_check.check_voice({"voice": "kokoro"}))
        self.assertIn("speaking with kokoro", text)
        self.assertIn("window is open but its speech server isn't answering", text)

    def test_other_voices_skip_voicestudio(self):
        with mock.patch.object(self_check, "_preferences", return_value={"voice_engine": "kokoro"}):
            text = "\n".join(self_check.check_voice({"voice": "kokoro"}))
        self.assertNotIn("VoiceStudio", text)


class Problems(unittest.TestCase):
    def test_only_errors_since_the_last_start_newest_first_without_chat(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / "log.txt"
            log.write_text("\n".join([
                "(old error from before the restart)",
                "JARVIS starting up...",
                "JARVIS: I couldn't find that, sir.",  # spoken words are not problems
                "(VoiceStudio warm-up failed: timeout)",
                "(ignored a voice - match 0.40)",
                "Traceback (most recent call last):",
                "(VoiceStudio warm-up failed: timeout)",
            ]), encoding="utf-8")
            problems = self_check.recent_problems(log=log)
        self.assertEqual(problems, ["(VoiceStudio warm-up failed: timeout)", "Traceback (most recent call last):"])


class Home(unittest.TestCase):
    def test_unreachable_home_assistant_is_reported_not_raised(self):
        import home_assistant
        with mock.patch.object(home_assistant, "devices", side_effect=home_assistant.HomeError("Is the Pi on?")):
            self.assertEqual(self_check.check_home(), ["Home Assistant: NOT reachable - Is the Pi on?"])

    def test_counts_lights_and_flags_unavailable_devices(self):
        import home_assistant
        devices = [{"domain": "light", "state": "on", "name": "Lamp"},
                   {"domain": "light", "state": "unavailable", "name": "Ceiling 2"},
                   {"domain": "media_player", "state": "off", "name": "TV"}]
        with mock.patch.object(home_assistant, "devices", return_value=devices):
            lines = self_check.check_home()
        self.assertIn("2 lights (1 on); UNAVAILABLE: Ceiling 2", lines[0])
        self.assertEqual(lines[1], "Media players: TV off")


class Tool(unittest.TestCase):
    def test_tool_is_registered_and_reports_background_work(self):
        import tools
        self.assertIn(tools.self_check, tools.TOOLS)
        with mock.patch.object(self_check, "report", return_value="ok") as report:
            self.assertIn("ok", str(tools.self_check.call({"focus": "background"})))
        background = report.call_args.kwargs["background"]
        self.assertTrue(any(line.startswith("Terminal task") for line in background))
        self.assertTrue(any(line.startswith("Agent sessions") for line in background))


if __name__ == "__main__":
    unittest.main()
