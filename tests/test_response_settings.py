import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import response_settings as style


class ResponseSettingsTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        p=patch.object(style,'STORE',Path(self.temp.name)/'style.json');p.start();self.addCleanup(p.stop)

    def test_partial_save_persists_and_keeps_other_choices(self):
        style.update({'humor':80,'tone':'friendly'})
        style.update({'detail':'detailed'})
        self.assertEqual(style.read()['humor'],80)
        self.assertEqual(style.read()['tone'],'friendly')
        self.assertEqual(style.read()['detail'],'detailed')

    def test_invalid_update_does_not_change_saved_settings(self):
        style.update({'humor':40});before=style.STORE.read_bytes()
        for change in ({'humor':True},{'humor':101},{'tone':'invent facts'},{'honesty':0},[]):
            with self.assertRaises(ValueError):style.update(change)
            self.assertEqual(style.STORE.read_bytes(),before)

    def test_honesty_approval_and_context_remain_invariants_at_extremes(self):
        for humor in (0,100):
            for direct in (0,100):
                prompt=style.prompt(dict(style.DEFAULT,humor=humor,directness=direct))
                self.assertIn('Truthfulness is always required',prompt)
                self.assertIn('never authorize actions',prompt)
                self.assertIn('Serious, sensitive or distressing',prompt)
        self.assertIn('No jokes',style.prompt(dict(style.DEFAULT,humor=0)))

    def test_next_turn_refreshes_provider_context_and_retains_dialogue(self):
        import jarvis
        import memory
        with patch.object(memory,'record_turn'),patch.object(memory,'recent_prompt',return_value=''):
            brain=jarvis.Brain();brain._run=lambda speak:speak('Done')
            brain.messages=[{'role':'user','content':'Our project is blue.'},{'role':'assistant','content':'Understood.'}]
            brain.config=dict(brain.selection.active)
            brain._codex_brain=Mock()
            style.update({'humor':0,'directness':100,'detail':'detailed'})
            brain.ask('Explain the plan',Mock())
            self.assertIn('No jokes',brain.system)
            self.assertIn('Be candid and blunt',brain.system)
            self.assertEqual(brain.messages[0]['content'],'Our project is blue.')
            brain._codex_brain.close.assert_called_once()
            self.assertIn('No jokes',jarvis.Brain().system)


if __name__=='__main__':unittest.main()
