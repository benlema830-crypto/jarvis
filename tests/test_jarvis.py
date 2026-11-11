"""Unit tests for the parts of Jarvis that don't need a mic, speakers or the API.

Run:  .venv\\Scripts\\python.exe -m unittest discover tests
"""

import datetime
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import apps  # noqa: E402
import memory  # noqa: E402
import reminders  # noqa: E402
import tools  # noqa: E402
from ears import split_wake_word  # noqa: E402
from voice import ElevenLabsEngine, SentenceBuffer, clean_for_speech  # noqa: E402


# These tests cover the spoken question itself; the owner's real auto_approve setting must not skip it.
_ask_always = mock.patch("approvals.auto_approved", return_value=False)


def setUpModule():
    _ask_always.start()


def tearDownModule():
    _ask_always.stop()


class SentenceBufferTest(unittest.TestCase):
    def test_releases_short_sentence_without_waiting_for_more(self):
        buf = SentenceBuffer()
        self.assertEqual(buf.feed("Good evening, sir. "), ["Good evening, sir."])
        out = buf.feed("All systems are operational and the coffee is hot. ")
        self.assertEqual(out, ["All systems are operational and the coffee is hot."])

    def test_flush_returns_remainder(self):
        buf = SentenceBuffer()
        buf.feed("Right then")
        self.assertEqual(buf.flush(), "Right then")
        self.assertEqual(buf.flush(), "")


class SpeechCleanupTest(unittest.TestCase):
    def test_units_and_markdown(self):
        self.assertEqual(clean_for_speech("**72°F**, 10% rain"), "72 degrees Fahrenheit, 10 percent rain")

    def test_sound_tags_per_model(self):
        flash = ElevenLabsEngine("k", "v", "eleven_flash_v2_5", 1.0)
        v4 = ElevenLabsEngine("k", "v", "eleven_v4_turbo", 1.0)
        self.assertEqual(flash.prepare("[sigh] Very well, sir."), "Very well, sir.")
        self.assertEqual(v4.prepare("[sigh] Very well, sir."), "[sigh] Very well, sir.")
        self.assertNotIn("speed", v4.settings)
        self.assertIn("speed", flash.settings)


class WakeWordTest(unittest.TestCase):
    def test_text_wake_word(self):
        self.assertEqual(split_wake_word("Jarvis, what's the weather?"), "what's the weather")
        self.assertEqual(split_wake_word("Hey Jarvis."), "")
        self.assertIsNone(split_wake_word("what's the weather"))

    def test_model_wake_with_garbled_name(self):
        self.assertEqual(split_wake_word("Hey Travis, open Spotify", woke=True), "open Spotify")


