"""Proposal: Codex processes Jarvis starts for conversation or research get no native MCP tools.

Without this, they inherit every server in ~/.codex/config.toml (here Roblox Studio, whose
execute_luau is auto-approved) plus the built-in ChatGPT apps server (site deploy/delete, app
uninstall, parental controls...), none of which pass through Jarvis's own approvals."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import agent_sessions
import codex_brain


class IsolationArgsTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.config = Path(temp.name) / 'config.toml'
        self.config.write_text('model = "x"\n[mcp_servers.Roblox_Studio]\ncommand = "studio.exe"\nargs = ["--secret-token=abc"]\n'
                               '[mcp_servers.Roblox_Studio.tools.execute_luau]\napproval_mode = "approve"\n'
                               '[mcp_servers."My Docs"]\nurl = "https://example.invalid"\n', encoding='utf-8')
        patcher = mock.patch.object(agent_sessions, 'CODEX_CONFIG', self.config)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_isolation_disables_apps_and_every_configured_server(self):
        args = agent_sessions.isolation_args()
        self.assertEqual(args[:2], ['--disable', 'apps'])
        self.assertIn('mcp_servers.Roblox_Studio.enabled=false', args)
        self.assertIn('mcp_servers."My Docs".enabled=false', args)
        self.assertNotIn('abc', ' '.join(args))  # only server names are read, never their settings

    def test_missing_or_broken_config_still_disables_apps(self):
        self.config.unlink()
        self.assertEqual(agent_sessions.isolation_args(), ['--disable', 'apps'])
        self.config.write_text('[[not toml', encoding='utf-8')
        self.assertEqual(agent_sessions.isolation_args(), ['--disable', 'apps'])

    def popen_args(self, **kw):
        with mock.patch.object(agent_sessions, 'executable', return_value='codex.exe'), \
                mock.patch.object(agent_sessions.subprocess, 'Popen') as popen, \
                mock.patch.object(agent_sessions.threading, 'Thread'):
            agent_sessions.Connection('.', lambda e: None, **kw)
        return popen.call_args.args[0]

    def test_connection_applies_isolation_only_when_asked(self):
        self.assertEqual(self.popen_args(), ['codex.exe', 'app-server', '--listen', 'stdio://'])
        isolated = self.popen_args(isolate_mcp=True)
        self.assertEqual(isolated[:2], ['codex.exe', 'app-server'])
        self.assertIn('mcp_servers.Roblox_Studio.enabled=false', isolated)
        self.assertEqual(isolated[-2:], ['--listen', 'stdio://'])

    def test_conversation_brain_is_isolated(self):
        with mock.patch.object(codex_brain, 'Connection') as connection:
            connection.return_value.call.return_value = {'account': {'type': 'chatgpt'}}
            codex_brain.connect(lambda e: None)
        self.assertTrue(connection.call_args.kwargs.get('isolate_mcp'))

    def test_research_sessions_are_isolated_and_work_sessions_keep_tools(self):
        self.assertTrue(agent_sessions.isolate_for_mode('research'))
        self.assertFalse(agent_sessions.isolate_for_mode('work'))


if __name__ == '__main__':
    unittest.main()
