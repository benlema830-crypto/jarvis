import json
import http.client
from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

import model_provider as mp


class ModelTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher = mock.patch.object(mp.preferences, 'PATH', Path(directory.name) / 'preferences.json')
        patcher.start()
        self.addCleanup(patcher.stop)

    def wait(self, selection):
        for _ in range(200):
            with selection.lock:
                if not selection.pending:
                    return
            time.sleep(.005)
        self.fail('model change did not finish')

    def test_switch_waits_for_turn_and_persists_after_validation(self):
        checked, saved = [], []
        s = mp.Selection(validate=lambda c: checked.append(c), persist=lambda c: saved.append(c))
        s.ready = True
        previous = s.begin()
        desired = {'provider': 'codex', 'model': 'gpt-test'}
        with mock.patch.object(mp, 'catalog', return_value={'claude_code':['claude-opus-5-5'],'codex':['gpt-test']}):
            s.request(desired)
        self.assertEqual(s.active, previous)
        self.assertFalse(checked)
        s.end()
        self.wait(s)
        self.assertEqual(s.active, desired)
        self.assertEqual(saved, [desired])

    def test_failed_validation_and_save_keep_last_valid_config(self):
        for validate, persist in [(mock.Mock(side_effect=mp.ProviderError('Codex validation failed.')), mock.Mock()),
                                  (mock.Mock(), mock.Mock(side_effect=OSError('private detail')))]:
            s = mp.Selection(validate=validate, persist=persist)
            s.ready = True
            with mock.patch.object(mp, 'catalog', return_value={'claude_code':['claude-opus-5-5'],'codex':['gpt-test']}):
                s.request({'provider':'codex', 'model':'gpt-test'})
            self.wait(s)
            self.assertEqual(s.active, mp.DEFAULT)
            self.assertTrue(s.error)
            self.assertNotIn('private detail', s.error)

    def test_history_drops_foreign_tool_blocks(self):
        result = mp.text_history([
            {'role':'user', 'content':'question'},
            {'role':'assistant','content':[{'type':'text','text':'checking'}, {'type':'tool_use','id':'private'}]},
            {'role':'user','content':[{'type':'tool_result','content':'secret tool data'}]}])
        self.assertEqual(result, [{'role':'user','content':'question'}, {'role':'assistant','content':'checking'}])

    def test_tool_images_are_provider_native_without_capture(self):
        text,images=mp.tool_output([{'type':'text','text':'Masked screenshot'},
            {'type':'image','source':{'type':'base64','media_type':'image/jpeg','data':'inert-test-only'}}])
        self.assertIn('Masked screenshot',text)
        self.assertNotIn('inert-test-only',text)
        self.assertEqual(images,[{'type':'input_image','image_url':'data:image/jpeg;base64,inert-test-only','detail':'auto'}])

    def test_atomic_preferences_preserve_other_settings(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(mp.preferences, 'PATH', Path(directory)/'prefs.json'):
            mp.preferences.update(listening_mode='wake')
            s = mp.Selection()
            s.persist({'provider':'codex','model':'gpt-test'})
            self.assertEqual(mp.preferences.read()['listening_mode'], 'wake')
            self.assertFalse((Path(directory)/'prefs.tmp').exists())

    def test_paid_providers_cannot_be_chosen_or_validated(self):
        s = mp.Selection(validate=mock.Mock(), persist=mock.Mock())
        s.ready = True
        with mock.patch.object(mp, 'catalog', return_value={'claude_code':['claude-opus-5-5'],'codex':['gpt-test']}):
            for provider, model in (('anthropic', 'claude-opus-5-5'), ('openai', 'gpt-4.1-mini'), ('ollama', 'qwen3:4b')):
                with self.assertRaises(ValueError):
                    s.request({'provider': provider, 'model': model})
        s.validate.assert_not_called()
        with self.assertRaises(mp.ProviderError):
            mp.Selection()._validate({'provider': 'anthropic', 'model': 'claude-opus-5-5'})
        self.assertEqual(mp.PROVIDERS, ('claude_code', 'codex', 'local'))  # local: this PC's Ollama, never billed
        self.assertFalse(hasattr(mp, 'Responses'))

    def test_busy_and_validating_cannot_overlap_turns(self):
        s=mp.Selection()
        s.begin()
        with self.assertRaises(mp.ProviderError):s.begin()
        s.end();s.validating=True
        with self.assertRaises(mp.ProviderError):s.begin()


class ModelEndpointTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher = mock.patch.object(mp.preferences, 'PATH', Path(directory.name) / 'preferences.json')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_endpoint_host_json_guards_and_pending_response(self):
        import hud
        selection=mp.Selection(validate=mock.Mock(),persist=mock.Mock())
        selection.ready=True
        selection.begin()  # Hold a turn so POST cannot trigger even a mocked probe.
        server=ThreadingHTTPServer(('127.0.0.1',0),hud._Handler)
        server.daemon_threads=True
        threading.Thread(target=server.serve_forever,daemon=True).start()
        def request(method,payload=None,headers=None):
            connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
            connection.request(method,'/models',body=payload,headers=headers or {})
            response=connection.getresponse()
            result=(response.status,response.getheader('Cache-Control'),response.read())
            connection.close()
            return result
        try:
            with mock.patch.object(mp,'SELECTION',selection),\
                 mock.patch.object(mp,'catalog',return_value={'claude_code':['claude-opus-5-5'],'codex':['gpt-test']}),\
                 mock.patch.object(hud,'ALLOWED_HOSTS',{f'127.0.0.1:{server.server_port}'}):
                code,cache,body=request('GET')
                self.assertEqual((code,cache),(200,'no-store'))
                self.assertEqual(sorted(json.loads(body)['models']),['claude_code','codex'])  # no paid providers offered
                self.assertEqual(request('GET',headers={'Host':'bad.example'})[0],403)
                self.assertEqual(request('POST','{}',{'Content-Type':'text/plain'})[0],400)
                self.assertEqual(request('POST','{"provider":[]}',{'Content-Type':'application/json'})[0],400)
                config={'provider':'codex','model':'gpt-test'}
                code,_,body=request('POST',json.dumps(config),{'Content-Type':'application/json'})
                self.assertEqual(code,200)
                self.assertEqual(json.loads(body)['pending'],config)
                self.assertEqual(json.loads(body)['active'],mp.DEFAULT)
                selection.validate.assert_not_called()
        finally:
            server.shutdown();server.server_close()


if __name__ == '__main__':
    unittest.main()
