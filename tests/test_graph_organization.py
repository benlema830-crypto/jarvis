import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import brain
import knowledge


class GraphOrganizationTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'data').mkdir()
        (self.root/'tools.py').write_text('TOOLS = []')
        def note(path,body):
            return {'path':path,'title':Path(path).stem,'content':body,'uri':'obsidian://open?path='+path}
        self.notes=[note('Projects/JARVIS.md','# JARVIS'),note('Projects/Rocket Frontier.md','# Rocket Frontier'),
            note('Plans/Next.md','# Next\n[[Projects/JARVIS]]'),note('Home.md','# Library'),
            note('Reports/Build.md','---\ndate: 2026-10-27\ntime: 10:30\nagent: agent session Builder\n---\n# Build\n\n## Report\n\nFixed startup. Tests passed.'),
            note('Reports/Music.md','# Spotify report\n\nJarvis played music.'),
            note('Projects/Rocket Frontier/Design.md','# Design'),
            note('Decisions/Shared.md','---\nproject: Rocket Frontier\n---\n# Shared')]
        self.links=[{'source':'Plans/Next.md','target':'Projects/JARVIS.md'},
                    {'source':'Projects/Rocket Frontier.md','target':'Projects/JARVIS.md'}]
        (self.root/'data/agent_sessions.json').write_text(json.dumps({'sessions':{'builder':{'name':'Builder','project':'Jarvis'}}}))
        (self.root/'data/recent_conversation.json').write_text(json.dumps([
            {'time':'2026-10-27T10:00:00','user':'Hello Jarvis.','assistant':'Hello.'},
            {'time':'2026-10-27T11:00:00','user':'Hello Jarvis.','assistant':'Hello again.'}]))

    def snapshot(self):
        with patch.object(brain,'ROOT',self.root),patch.object(knowledge,'index',return_value={
            'notes':copy.deepcopy(self.notes),'links':copy.deepcopy(self.links),'skipped':0,'unresolved':0}):
            return brain.snapshot()

    def test_keeps_all_content_and_ids_and_disambiguates_jarvis(self):
        data=self.snapshot();nodes={n['id']:n for n in data['nodes']}
        self.assertEqual(nodes['root']['label'],'Jarvis Assistant')
        self.assertEqual(nodes['note:Projects/JARVIS.md']['label'],'Jarvis Project')
        self.assertEqual(nodes['vault']['label'],'Knowledge Library')
        for note in self.notes:
            self.assertEqual(nodes['note:'+note['path']]['body'],note['content'])
        self.assertEqual(len([n for n in nodes.values() if n['kind']=='Note']),len(self.notes))
        self.assertEqual(nodes['recent-0']['original_label'],nodes['recent-1']['original_label'])
        self.assertNotEqual(nodes['recent-0']['label'],nodes['recent-1']['label'])

    def test_project_neighborhoods_require_explicit_evidence(self):
        data=self.snapshot();nodes={n['id']:n for n in data['nodes']}
        jarvis='note:Projects/JARVIS.md';rocket='note:Projects/Rocket Frontier.md'
        self.assertIn(jarvis,nodes['note:Plans/Next.md']['parents'])
        self.assertIn(jarvis,nodes['note:Reports/Build.md']['parents'])
        self.assertIn(rocket,nodes['note:Projects/Rocket Frontier/Design.md']['parents'])
        self.assertIn(rocket,nodes['note:Decisions/Shared.md']['parents'])
        self.assertEqual(nodes['note:Reports/Music.md']['project_ids'],[])
        self.assertNotIn(rocket,nodes[jarvis]['parents'])
        self.assertTrue(any(l['kind']=='project-report' and 'Builder' in l['evidence'] for l in data['links']))
        self.assertTrue(any(l['kind']=='note-link' and l['label']=='References' for l in data['links']))

    def test_overview_contains_hubs_not_history_leaves(self):
        nodes={n['id']:n for n in self.snapshot()['nodes']}
        self.assertTrue(nodes['note:Projects/JARVIS.md']['overview'])
        self.assertTrue(nodes['recent']['overview']);self.assertTrue(nodes['recent']['hub'])
        self.assertFalse(nodes['recent-0']['overview'])
        self.assertFalse(nodes['note:Reports/Build.md']['overview'])
        self.assertEqual(nodes['recent']['child_count'],2)
        self.assertIn('Fixed startup',nodes['note:Reports/Build.md']['label'])


if __name__=='__main__':unittest.main()