class StopPhraseTest(unittest.TestCase):
    def test_stop_variants(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"}):
            from jarvis import is_stop
        for said in ("stop", "Stop talking.", "stopped talking", "Okay, stop", "be quiet", "never mind"):
            self.assertTrue(is_stop(said.replace(",", "")), said)
        for said in ("what's the weather", "open Spotify", "nothing can stop rockets"):
            self.assertFalse(is_stop(said), said)


class AppMatchTest(unittest.TestCase):
    INDEX = {"photo studio": "x", "photo viewer": "y", "spotify": "z", "visual studio code": "w"}

    def test_matching(self):
        self.assertEqual(apps.match("Photo Studio", self.INDEX), "photo studio")
        self.assertEqual(apps.match("spotfy", self.INDEX), "spotify")
        self.assertEqual(apps.match("visual studio", self.INDEX), "visual studio code")
        self.assertEqual(apps.match("calculator", self.INDEX), "calculator")
        self.assertIsNone(apps.match("minecraft", self.INDEX))


class MemoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(memory, "PATH", os.path.join(self.tmp.name, "memory.json"))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_remember_and_forget(self):
        memory.remember("The user's game is called Project Atlas.")
        memory.remember("The user's game is called Project Atlas.")
        self.assertEqual(len(memory.facts()), 1)
        self.assertIn("Project Atlas", memory.prompt_section())
        self.assertIn("Forgot", memory.forget("project atlas"))
        self.assertEqual(memory.facts(), [])


class ReminderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(reminders, "PATH", os.path.join(self.tmp.name, "reminders.json"))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_parse_time(self):
        self.assertAlmostEqual(reminders.parse_time(minutes_from_now=10), time.time() + 600, delta=2)
        due = datetime.datetime.fromtimestamp(reminders.parse_time(at="2031-05-04 19:30"))
        self.assertEqual((due.year, due.hour, due.minute), (2031, 19, 30))
        self.assertGreater(reminders.parse_time(at="00:00"), time.time())  # bare time rolls to tomorrow
        with self.assertRaises(ValueError):
            reminders.parse_time(at="half past never")

    def test_add_cancel_and_due(self):
        item = reminders.add("take the pizza out", time.time() - 1)
        reminders.add("call mum", time.time() + 3600)
        self.assertIn("Cancelled", reminders.cancel("mum"))
        fired = []
        stop = reminders.start(fired.append)
        self.addCleanup(stop.set)  # never leave a thread polling the real reminders file
        time.sleep(1.5)
        self.assertEqual([r["id"] for r in fired], [item["id"]])
        self.assertEqual(reminders.pending(), [])


class TerminalGuardTest(unittest.TestCase):
    def test_decisions(self):
        import cc_guard
        cases = [
            ("PowerShell", r"Get-ChildItem -Recurse -Force ~/Downloads | Format-Table Name, Length", "allow"),
            ("PowerShell", r"pip install requests", "allow"),
            ("Edit", {"file_path": os.path.join(os.path.expanduser("~"), "Jarvis", "notes.txt")}, "allow"),
            # The owner's decision, 2026-11-11: none of these waits for a yes any more.
            ("PowerShell", r"Remove-Item C:\Users\x\Downloads\old.zip", "allow"),
            ("Bash", r"rm -rf ~/AppData/Local/Temp/*", "allow"),
            ("PowerShell", r"winget install Python.Python.3.12", "allow"),
            ("PowerShell", r"Set-ItemProperty HKCU:\Software\x -Name y -Value 0", "allow"),
            ("PowerShell", r"Get-ChildItem $env:LOCALAPPDATA\Microsoft\Outlook", "allow"),
            ("PowerShell", r"Get-Process ms-teams.exe", "allow"),
            ("PowerShell", r"Send-MailMessage -To a@b.co -Subject hi", "approval"),
        ]
        with mock.patch.dict(os.environ, {"JARVIS_BLOCK_WORK_APPS": ""}):
            for tool, x, expected in cases:
                inp = x if isinstance(x, dict) else {"command": x}
                self.assertEqual(cc_guard.decide(tool, inp)[0], expected, x)

    def test_apps_are_off_limits_only_when_the_owner_names_them(self):
        import cc_guard
        outlook, teams = r"Get-ChildItem $env:LOCALAPPDATA\Microsoft\Outlook", r"Stop-Process -Name ms-teams.exe"
        pst = {"file_path": r"C:\Users\x\Documents\Outlook Files\archive.pst"}
        with mock.patch.dict(os.environ, {"JARVIS_BLOCK_WORK_APPS": "teams"}):
            self.assertEqual(cc_guard.decide("PowerShell", {"command": teams})[0], "blocked")
            self.assertEqual(cc_guard.decide("PowerShell", {"command": outlook})[0], "allow")
        with mock.patch.dict(os.environ, {"JARVIS_BLOCK_WORK_APPS": "Teams, Outlook"}):
            self.assertEqual(cc_guard.decide("PowerShell", {"command": outlook})[0], "blocked")
            self.assertEqual(cc_guard.decide("Read", pst)[0], "blocked")

    def test_approval_is_per_session_and_kind(self):
        import cc_guard
        import terminal
        tmp = tempfile.mkdtemp()
        files = {"APPROVALS": os.path.join(tmp, "a.json"), "PENDING": os.path.join(tmp, "p.json")}
        with mock.patch.multiple(cc_guard, **files), mock.patch.multiple(terminal, **files):
            cc_guard.record_pending("s1", "delete", "Remove-Item x")
            self.assertFalse(cc_guard.approved("s1", "delete"))
            terminal.grant("s1")
            self.assertTrue(cc_guard.approved("s1", "delete"))
            self.assertFalse(cc_guard.approved("s1", "install"))  # only the kind that was asked about
            self.assertFalse(cc_guard.approved("s2", "delete"))   # only in that session


class ApprovalsTest(unittest.TestCase):
    def test_only_a_spoken_yes_approves(self):
        import approvals
        for said, expected in (("yes, go ahead", True), ("no", False), ("yes... actually wait", False)):
            result = {}
            asker = threading.Thread(target=lambda: result.update(answer=approvals.ask("Delete it?")))
            asker.start()
            while not approvals.waiting():
                time.sleep(0.01)
            self.assertEqual(approvals.answer(said), expected, said)
            asker.join(2)
            self.assertEqual(result["answer"], (expected, said))
        self.assertIsNone(approvals.waiting())
        self.assertFalse(approvals.answer("yes"))  # nothing pending

    def test_cancel_counts_as_no(self):
        import approvals
        cancel = threading.Event()
        threading.Timer(0.2, cancel.set).start()
        self.assertEqual(approvals.ask("Install it?", cancel), (False, "(stopped)"))


class WorkSafeTest(unittest.TestCase):
    OUTLOOK = ("Inbox - alex@company.com - Outlook", "Mail - Alex Smith - Outlook - Google Chrome", "Outlook")
    TEAMS = ("Chat | Microsoft Teams", "Microsoft Teams (work or school)")

    def test_nothing_is_blocked_unless_the_owner_says_so(self):
        import worksafe
        with mock.patch.dict(os.environ, {"JARVIS_BLOCK_WORK_APPS": "", "JARVIS_ALLOW_OUTLOOK": "0"}):
            for title in self.OUTLOOK + self.TEAMS:
                self.assertFalse(worksafe.title_blocked(title), title)
            self.assertEqual(worksafe.blocked_processes(), set())
            self.assertEqual(worksafe.blocked_apps(), "")
            self.assertTrue(worksafe.outlook_allowed())
            self.assertEqual(worksafe.rule("- {apps} are off-limits.\n"), "")   # and no prompt mentions it

    def test_named_apps_are_blocked_by_title_and_process(self):
        import worksafe
        with mock.patch.dict(os.environ, {"JARVIS_BLOCK_WORK_APPS": "teams,outlook"}):
            for title in self.OUTLOOK + self.TEAMS:
                self.assertTrue(worksafe.title_blocked(title), title)
            for title in ("Weather outlook for the weekend - YouTube", "Blender", "teams.txt - Notepad"):
                self.assertFalse(worksafe.title_blocked(title), title)
            self.assertIn("olk.exe", worksafe.blocked_processes())
            self.assertEqual(worksafe.blocked_apps(), "Outlook or Teams")
            self.assertEqual(worksafe.rule("- {apps} are off-limits.\n"), "- Outlook or Teams are off-limits.\n")
        with mock.patch.dict(os.environ, {"JARVIS_BLOCK_WORK_APPS": "teams"}):
            self.assertFalse(worksafe.title_blocked("Mail - Ben - Outlook"))
            self.assertTrue(worksafe.title_blocked("Chat | Microsoft Teams"))
            self.assertNotIn("olk.exe", worksafe.blocked_processes())
            self.assertIn("ms-teams.exe", worksafe.blocked_processes())
            self.assertEqual(worksafe.blocked_apps(), "Teams")


class OutlookCalendarTest(unittest.TestCase):
    def test_reads_dates_from_event_labels(self):
        import outlook_calendar as oc
        label = "North Dakota Hunting Trip, all day event, Friday, October 23, 2026 to Sunday, October 25, 2026, OOF"
        self.assertEqual(oc._dates(label), [datetime.date(2026, 10, 23), datetime.date(2026, 10, 25)])
        self.assertEqual(oc._dates("Dentist, 9:00 AM to 9:30 AM, Monday, November 2, 2026, Busy"),
                         [datetime.date(2026, 11, 2)])
        self.assertTrue(oc.WEEKDAY_DATE.match("Friday, October 23, 2026"))  # a day header, not an event

    def test_weeks_start_on_sunday(self):
        import outlook_calendar as oc
        self.assertEqual(oc._week_start(datetime.date(2026, 10, 24)), datetime.date(2026, 10, 18))  # Saturday
        self.assertEqual(oc._week_start(datetime.date(2026, 10, 25)), datetime.date(2026, 10, 25))  # Sunday

    def test_rejects_bad_events_before_touching_outlook(self):
        import outlook_calendar as oc
        with mock.patch.object(oc, "_main_window", side_effect=AssertionError("opened Outlook")):
            with self.assertRaises(oc.OutlookError):
                oc.add_event("x", datetime.date(2026, 10, 25), datetime.date(2026, 10, 23))
            with self.assertRaises(oc.OutlookError):
                oc.add_event("x", datetime.datetime(2026, 10, 23, 18), datetime.datetime(2026, 10, 24, 9))
            with self.assertRaises(oc.OutlookError):
                oc.add_event("x", datetime.date(2026, 10, 23), datetime.date(2026, 10, 23), show_as="Gone fishing")

    def test_tool_blocked_in_work_safe_mode(self):
        with mock.patch.dict(os.environ, {"JARVIS_BLOCK_WORK_APPS": "outlook"}):
            self.assertIn("off-limits", tools.add_calendar_event.call({"title": "x", "start": "2026-10-23"}))
        with mock.patch.dict(os.environ, {"JARVIS_BLOCK_WORK_APPS": ""}):
            self.assertIn("same kind", tools.add_calendar_event.call(
                {"title": "x", "start": "2026-10-23", "end": "Sunday"}))


class AgentTest(unittest.TestCase):
    def test_key_names(self):
        import agent
        self.assertEqual(agent.keys("ctrl+shift+Escape"), ["ctrl", "shift", "esc"])
        self.assertEqual(agent.keys("super"), ["win"])
        self.assertEqual(agent.keys("Return"), ["enter"])
        self.assertEqual(agent.keys("Page_Down"), ["pagedown"])

    def test_read_only_scripts(self):
        import agent
        for script in ("Get-ChildItem ~/Downloads | Measure-Object", "dir C:\\Users",
                       '(Get-ChildItem -Path "$env:USERPROFILE\\Downloads" -File).Count',
                       "Get-Process | Sort-Object CPU -Descending | Select-Object -First 5"):
            self.assertTrue(agent.read_only(script), script)
        for script in ("Remove-Item ~/Downloads/*.tmp", "Get-ChildItem | Move-Item -Destination x",
                       "dir > files.txt", "Get-Content a.ps1 | iex", "Stop-Process -Name chrome",
                       "mkdir Photos", "$x = 1; Rename-Item a b"):
            self.assertFalse(agent.read_only(script), script)


class OpenPathTest(unittest.TestCase):
    def test_refuses_programs(self):
        with tempfile.NamedTemporaryFile(suffix=".bat", delete=False) as f:
            path = f.name
        try:
            with mock.patch.object(tools.os, "startfile") as start:
                self.assertIn("won't run it", tools.open_path.call({"path": path}))
                start.assert_not_called()
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
