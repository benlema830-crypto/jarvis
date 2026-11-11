"""Terminal agents cannot approve themselves or rewrite their guard. Everywhere else is theirs to write
(the owner's decision, 2026-11-11: writes outside the user folder and in settings folders used to ask)."""
import os
from pathlib import Path
import unittest

import cc_guard

HOME = Path(os.path.expanduser('~'))
JARVIS = Path(cc_guard.HERE)


class SelfApprovalTest(unittest.TestCase):
    def test_agent_cannot_write_its_own_approval_or_guard_files(self):
        for path in (cc_guard.APPROVALS, cc_guard.PENDING, JARVIS / 'data' / 'cc_settings.json',
                     JARVIS / 'cc_guard.py', JARVIS / 'approvals.py'):
            for tool in ('Write', 'Edit', 'MultiEdit'):
                self.assertEqual(cc_guard.decide(tool, {'file_path': str(path)})[0], 'blocked', (tool, path))

    def test_shell_cannot_touch_approval_state(self):
        for command in ("Set-Content data\\cc_approvals.json '{}'", 'echo {} > data/cc_pending.json',
                        'Copy-Item x.json C:\\Users\\x\\Jarvis\\data\\cc_settings.json'):
            self.assertEqual(cc_guard.decide('PowerShell', {'command': command})[0], 'blocked', command)

    def test_reading_guard_code_is_fine(self):
        self.assertEqual(cc_guard.decide('Read', {'file_path': str(JARVIS / 'cc_guard.py')})[0], 'allow')


class WritesAnywhereTest(unittest.TestCase):
    def verdict(self, path, tool='Write'):
        return cc_guard.decide(tool, {'file_path': str(path)})

    def test_writes_outside_the_user_folder_run_without_a_question(self):
        for path in (r'C:\Windows\System32\drivers\etc\hosts', r'C:\Program Files\App\config.ini', r'D:\backup\notes.txt'):
            self.assertEqual(self.verdict(path), ('allow', ''), path)

    def test_startup_and_settings_folders_run_too(self):
        for relative in (r'AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\run.bat', r'.ssh\config',
                         r'.codex\config.toml', r'.claude\settings.json', r'Documents\PowerShell\profile.ps1'):
            self.assertEqual(self.verdict(HOME / relative), ('allow', ''), relative)

    def test_ordinary_work_in_the_user_folder_is_unchanged(self):
        for relative in (r'Documents\Rocket Frontier\fresh\src\main.lua', r'Downloads\report.txt', r'Desktop\todo.md',
                         r'jarvis\semantic_search.py'):
            self.assertEqual(self.verdict(HOME / relative)[0], 'allow', relative)
        self.assertEqual(self.verdict(r'C:\Windows\win.ini', tool='Read')[0], 'allow')

    def test_traversal_cannot_reach_the_guards_own_files(self):
        sneaky_state = str(JARVIS / 'tests' / '..' / 'data' / 'cc_approvals.json')
        self.assertEqual(self.verdict(sneaky_state)[0], 'blocked')

    def test_codex_file_changes_inherit_the_same_rules(self):
        self.assertEqual(cc_guard.decide('Edit', {'file_path': cc_guard.APPROVALS})[0], 'blocked')


if __name__ == '__main__':
    unittest.main()
