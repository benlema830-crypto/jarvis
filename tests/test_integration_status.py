import http.client
from http.server import ThreadingHTTPServer
import json
import threading
import unittest
from unittest.mock import Mock, patch

import brain
import integration_status
import mcp_connections as mcp


class IntegrationTests(unittest.TestCase):
    def test_inventory_is_local_and_never_treats_catalog_as_live(self):
        with patch.object(mcp, 'connections', return_value=[{
                'enabled': True, 'discovery_state': 'refresh_failed',
                'secret': 'not-for-browser', 'host': 'private.example'}]), \
             patch.object(mcp, 'Client') as client, patch.object(mcp, 'unseal') as decrypt:
            result = integration_status.snapshot()
        client.assert_not_called()
        decrypt.assert_not_called()
        self.assertEqual(result['armory']['refresh_failed'], 1)
        self.assertEqual(result['armory']['state'], 'saved catalogs')
        serialized = json.dumps(result)
        self.assertNotIn('not-for-browser', serialized)
        self.assertNotIn('private.example', serialized)
        states = {x['id']: x['state'] for x in result['integrations']}
        self.assertNotEqual(states['telegram'], 'connected')
        self.assertNotIn(states['zapier'], ('connected',))

    def test_saved_matching_server_is_configured_not_live(self):
        saved = {'enabled': True, 'discovery_state': 'discovered', 'host': 'mcp.zapier.com', 'name': 'Zapier'}
        with patch.object(mcp, 'connections', return_value=[saved]):
            self.assertEqual(next(x for x in integration_status.snapshot()['integrations'] if x['id'] == 'zapier')['state'], 'configured')
        with patch.object(mcp, 'connections', return_value=[dict(saved, enabled=False)]):
            self.assertEqual(next(x for x in integration_status.snapshot()['integrations'] if x['id'] == 'zapier')['state'], 'paused')

    def test_empty_and_unreadable_store_are_distinct(self):
        with patch.object(mcp, 'connections', return_value=[]):
            self.assertEqual(integration_status.snapshot()['armory']['state'], 'unconnected')
        with patch.object(mcp, 'connections', side_effect=ValueError('private storage path')):
            result = integration_status.snapshot()
        self.assertIsNone(result['armory']['saved'])
        states = {x['id']: x['state'] for x in result['integrations']}
        self.assertEqual(states['zapier'], 'unavailable')
        self.assertEqual(states['github'], 'unavailable')
        self.assertNotIn('private storage path', json.dumps(result))

    def test_saved_calendar_and_model_are_not_live_checks(self):
        with patch('preferences.read', return_value={
                'calendar_urls': ['https://private.example/feed'],
                'conversation_model': {'provider': 'codex', 'model': 'test'}}):
            result = integration_status.snapshot()
        states = {x['id']: x['state'] for x in result['integrations']}
        self.assertEqual(states['calendar'], 'configured')
        self.assertEqual(states['models'], 'configured')
        self.assertNotIn('private.example', json.dumps(result))

    def test_legacy_connection_public_state_is_historical(self):
        result = mcp.public(dict(id='x', name='x', host='example.com', enabled=True,
                                 tools=[], checked_at=123, secret='hidden'))
        self.assertFalse(result['live_verified'])
        self.assertEqual(result['discovery_state'], 'discovered')
        self.assertEqual(result['last_attempt_at'], 123)
        self.assertNotIn('secret', result)

    def test_companion_read_only_route_and_asset_with_existing_guards(self):
        holder = {}
        def construct(address, handler):
            holder['handler'] = handler
            return Mock()
        with patch('http.server.ThreadingHTTPServer', side_effect=construct), \
             patch('visual_modes.controller'):
            brain.serve()
        server = ThreadingHTTPServer(('127.0.0.1', 0), holder['handler'])
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        def call(method='GET', path='/integration-status', headers=None):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
            fields = {'Host': '127.0.0.1:7781', 'Content-Type': 'application/json'}
            fields.update(headers or {})
            connection.request(method, path, headers=fields)
            response = connection.getresponse()
            result = response.status, response.getheader('Cache-Control'), response.read()
            connection.close()
            return result
        try:
            with patch.object(mcp, 'connections', return_value=[]), patch.object(mcp, 'Client') as client:
                code, cache, body = call()
                self.assertEqual((code, cache), (200, 'no-store'))
                self.assertEqual(json.loads(body)['armory']['state'], 'unconnected')
                self.assertEqual(call('POST')[0], 404)
                self.assertEqual(call(headers={'Host': 'other.example'})[0], 403)
                self.assertEqual(call(headers={'Origin': 'https://other.example'})[0], 403)
                self.assertEqual(call(path='/panels.js')[0], 200)
                client.assert_not_called()
        finally:
            server.shutdown()
            server.server_close()
