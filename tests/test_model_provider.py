import json
import http.client
from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock
from types import SimpleNamespace

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
        desired = {'provider': 'openai', 'model': 'gpt-4.1-mini'}
        with mock.patch.object(mp, 'credential_state', return_value='available'), mock.patch.object(mp, 'catalog', return_value={'openai':['gpt-4.1-mini']}):
            s.request(desired)
        self.assertEqual(s.active, previous)
        self.assertFalse(checked)
        s.end()
        self.wait(s)
        self.assertEqual(s.active, desired)
        self.assertEqual(saved, [desired])

    def test_failed_validation_and_save_keep_last_valid_config(self):
        for validate, persist in [(mock.Mock(side_effect=mp.ProviderError('OpenAI authentication failed.')), mock.Mock()),
                                  (mock.Mock(), mock.Mock(side_effect=OSError('private detail')))]:
            s = mp.Selection(validate=validate, persist=persist)
            s.ready = True
            with mock.patch.object(mp, 'credential_state', return_value='available'), mock.patch.object(mp, 'catalog', return_value={'openai':['gpt-4.1-mini']}):
                s.request({'provider':'openai', 'model':'gpt-4.1-mini'})
            self.wait(s)
            self.assertEqual(s.active, mp.DEFAULT)
            self.assertTrue(s.error)
            self.assertNotIn('private detail', s.error)

    def test_missing_key_and_http_errors_are_safe(self):
        with mock.patch.object(mp, 'load_openai_key', return_value=''), mock.patch.object(mp.requests, 'post') as post:
            with self.assertRaisesRegex(mp.ProviderError, 'setup required'):
                mp.Responses().validate('gpt-4.1-mini')
            post.assert_not_called()
        for code, text in [(401, 'authentication'), (404, 'model unavailable'), (429, 'quota')]:
            response = mock.Mock(status_code=code)
            with mock.patch.object(mp, 'load_openai_key', return_value='secret-test-key'), mock.patch.object(mp.requests, 'post', return_value=response):
                with self.assertRaisesRegex(mp.ProviderError, text):
                    mp.Responses().validate('gpt-4.1-mini')
            response.close.assert_called_once()

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
            s.persist({'provider':'openai','model':'gpt-4.1-mini'})
            self.assertEqual(mp.preferences.read()['listening_mode'], 'wake')
            self.assertFalse((Path(directory)/'prefs.tmp').exists())

    def test_stream_cancellation_closes_response(self):
        response = mock.Mock(status_code=200)
        response.iter_lines.return_value = [b'data: {"type":"response.output_text.delta","delta":"hello"}',
                                           b'data: {"type":"response.completed"}']
        cancel = threading.Event()
        with mock.patch.object(mp, 'load_openai_key', return_value='test'), mock.patch.object(mp.requests, 'post', return_value=response):
            stream = mp.Responses().events({'model':'gpt-4.1-mini'}, cancel)
            self.assertEqual(next(stream)['delta'], 'hello')
            cancel.set()
            self.assertEqual(list(stream), [])
            response.close.assert_called()

    def test_validation_requires_completed_text_and_never_sends_private_context(self):
        response=mock.MagicMock(status_code=200)
        response.__enter__.return_value=response
        for status, content, success in [('completed',[{'type':'output_text','text':'OK'}],True),
                                         ('incomplete',[],False),('completed',[],False)]:
            response.json.return_value={'status':status,'output':[{'content':content}]}
            with mock.patch.object(mp,'load_openai_key',return_value='test'), mock.patch.object(mp.requests,'post',return_value=response) as post:
                if success:
                    mp.Responses().validate('gpt-4.1-mini')
                else:
                    with self.assertRaises(mp.ProviderError):mp.Responses().validate('gpt-4.1-mini')
                request=post.call_args.kwargs
                self.assertEqual(request['json']['input'],'Reply with OK.')
                self.assertNotIn('tools',request['json'])
                self.assertFalse(request['allow_redirects'])

    def test_busy_and_validating_cannot_overlap_turns(self):
        s=mp.Selection()
        s.begin()
        with self.assertRaises(mp.ProviderError):s.begin()
        s.end();s.validating=True
        with self.assertRaises(mp.ProviderError):s.begin()


class OpenAIConversationTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher = mock.patch.object(mp.preferences, 'PATH', Path(directory.name) / 'preferences.json')
        patcher.start()
        self.addCleanup(patcher.stop)

    def brain(self):
        import jarvis
        selection = mp.Selection(validate=mock.Mock(), persist=mock.Mock())
        selection.active = {'provider':'openai','model':'gpt-4.1-mini'}
        with mock.patch.object(mp, 'SELECTION', selection), mock.patch.object(jarvis.preferences, 'read', return_value={}), \
             mock.patch.object(jarvis.memory, 'prompt_section', return_value=''), mock.patch.object(jarvis.memory, 'recent_prompt', return_value=''), \
             mock.patch.object(jarvis, 'web_search_def', return_value={}):
            brain = jarvis.Brain()
        return brain

    def test_text_tool_round_trip_retains_call_items(self):
        import jarvis
        brain = self.brain()
        requests = []
        outputs = [
            [{'type':'function_call','name':'search_knowledge','arguments':'{"query":"test"}','call_id':'call-1'}],
            [{'type':'message','role':'assistant','content':[{'type':'output_text','text':'Found it.',
              'annotations':[{'type':'url_citation','title':'Source','url':'https://example.com'}]}]}]]
        def events(_, payload, cancel):
            requests.append(json.loads(json.dumps(payload)))
            if len(requests) == 2:
                yield {'type':'response.output_text.delta','delta':'Found it.'}
            yield {'type':'response.completed','response':{'status':'completed','output':outputs[len(requests)-1]}}
        said=[]
        with mock.patch.object(mp.Responses, 'events', events), mock.patch.object(jarvis, 'run_tool', return_value={'content':'mock source'}) as tool, \
             mock.patch.object(jarvis.hud, 'emit') as emit, mock.patch.object(jarvis.memory, 'record_turn'):
            brain.ask('Find test', said.append)
        self.assertEqual(said, ['Found it.'])
        self.assertEqual(tool.call_args.args[0].id, 'call-1')
        self.assertIn({'type':'function_call_output','call_id':'call-1','output':'mock source'}, requests[1]['input'])
        self.assertTrue(all(t['type'] in ('function','web_search') for t in requests[0]['tools']))
        self.assertNotIn('context_management', requests[0])
        self.assertFalse(brain.selection.busy)
        self.assertTrue(any(c.args[0]=='sources' for c in emit.call_args_list))

    def test_interrupt_prevents_tool_execution(self):
        import jarvis
        brain=self.brain()
        def events(_, payload, cancel):
            cancel.set()
            yield {'type':'response.completed','response':{'status':'completed','output':[
                {'type':'function_call','name':'open_app','arguments':'{}','call_id':'c'}]}}
        with mock.patch.object(mp.Responses,'events',events), mock.patch.object(jarvis,'run_tool') as tool, \
             mock.patch.object(jarvis.memory,'record_turn'), self.assertRaises(jarvis.Interrupted):
            brain.ask('test', mock.Mock())
        tool.assert_not_called()
        self.assertFalse(brain.selection.busy)
        self.assertIn('interrupted',brain.messages[-1]['content'])

    def test_followup_retains_response_items_and_background_dialogue(self):
        import jarvis
        brain=self.brain()
        sent=[]
        output=[{'type':'reasoning','id':'reason-1','summary':[], 'encrypted_content':'opaque'},
                {'type':'message','role':'assistant','content':[{'type':'output_text','text':'First.'}]}]
        def events(_, payload, cancel):
            sent.append(json.loads(json.dumps(payload)))
            yield {'type':'response.output_text.delta','delta':'First.'}
            yield {'type':'response.completed','response':{'status':'completed','output':output}}
        with mock.patch.object(mp.Responses,'events',events),mock.patch.object(jarvis.memory,'record_turn'):
            brain.ask('first',mock.Mock())
            brain.note('Task finished','Result ready.')
            brain.ask('follow up',mock.Mock())
        self.assertIn(output[0],sent[1]['input'])
        self.assertTrue(any(i.get('content')=='Result ready.' for i in sent[1]['input']))
        self.assertEqual(sum(i.get('type')=='reasoning' for i in sent[1]['input']),1)

    def test_incomplete_stream_and_refusal_do_not_become_success(self):
        import jarvis
        for output, expected in [(None,mp.ProviderError),([{'type':'message','content':[{'type':'refusal','refusal':'No'}]}],jarvis.Refused)]:
            brain=self.brain()
            def events(_,payload,cancel):
                if output is not None:
                    yield {'type':'response.completed','response':{'status':'completed','output':output}}
            with mock.patch.object(mp.Responses,'events',events),mock.patch.object(jarvis.memory,'record_turn') as saved:
                with self.assertRaises(expected):brain.ask('question',mock.Mock())
                saved.assert_not_called()
            self.assertEqual(brain.messages,[])
            self.assertFalse(brain.selection.busy)

    def test_saved_openai_is_restored_without_probe_or_fallback(self):
        import jarvis
        selection=mp.Selection(validate=mock.Mock(),persist=mock.Mock())
        config={'provider':'openai','model':'gpt-4.1-mini'}
        with mock.patch.object(mp,'SELECTION',selection),mock.patch.object(jarvis.preferences,'read',return_value={'conversation_model':config}),\
             mock.patch.object(jarvis,'web_search_def',return_value={}),mock.patch.object(jarvis.memory,'prompt_section',return_value=''),\
             mock.patch.object(jarvis.memory,'recent_prompt',return_value=''):
            jarvis.Brain()
        self.assertEqual(selection.active,config)
        selection.validate.assert_not_called()

    def test_claude_still_streams_and_emits_research_citations(self):
        import jarvis
        brain=self.brain();brain.selection.active=dict(mp.DEFAULT)
        client=mock.MagicMock();brain.client=client
        stream=client.beta.messages.stream.return_value.__enter__.return_value
        stream.__iter__.return_value=iter([SimpleNamespace(type='text',text='A sourced answer.')])
        stream.get_final_message.return_value=SimpleNamespace(stop_reason='end_turn',usage=object(),content=[
            SimpleNamespace(type='text',text='A sourced answer.',citations=[SimpleNamespace(url='https://example.com',title='Research')])])
        said=[]
        with mock.patch.object(jarvis,'log_usage'),mock.patch.object(jarvis.hud,'emit') as emit,mock.patch.object(jarvis.memory,'record_turn'):
            brain.ask('Research this',said.append)
        self.assertEqual(said,['A sourced answer.'])
        self.assertEqual(client.beta.messages.stream.call_args.kwargs['model'],mp.CLAUDE_MODEL)
        self.assertIn(mock.call('sources',sources=[{'url':'https://example.com','title':'Research'}]),emit.call_args_list)

    def test_tool_rounds_are_bounded(self):
        import jarvis
        brain=self.brain()
        def events(_,payload,cancel):
            yield {'type':'response.completed','response':{'status':'completed','output':[
                {'type':'function_call','name':'search_knowledge','arguments':'{}','call_id':'c'}]}}
        with mock.patch.object(mp.Responses,'events',events),mock.patch.object(jarvis,'run_tool',return_value={'content':'mock'}) as tool,\
             mock.patch.object(jarvis.memory,'record_turn'):
            with self.assertRaisesRegex(mp.ProviderError,'round limit'):brain.ask('test',mock.Mock())
        self.assertEqual(tool.call_count,10)
        self.assertEqual(brain.messages,[])


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
            with mock.patch.object(mp,'SELECTION',selection),mock.patch.object(mp,'credential_state',return_value='setup required'),\
                 mock.patch.object(mp,'catalog',return_value={'anthropic':[mp.CLAUDE_MODEL],'openai':['gpt-4.1-mini']}),\
                 mock.patch.object(hud,'ALLOWED_HOSTS',{f'127.0.0.1:{server.server_port}'}):
                code,cache,body=request('GET')
                self.assertEqual((code,cache),(200,'no-store'))
                self.assertEqual(json.loads(body)['credential'],'setup required')
                self.assertEqual(request('GET',headers={'Host':'bad.example'})[0],403)
                self.assertEqual(request('POST','{}',{'Content-Type':'text/plain'})[0],400)
                self.assertEqual(request('POST','{"provider":[]}',{'Content-Type':'application/json'})[0],400)
                config={'provider':'openai','model':'gpt-4.1-mini'}
                code,_,body=request('POST',json.dumps(config),{'Content-Type':'application/json'})
                self.assertEqual(code,200)
                self.assertEqual(json.loads(body)['pending'],config)
                self.assertEqual(json.loads(body)['active'],mp.DEFAULT)
                selection.validate.assert_not_called()
        finally:
            server.shutdown();server.server_close()


if __name__ == '__main__':
    unittest.main()
