import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app_audio
import direct_files
import window_control as wc


class FilesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patch = mock.patch.object(direct_files, "ROOTS", (self.root,))
        patch.start()
        self.addCleanup(patch.stop)

    def test_create_list_copy_rename_roundtrip(self):
        folder = self.root / "new"
        direct_files.operate("create_folder", str(folder))
        source = folder / "first.txt"
        source.write_bytes(b"test content\x00")
        copy = folder / "copy.txt"
        direct_files.operate("copy_file", str(source), str(copy))
        renamed = folder / "renamed.txt"
        direct_files.operate("rename", str(copy), str(renamed))
        self.assertEqual(renamed.read_bytes(), source.read_bytes())
        self.assertFalse(copy.exists())
        self.assertIn("renamed.txt", direct_files.operate("list", str(folder)))

    def test_copy_and_rename_never_overwrite(self):
        a, b = self.root / "a", self.root / "b"
        a.write_text("first")
        b.write_text("second")
        for action in ("copy_file", "rename"):
            with self.assertRaises(FileExistsError):
                direct_files.operate(action, str(a), str(b))
        self.assertEqual(a.read_text(), "first")
        self.assertEqual(b.read_text(), "second")

    def test_refuses_escape_and_root_rename(self):
        with self.assertRaises(ValueError):
            direct_files.checked(str(self.root / ".." / "escape.txt"))
        with self.assertRaises(ValueError):
            direct_files.operate("rename", str(self.root), str(self.root / "renamed"))
        with self.assertRaises(ValueError):
            direct_files.checked(str(self.root / ".git" / "config"))

    def test_off_limits_and_unsupported_actions(self):
        with mock.patch.dict("os.environ", {"JARVIS_ALLOW_OUTLOOK": "0"}):
            with self.assertRaises(ValueError):
                direct_files.checked(str(self.root / "mail.pst"))
        with self.assertRaises(ValueError):
            direct_files.operate("delete", str(self.root))


class AudioTest(unittest.TestCase):
    def setUp(self):
        for method in ("CoInitialize", "CoUninitialize"):
            patch = mock.patch.object(app_audio.comtypes, method)
            patch.start()
            self.addCleanup(patch.stop)

    def session(self, name):
        session = mock.Mock()
        session.Process.name.return_value = name
        return session

    def test_targeted_volume_does_not_change_other_apps_or_mute_state(self):
        a, b = self.session("Spotify.exe"), self.session("RobloxPlayerBeta.exe")
        a.SimpleAudioVolume.GetMasterVolume.return_value = .25
        with mock.patch.object(app_audio.AudioUtilities, "GetAllSessions", return_value=[a, b]):
            self.assertIn("25%", app_audio.control("volume", "Spotify", 25))
        a.SimpleAudioVolume.SetMasterVolume.assert_called_once_with(.25, None)
        a.SimpleAudioVolume.SetMute.assert_not_called()
        b.SimpleAudioVolume.SetMasterVolume.assert_not_called()

    def test_mute_applies_to_all_sessions_of_matched_app(self):
        items = [self.session("Spotify.exe"), self.session("Spotify.exe")]
        for item in items:
            item.SimpleAudioVolume.GetMute.return_value = 1
        with mock.patch.object(app_audio.AudioUtilities, "GetAllSessions", return_value=items):
            app_audio.control("mute", "Spotify")
        for item in items:
            item.SimpleAudioVolume.SetMute.assert_called_once_with(True, None)

    def test_ambiguous_audio_target_is_not_modified(self):
        items = [self.session("RobloxPlayerBeta.exe"), self.session("RobloxStudioBeta.exe")]
        with mock.patch.object(app_audio.AudioUtilities, "GetAllSessions", return_value=items):
            with self.assertRaises(ValueError):
                app_audio.control("mute", "Roblox")
        for item in items:
            item.SimpleAudioVolume.SetMute.assert_not_called()

    def test_bad_volume_rejected_before_com(self):
        with self.assertRaises(ValueError):
            app_audio.control("volume", "Spotify", 101)
        app_audio.comtypes.CoInitialize.assert_not_called()


class DirectWindowTest(unittest.TestCase):
    def test_snap_partitions_work_area_on_negative_monitor(self):
        work = (-2561, -100, 0, 1300)
        left = wc.placement("snap_left", (), work)
        right = wc.placement("snap_right", (), work)
        self.assertEqual(left[0] + left[2], right[0])
        self.assertEqual(right[0] + right[2], 0)
        self.assertEqual(left[3], 1400)

    def test_fast_parser_leaves_compound_and_conditional_commands_to_ai(self):
        self.assertEqual(wc.quick_action("Can you maximize Roblox Studio, please?"), ("control_app_window", {"app": "Roblox Studio", "action": "maximize"}))
        self.assertEqual(wc.quick_action("Move Roblox Studio to my second monitor")[1]["monitor"], "second")
        for text in ("maximize Roblox Studio then open Notepad", "minimize Chrome if Spotify is open", "how do I maximize Roblox Studio?"):
            self.assertIsNone(wc.quick_action(text))

    def test_close_requests_normal_close_and_does_not_claim_closed_on_save_prompt(self):
        item = {"id": 10, "title": "Test editor", "process": "test.exe"}
        with mock.patch.object(wc, "windows", return_value=[item]), \
             mock.patch.object(wc.win32gui, "GetForegroundWindow", return_value=10), \
             mock.patch.object(wc.win32gui, "IsWindow", return_value=True), \
             mock.patch.object(wc.worksafe, "is_blocked", return_value=False), \
             mock.patch.object(wc.win32gui, "PostMessage") as post, \
             mock.patch.object(wc.time, "sleep"):
            report = wc.control("Test editor", "close")
        post.assert_called_once_with(10, wc.win32con.WM_CLOSE, 0, 0)
        self.assertIn("still open", report)
        self.assertNotIn("closed.", report)

    def test_invalid_action_never_touches_windows(self):
        with mock.patch.object(wc, "windows") as windows:
            with self.assertRaises(ValueError):
                wc.control("Test", "force_kill")
            windows.assert_not_called()
