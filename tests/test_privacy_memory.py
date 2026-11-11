import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock

import memory
import privacy


class LocalFeaturesTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        for module,field,value in [(privacy,'STORE',self.root/'privacy.json'),(memory,'PATH',str(self.root/'memory.json')),
                (memory,'RECENT_PATH',str(self.root/'recent.json'))]:
            p=patch.object(module,field,value);p.start();self.addCleanup(p.stop)

    def test_redacts_credentials_json_assignments_and_selected_information(self):
        privacy.configure(['Secret Project'],email=True,phone=True)
        for secret in ['sk-proj-'+'a'*30,'ghp_'+'B'*30,'123-45-6789','Bearer abcdefghijklmnop',
                       'eyJabc.abcdefgh.signature','user@example.com','312-555-1234','Secret Project']:
            self.assertNotIn(secret,privacy.redact('prefix '+secret+' suffix'))
        self.assertNotIn('hunter22',privacy.redact('{"password":"hunter22"}'))
        self.assertIn('player progress',privacy.redact('player progress'))

    def test_private_key_and_image_payload(self):
        key='-----BEGIN PRIVATE KEY-----\nabc123\n-----END PRIVATE KEY-----'
        self.assertNotIn('abc123',privacy.redact(key))
        self.assertEqual(privacy.payload({'type':'image','source':{'type':'base64','data':'sk-'+'a'*30}})['source']['data'],'sk-'+'a'*30)
        self.assertNotIn('sk-'+'a'*30,privacy.payload({'data':'sk-'+'a'*30})['data'])

    def test_memory_redaction_edit_and_stale_revision(self):
        memory.remember('password=hunter22')
        memory.record_turn('SSN 123-45-6789','okay')
        state=memory.snapshot(); self.assertNotIn('hunter22',state['facts'][0]['fact'])
        self.assertNotIn('123-45-6789',state['recent'][0]['user'])
        updated=memory.edit('update',state['revision'],state['facts'][0]['id'],'Likes tea')
        with self.assertRaises(ValueError):memory.edit('delete',state['revision'],updated['facts'][0]['id'])
        deleted=memory.edit('delete',updated['revision'],updated['facts'][0]['id'])
        self.assertEqual(deleted['facts'],[])
        cleared=memory.edit('clear_recent',deleted['revision']);self.assertEqual(cleared['recent'],[])

    def test_memory_scrub_rewrites_existing_records(self):
        memory.remember('private phrase');memory.record_turn('private phrase','private phrase')
        privacy.configure(['private phrase'])
        memory.edit('scrub',memory.revision())
        self.assertNotIn('private phrase',Path(memory.PATH).read_text())
        self.assertNotIn('private phrase',Path(memory.RECENT_PATH).read_text())
        self.assertEqual(memory.recent_prompt(),'')

    def test_spoken_forget_also_invalidates_old_context(self):
        memory.remember('Likes tea');memory.record_turn('Likes tea','Saved')
        memory.forget('Likes tea')
        self.assertEqual(memory.facts(),[]);self.assertEqual(memory.recent_prompt(),'')

    def test_memory_edit_refreshes_active_and_restart_context(self):
        import jarvis
        memory.remember('Likes tea');memory.record_turn('Likes tea','Tea noted')
        brain=jarvis.Brain();brain._run=lambda speak:speak('Okay')
        self.assertIn('Likes tea',brain.system)
        state=memory.snapshot();memory.edit('update',state['revision'],state['facts'][0]['id'],'Likes coffee')
        brain.ask('What do I prefer?',Mock())
        self.assertIn('Likes coffee',brain.system);self.assertNotIn('Likes tea',brain.system)
        self.assertNotIn('Likes tea',jarvis.Brain().system)

    def test_openai_boundary_redacts_without_touching_authentication(self):
        import model_provider
        response=Mock(status_code=200)
        secret='sk-proj-'+'Q'*30
        with patch.object(model_provider,'load_openai_key',return_value='real-auth'), \
                patch.object(model_provider.requests,'post',return_value=response) as post:
            model_provider.Responses()._post({'model':'test','input':secret})
        self.assertNotIn(secret,str(post.call_args.kwargs['json']))
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'],'Bearer real-auth')

    def test_codex_connection_redacts_model_text_only(self):
        import agent_sessions
        from types import SimpleNamespace
        conn=agent_sessions.Connection.__new__(agent_sessions.Connection)
        conn.lock=threading.Lock();conn.proc=SimpleNamespace(stdin=Mock())
        conn.send({'method':'turn/start','params':{'threadId':'thread','input':[{'type':'text','text':'password=hunter22'}]}})
        sent=json.loads(conn.proc.stdin.write.call_args.args[0])
        self.assertNotIn('hunter22',str(sent));self.assertEqual(sent['params']['threadId'],'thread')


if __name__ == "__main__":
    unittest.main()
