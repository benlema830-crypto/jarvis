"""What cc_guard pauses and what it lets run. Since 2026-11-11 (the owner: "there should be little to no
rules") only a command that messages other people waits; encoded commands and deletes run."""
import unittest

import cc_guard


class GuardHardeningTest(unittest.TestCase):
    def verdict(self, command):
        return cc_guard.decide('PowerShell', {'command': command})

    def test_encoded_commands_run_without_a_question(self):
        for command in ('powershell -EncodedCommand SQBFAFgAIAAoAE4AZQB3AC0ATwBiAGoAZQBjAHQAKQA=',
                        'pwsh -enc SQBFAFgAIAAoAE4AZQB3AC0ATwBiAGoAZQBjAHQAKQA=',
                        "iex ('Re'+'move-Item C:/x')",
                        "Invoke-Expression $payload",
                        '[Convert]::FromBase64String($blob) | Set-Content run.ps1'):
            self.assertEqual(self.verdict(command), ('allow', ''), command)

    def test_deletes_run_without_a_question(self):
        for command in ('python -c "import os; os.remove(\'notes.txt\')"',
                        'python -c "import shutil; shutil.rmtree(\'build\')"',
                        "py -c \"from pathlib import Path; Path('a.txt').unlink()\"",
                        'node -e "require(\'fs\').rmSync(\'dist\', {recursive: true})"'):
            self.assertEqual(self.verdict(command)[0], 'allow', command)
        for command in ('Remove-Item build -Recurse -Force', 'winget install Git.Git', 'git push --force origin main',
                        'git reset --hard HEAD~2', 'npm publish', 'Set-ItemProperty HKCU:\\Software\\x -Name y -Value 1'):
            self.assertEqual(self.verdict(command), ('allow', ''), command)

    def test_messaging_other_people_still_waits_for_the_owner(self):
        for command in ('gh pr comment 12 --body "looks good"', 'gh issue create --title Bug --body x',
                        'Send-MailMessage -To a@b.co -Subject hi -SmtpServer smtp.x.co',
                        'python -c "import smtplib; smtplib.SMTP(\'x\')"',
                        'curl -X POST https://hooks.slack.com/services/T0/B0/x -d hi'):
            self.assertEqual(self.verdict(command), ('approval', cc_guard.MESSAGE), command)
        for command in ('gh pr view 12', 'gh pr create --fill', 'git commit -m "send mail later"'):
            self.assertEqual(self.verdict(command)[0], 'allow', command)

    def test_ordinary_project_work_still_runs(self):
        for command in ('python -m unittest discover -s tests', 'git status --short', 'npm test',
                        'Get-Content README.md | Select-Object -First 20', 'python scripts/memory_benchmark.py --mode offline',
                        'Select-String -Path *.py -Pattern "remove"'):
            self.assertEqual(self.verdict(command)[0], 'allow', command)


if __name__ == '__main__':
    unittest.main()
