import copy
import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import agent_sessions
import project_catalog as catalog
import project_memory
import daily_review


class GiantProjectTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.projects = {**catalog.PROJECTS, catalog.GIANT: self.root}
        for obj, name, value in ((catalog,'PROJECTS',self.projects),
                                 (catalog,'MIGRATIONS',self.root/'migrations.json'),
                                 (project_memory,'PROJECTS',self.projects),
                                 (project_memory,'ROOT',self.root),
                                 (project_memory,'STORE',self.root/'handoffs'),
                                 (agent_sessions,'STORE',self.root/'sessions.json')):
            p=patch.object(obj,name,value);p.start();self.addCleanup(p.stop)

    def migration(self):
        catalog.MIGRATIONS.write_text(json.dumps({'giant builder':{
            'from_project':'Rocket Frontier','project':catalog.GIANT,'thread_id':'kept-thread'}}))

    def test_names_and_hand_off_scope(self):
        for name in (catalog.GIANT, 'dont wake the giant', 'DON’T WAKE THE GIANT'):
            self.assertEqual(project_memory.project(name),(catalog.GIANT,self.root))
        with self.assertRaises(ValueError): project_memory.project('../giant')

    def test_migration_keeps_saved_history_and_other_sessions(self):
        self.migration()
        saved={'selected':'giant builder','sessions':{'giant builder':{
            'name':'Giant Builder','provider':'codex','project':'Rocket Frontier','cwd':'old',
            'thread_id':'kept-thread','status':'completed','task':'previous task',
            'report':'saved result','timeline':[{'label':'prior checkpoint'}]},
            'frontier':{'name':'Frontier','provider':'codex','project':'Rocket Frontier','cwd':'frontier',
                        'thread_id':'other','status':'completed'}}}
        agent_sessions.STORE.write_text(json.dumps(saved))
        expected=copy.deepcopy(saved)
        expected['sessions']['giant builder'].update(project=catalog.GIANT,cwd=str(self.root))
        manager=agent_sessions.SessionManager();manager.snapshot()
        self.assertEqual(json.loads(agent_sessions.STORE.read_text()),expected)
        self.assertFalse(catalog.migrate_sessions(manager.entries))
        with patch.object(agent_sessions,'executable',return_value='codex'),patch.object(manager,'publish'),patch.object(agent_sessions,'Connection') as conn:
            self.assertIn('ready in '+catalog.GIANT,manager.open(project=catalog.GIANT))
            conn.assert_not_called()
        self.assertEqual(manager.entries['giant builder']['thread_id'],'kept-thread')

    def test_different_thread_cannot_be_retargeted_by_stale_migration(self):
        self.migration()
        entries={'giant builder':{'project':'Rocket Frontier','thread_id':'new-thread','cwd':'old'}}
        before=copy.deepcopy(entries)
        self.assertFalse(catalog.migrate_sessions(entries));self.assertEqual(entries,before)

    def test_new_session_default_and_handoff(self):
        (self.root/'PROJECT-HANDOFF.txt').write_text('Reference only: collect five golden eggs.')
        manager=agent_sessions.SessionManager()
        with patch.object(agent_sessions,'executable',return_value='codex'),patch.object(manager,'publish'):
            self.assertIn('ready',manager.open(project=catalog.GIANT))
        self.assertEqual(manager.selected,'giant builder')
        with patch.object(project_memory,'_git',return_value=None):
            result=project_memory.handoff(catalog.GIANT,summary='Configured workspace',next_action='Inspect project when asked')
            self.assertEqual(project_memory.status(catalog.GIANT)['last_handoff']['id'],result['id'])

    def test_daily_review_enumerates_registered_giant(self):
        with patch('working_memory.brief',return_value=''),patch('working_memory.project_brief',return_value='saved project evidence') as brief,patch('memory.prompt_section',return_value=''),patch('performance.scorecard',return_value=''),patch('gmail.digest',return_value=''),patch.object(daily_review,'latest',return_value=(None,'')):
            text=daily_review.gather(datetime.date(2026,11,2))
        self.assertIn('## Project: '+catalog.GIANT,text)
        self.assertIn(catalog.GIANT,[c.args[0] for c in brief.call_args_list])


if __name__ == '__main__':
    unittest.main()
