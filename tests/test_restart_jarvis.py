import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import restart_jarvis  # noqa: E402


class IsJarvisProcess(unittest.TestCase):
    def test_matches_own_scripts_in_this_folder(self):
        py = r"C:\Python312\python.exe"
        for script in ("jarvis.py", "brain.py", "spotify_mcp.py"):
            self.assertTrue(restart_jarvis.is_jarvis_process([py, "-u", str(ROOT / script), "--no-window"]))
        self.assertTrue(restart_jarvis.is_jarvis_process([r"C:\x\pythonw.exe", str(ROOT / "brain.py")]))

    def test_ignores_other_folders_and_programs(self):
        self.assertFalse(restart_jarvis.is_jarvis_process([r"C:\Python312\python.exe", r"C:\elsewhere\jarvis.py"]))
        self.assertFalse(restart_jarvis.is_jarvis_process([r"C:\x\code.exe", str(ROOT / "jarvis.py")]))
        self.assertFalse(restart_jarvis.is_jarvis_process([r"C:\Python312\python.exe", str(ROOT / "scripts" / "restart_jarvis.py")]))
        self.assertFalse(restart_jarvis.is_jarvis_process([]))
        self.assertFalse(restart_jarvis.is_jarvis_process(None))


class Stop(unittest.TestCase):
    def test_keeps_apps_jarvis_opened_but_stops_jarvis_workers(self):
        def proc(pid, name, children=()):
            p = mock.Mock(pid=pid)
            p.name.return_value = name
            p.children.return_value = list(children)
            return p
        server = proc(13, 'python.exe')        # VoiceStudio's speech server, under VoiceStudio.exe
        studio = proc(12, 'VoiceStudio.exe', [server])
        crash = proc(15, 'RobloxCrashHandler.exe')
        roblox = proc(14, 'RobloxStudioBeta.exe', [crash])  # unsaved game work: never close it
        worker = proc(11, 'codex.exe')
        shell = proc(16, 'conhost.exe')
        jarvis = proc(10, 'python.exe', [worker, shell, studio, server, roblox, crash])
        with mock.patch.object(restart_jarvis, 'jarvis_processes', return_value=[jarvis]), \
             mock.patch.object(restart_jarvis, '_name', return_value='x'), \
             mock.patch.object(restart_jarvis.psutil, 'wait_procs', return_value=([], [])), \
             mock.patch.object(restart_jarvis, 'port_open', return_value=False), \
             mock.patch.object(restart_jarvis, 'log'):
            restart_jarvis.stop_jarvis()
        jarvis.terminate.assert_called_once()
        worker.terminate.assert_called_once()
        studio.terminate.assert_not_called()
        server.terminate.assert_not_called()
        shell.terminate.assert_called_once()
        roblox.terminate.assert_not_called()
        crash.terminate.assert_not_called()


class Main(unittest.TestCase):
    def test_refuses_to_start_a_second_copy(self):
        with mock.patch.object(restart_jarvis, "stop_jarvis"), \
             mock.patch.object(restart_jarvis, "jarvis_processes", return_value=[object()]), \
             mock.patch.object(restart_jarvis, "start_jarvis") as start, \
             mock.patch.object(restart_jarvis, "message_box"), \
             mock.patch.object(restart_jarvis, "log"):
            self.assertEqual(restart_jarvis.main([]), 1)
            start.assert_not_called()

    def test_restarts_quietly_by_default(self):
        with mock.patch.object(restart_jarvis, "stop_jarvis"), \
             mock.patch.object(restart_jarvis, "jarvis_processes", return_value=[]), \
             mock.patch.object(restart_jarvis, "repair_voicestudio"), \
             mock.patch.object(restart_jarvis, "start_jarvis") as start, \
             mock.patch.object(restart_jarvis, "wait_until_up", return_value=True), \
             mock.patch.object(restart_jarvis, "log"):
            self.assertEqual(restart_jarvis.main([]), 0)
            start.assert_called_once_with(quiet=True)


class StuckVoiceStudio(unittest.TestCase):
    def _procs(self, age):
        proc = mock.Mock(info={"exe": str(__import__("voicestudio_voice").APP), "create_time": time.time() - age})
        return [proc]

    def test_closes_app_whose_server_died_long_ago(self):
        import voicestudio_voice as vs
        procs = self._procs(age=600)
        with mock.patch("psutil.process_iter", return_value=procs), mock.patch("psutil.wait_procs"):
            self.assertTrue(vs._close_if_stuck())
        procs[0].terminate.assert_called_once()

    def test_leaves_app_that_is_still_starting(self):
        import voicestudio_voice as vs
        procs = self._procs(age=10)
        with mock.patch("psutil.process_iter", return_value=procs):
            self.assertFalse(vs._close_if_stuck())
        procs[0].terminate.assert_not_called()


class Tool(unittest.TestCase):
    def test_tool_launches_detached_restarter(self):
        import tools
        with mock.patch.object(tools.subprocess, "Popen") as popen:
            text = tools.restart_jarvis.call({})
        args = popen.call_args[0][0]
        self.assertTrue(args[0].endswith("pythonw.exe"))
        self.assertTrue(args[1].endswith("restart_jarvis.py"))
        self.assertIn("--delay", args)
        self.assertIn("Restarting", str(text))
        self.assertIn(tools.restart_jarvis, tools.TOOLS)


if __name__ == "__main__":
    unittest.main()
