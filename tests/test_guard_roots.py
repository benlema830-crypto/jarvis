"""Phase D: terminal agents cannot approve themselves, and writes stay inside allowed roots."""
import os
from pathlib import Path
import unittest
from unittest import mock

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


class AllowedRootsTest(unittest.TestCase):
    def verdict(self, path, tool='Write'):
        return cc_guard.decide(tool, {'file_path': str(path)})

    def test_writes_outside_the_user_folder_need_approval(self):
        for path in (r'C:\Windows\System32\drivers\etc\hosts', r'C:\Program Files\App\config.ini', r'D:\backup\notes.txt'):
            self.assertEqual(self.verdict(path), ('approval', 'write outside allowed folders'), path)

    def test_sensitive_places_inside_the_user_folder_need_approval(self):
        for relative in (r'AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\run.bat', r'.ssh\authorized_keys',
                         r'.codex\config.toml', r'.claude\settings.json', r'Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1',
                         r'Documents\PowerShell\profile.ps1'):
            self.assertEqual(self.verdict(HOME / relative), ('approval', 'change startup, credential or agent settings'), relative)

    def test_ordinary_work_in_the_user_folder_is_unchanged(self):
        for relative in (r'Documents\Rocket Frontier\fresh\src\main.lua', r'Downloads\report.txt', r'Desktop\todo.md',
                         r'jarvis\semantic_search.py'):
            self.assertEqual(self.verdict(HOME / relative)[0], 'allow', relative)
        self.assertEqual(self.verdict(r'C:\Windows\win.ini', tool='Read')[0], 'allow')  # reading is not writing

    def test_traversal_cannot_escape_the_check(self):
        sneaky = str(HOME / 'Documents' / '..' / '..' / '..' / 'Windows' / 'system.ini')
        self.assertEqual(self.verdict(sneaky)[0], 'approval')
        sneaky_state = str(JARVIS / 'tests' / '..' / 'data' / 'cc_approvals.json')
        self.assertEqual(self.verdict(sneaky_state)[0], 'blocked')

    def test_codex_file_changes_inherit_the_same_rules(self):
        with mock.patch.dict(os.environ, {'JARVIS_ALLOW_OUTLOOK': '0'}):
            self.assertEqual(cc_guard.decide('Edit', {'file_path': cc_guard.APPROVALS})[0], 'blocked')


if __name__ == '__main__':
    unittest.main()
