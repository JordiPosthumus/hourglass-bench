import json
import tempfile
import unittest
from pathlib import Path
import run_editor

class SetupReuse(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  self.source={'id':'old','model':'fixture','config_hash':'exact','hardware':{'machine_key':'machine','label':'desktop','captured_at':'old'},'started':100,'state':'stopped'}
  self.target={**self.source,'id':'new','started':None,'state':'pending'}
  self.values={'model_name':'Fixture','run_name':'My setup','temperature':0,'notes':'Retain all my text','cache':'Enabled'}
 def save(self,manifest,values,base=None):
  return run_editor.save(self.root,manifest,{'values':values,'applies_from':'run_start','base_revision':base})
 def test_complete_setup_survives_deleted_run_and_keeps_execution_untouched(self):
  self.save(self.source,self.values)
  (self.root/'evaluations/old.details.jsonl').unlink()
  original=json.dumps(self.target,sort_keys=True)
  result=run_editor.reuse_setup(self.root,self.target)
  self.assertEqual(result['values'],self.values)
  self.assertIn('Reused saved editor setup',result['reason'])
  self.assertEqual(json.dumps(self.target,sort_keys=True),original)
  self.assertIsNone(run_editor.reuse_setup(self.root,self.target))
 def test_config_and_machine_must_match_but_capture_time_can_change(self):
  self.save(self.source,self.values)
  for change in [{'config_hash':'different'},{'model':'another'},{'hardware':{'machine_key':'other','label':'desktop'}}]:
   self.assertIsNone(run_editor.reusable_setup(self.root,{**self.target,**change}))
  target={**self.target,'hardware':{**self.target['hardware'],'captured_at':'new'}}
  self.assertEqual(run_editor.reusable_setup(self.root,target)['values'],self.values)
 def test_preexisting_deleted_backup_can_be_reused(self):
  p=self.root/'backups/cleared-run-fixture';p.mkdir(parents=True)
  (p/'evaluation.json').write_text(json.dumps(self.source))
  (p/'old.details.jsonl').write_text(json.dumps({'recorded_at':10,'values':self.values})+'\n')
  self.assertEqual(run_editor.reuse_setup(self.root,self.target)['values'],self.values)
 def test_empty_revision_clears_setup_and_existing_target_is_preserved(self):
  first=self.save(self.source,self.values)
  self.save(self.source,{},first['id'])
  self.assertEqual(run_editor.reusable_setup(self.root,self.target)['values'],{})
  self.save(self.target,{'notes':'Keep current edit'})
  self.assertIsNone(run_editor.reuse_setup(self.root,self.target))
  self.assertEqual(run_editor.snapshot(self.root,'new')['values'],{'notes':'Keep current edit'})
