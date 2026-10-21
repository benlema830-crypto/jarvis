"""Exercise actual assistant dispatch with approval and remote effects mocked."""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import approvals
import mcp_connections as mcp
import tools


class DispatchTests(unittest.TestCase):
    def dispatch(self, approved, effect=None, available=True):
        catalog = [{'id': 'test', 'name': 'Test server', 'tools': [{'name': 'echo'}]}]
        # Run the background job inline, without affecting an actual supervisor.
        def thread(*, target, **kwargs):
            return SimpleNamespace(start=target)
        with patch.object(mcp, 'catalog', return_value=catalog if available else []), \
             patch.object(mcp, 'call', side_effect=effect, return_value=json.dumps({'isError': True, 'content': []})) as call, \
             patch.object(approvals, 'ask', return_value=(approved, 'test')) as ask, \
             patch.object(tools.hud, 'commands', Mock()) as queue, \
             patch('threading.Thread', side_effect=thread):
            result = tools.run_tool(SimpleNamespace(name='call_mcp_tool', id='one',
                input={'connection_id': 'test', 'tool_name': 'echo', 'arguments_json': '{"text":"test"}'}))
        return result, call, ask, queue

    def test_denial_never_calls_remote_and_releases_busy_lock(self):
        result, call, ask, queue = self.dispatch(False)
        call.assert_not_called()
        ask.assert_called_once()
        self.assertIn('No tool has executed yet', result['content'])
        self.assertIn('cancelled', queue.put.call_args.args[0]['say'])
        self.assertFalse(tools._mcp_busy.locked())

    def test_approved_result_keeps_remote_error_flag_and_untrusted_label(self):
        result, call, ask, queue = self.dispatch(True)
        call.assert_called_once_with('test', 'echo', {'text': 'test'})
        message = queue.put.call_args.args[0]['prompt']
        self.assertIn('untrusted data', message)
        self.assertIn('"isError": true', message)
        self.assertFalse(tools._mcp_busy.locked())

    def test_removed_connection_after_approval_is_reported_as_failure(self):
        def removed(*args):
            # The actual client rechecks saved enable/tool state before networking.
            with patch.object(mcp, '_load', return_value=[]), patch.object(mcp, 'Client') as client:
                try:
                    original_call(*args)
                finally:
                    client.assert_not_called()
        original_call = mcp.call
        result, call, ask, queue = self.dispatch(True, effect=removed)
        self.assertEqual(queue.put.call_args.args[0]['label'], 'MCP request failed')
        self.assertIn('unavailable', queue.put.call_args.args[0]['say'])
        self.assertFalse(tools._mcp_busy.locked())

    def test_unavailable_catalog_does_not_request_approval(self):
        result, call, ask, queue = self.dispatch(True, available=False)
        ask.assert_not_called()
        call.assert_not_called()
        queue.put.assert_not_called()
        self.assertIn('unavailable', result['content'])
