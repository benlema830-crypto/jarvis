"""Phase D: commands that hide what they do are never auto-approved.

cc_guard's keyword rules are a secondary filter (Codex sessions also run inside the platform
sandbox), but they decide which commands Jarvis auto-accepts, so obvious obfuscation and
deletes written in Python/Node must go to the user instead."""
import unittest

import cc_guard


class GuardHardeningTest(unittest.TestCase):
    def verdict(self, command):
        return cc_guard.decide('PowerShell', {'command': command})

    def test_obfuscated_commands_need_approval(self):
        for command in ('powershell -EncodedCommand SQBFAFgAIAAoAE4AZQB3AC0ATwBiAGoAZQBjAHQAKQA=',
                        'pwsh -enc SQBFAFgAIAAoAE4AZQB3AC0ATwBiAGoAZQBjAHQAKQA=',
                        "iex ('Re'+'move-Item C:/x')",
                        "Invoke-Expression $payload",
                        '[Convert]::FromBase64String($blob) | Set-Content run.ps1'):
            self.assertEqual(self.verdict(command), ('approval', 'hidden or encoded command'), command)

    def test_deletes_written_in_scripts_need_approval(self):
        for command in ('python -c "import os; os.remove(\'notes.txt\')"',
                        'python -c "import shutil; shutil.rmtree(\'build\')"',
                        "py -c \"from pathlib import Path; Path('a.txt').unlink()\"",
                        'node -e "require(\'fs\').rmSync(\'dist\', {recursive: true})"'):
            self.assertEqual(self.verdict(command)[0], 'approval', command)

    def test_ordinary_project_work_still_runs(self):
        for command in ('python -m unittest discover -s tests', 'git status --short', 'npm test',
                        'Get-Content README.md | Select-Object -First 20', 'python scripts/memory_benchmark.py --mode offline',
                        'Select-String -Path *.py -Pattern "remove"'):
            self.assertEqual(self.verdict(command)[0], 'allow', command)


if __name__ == '__main__':
    unittest.main()
