import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

import knowledge
from knowledge_events import result_event
import tools


class KnowledgeEventsTest(unittest.TestCase):
    def test_actual_dispatch_emits_search_read_and_missing_sources(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(knowledge, 'VAULT', Path(temp)), \
             mock.patch.object(tools.hud, 'emit') as emit:
            knowledge.create('Home.md', '# Home\nFind this actual marker [[Other]]')
            knowledge.create('Other.md', '# Other\nLinked note')
            search = tools.run_tool(SimpleNamespace(name='search_knowledge', id='1', input={'query':'marker'}))
            self.assertNotIn('is_error', search)
            event = [c.kwargs for c in emit.call_args_list if c.args[0]=='knowledge'][-1]
            self.assertEqual(event['sources'][0]['id'], 'note:Home.md')
            self.assertIn('actual marker', event['sources'][0]['excerpt'])
            self.assertTrue(event['sources'][0]['uri'].startswith('obsidian://'))
            tools.run_tool(SimpleNamespace(name='read_knowledge_note', id='2', input={'path':'Home.md'}))
            event = [c.kwargs for c in emit.call_args_list if c.args[0]=='knowledge'][-1]
            self.assertEqual(event['status'], 'found')
            tools.run_tool(SimpleNamespace(name='search_knowledge', id='3', input={'query':'no-such-marker-unique'}))
            # Use a token not present in either note.
            tools.run_tool(SimpleNamespace(name='search_knowledge', id='4', input={'query':'zqxwvvv'}))
            self.assertEqual([c.kwargs for c in emit.call_args_list if c.args[0]=='knowledge'][-1], {'status':'empty','sources':[]})
            tools.run_tool(SimpleNamespace(name='read_knowledge_note', id='5', input={'path':'Missing.md'}))
            self.assertEqual([c.kwargs for c in emit.call_args_list if c.args[0]=='knowledge'][-1], {'status':'unavailable','sources':[]})

    def test_payload_is_bounded_and_not_fabricated(self):
        item={'path':'a'*900, 'title':'<script>'+'x'*900, 'excerpt':'x'*9000, 'uri':'obsidian:'+'x'*9000}
        event=result_event('search_knowledge', json.dumps([item]*30))
        self.assertEqual(len(event['sources']),8)
        for source in event['sources']:
            self.assertLessEqual(len(source['path']),500)
            self.assertLessEqual(len(source['title']),200)
            self.assertLessEqual(len(source['excerpt']),1200)
            self.assertLessEqual(len(source['uri']),2000)
        self.assertEqual(result_event('read_knowledge_note','invalid'),{'status':'unavailable','sources':[]})
        self.assertIsNone(result_event('open_app','ok'))


if __name__=='__main__':
    unittest.main()
