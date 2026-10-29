import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import holo_control
import project_memory
import hud
from collections import deque


class ResumePanelsTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        patcher=patch.object(project_memory,'PROJECTS',{'Jarvis':self.root});patcher.start();self.addCleanup(patcher.stop)
        (self.root/'main.py').write_text('print("hello")')

    def test_resume_includes_attribution_and_readable_existing_files(self):
        evidence={'project':'Jarvis','checked_at':'today','verified':[{'source':'git status','text':' M main.py'}],
            'last_handoff':{'created_at':'yesterday','claims':{'summary':'Fixed startup','unresolved':'Audio pending','next_action':'Test microphone','files':'main.py\nmissing.py\n../outside.py'}},
            'reference_notes':[],'agent_reports':[],'interpretation':'Reports are claims.'}
        with patch.object(project_memory,'status',return_value=evidence),patch.object(project_memory,'_git',return_value='main.py'):
            result=project_memory.resume('Jarvis')
        self.assertEqual([f['path'] for f in result['files']],['main.py'])
        self.assertIn('yesterday',result['summary_source'])
        self.assertEqual(result['next_action'],'Test microphone')
        self.assertEqual(project_memory.source_file('Jarvis','main.py')['text'],'print("hello")')

    def test_source_previews_exclude_runtime_secrets_and_traversal(self):
        for path in ['../outside.py','.env','data/memory.json','voices/sample.txt','voice-profile.json']:
            with self.assertRaises(ValueError):project_memory.source_file('Jarvis',path)

    def test_newer_agent_report_takes_precedence_over_old_handoff(self):
        evidence={'project':'Jarvis','checked_at':'today','verified':[], 'interpretation':'claims',
            'last_handoff':{'created_at':'2020-01-01T00:00:00+00:00','claims':{'summary':'Old work','next_action':'Old plan'}},
            'agent_reports':[{'name':'New','report':'New work','reported_at':1700000000},
                             {'name':'Old','report':'Older work','reported_at':1600000000}]}
        with patch.object(project_memory,'status',return_value=evidence),patch.object(project_memory,'_git',return_value=''):
            result=project_memory.resume('Jarvis')
        self.assertEqual(result['summary'],'New work')
        self.assertIn('Earlier handoff',result['next_action'])

    def test_explicit_voice_commands_only(self):
        emit=Mock()
        for text in ['bring that closer','put that away','show my tasks','expand panel Alpha']:
            self.assertEqual(holo_control.dispatch(text,emit),'')
        self.assertEqual(emit.call_count,4)
        for text in ['explain how to bring that closer','show my tasks and delete them','continue working on an unknown project']:
            self.assertIsNone(holo_control.dispatch(text,emit))
        self.assertEqual(emit.call_count,4)

    def test_ui_commands_and_resource_hints_are_not_replayed(self):
        with patch.object(hud,'_history',deque()),patch.object(hud,'_subscribers',[]):
            for kind in ['holo-panel','project-resume','visual-model','resources']:
                hud.emit(kind,action='test')
            self.assertEqual(len(hud._history),0)


if __name__=='__main__':unittest.main()
