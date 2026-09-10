import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import calibration
import hardware_records
import option_layout
import run_naming
import task_identity
import web

class BankHardeningTests(unittest.TestCase):
    def test_images_fixtures_and_verifiers_change_bundle_identity(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'task.json').write_text('{}');before=task_identity.identity(p)
            for name in ['chart.png','fixture.js','verify/check.py']:
                f=p/name;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(b'first')
                after=task_identity.identity(p);self.assertNotEqual(before,after)
                f.write_bytes(b'edited');self.assertNotEqual(after,task_identity.identity(p));before=task_identity.identity(p)
    def test_queued_snapshot_survives_author_edits_but_rejects_snapshot_tampering(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'tasks/t';p.mkdir(parents=True);(p/'task.json').write_text('{"repeat":1}');(p/'chart.png').write_bytes(b'original')
            job={'id':'run','model':'fixture','tasks':['t'],'repeat':1,'created':0,'state':'pending'}
            manifest=calibration.evaluation_manifest(root,job,'test',{'model':'fixture'})
            frozen=root/manifest['task_snapshot']/'t';(p/'chart.png').write_bytes(b'changed')
            task_identity.verify(frozen,manifest['expected'][0])
            with self.assertRaises(ValueError):task_identity.verify(p,manifest['expected'][0])
            (frozen/'chart.png').write_bytes(b'tampered')
            with self.assertRaises(ValueError):task_identity.verify(frozen,manifest['expected'][0])
    def test_layout_is_reproducible_and_remaps_truth_without_mutating_bank(self):
        task={'id':'fixture','mode':'option_id','answer':'017','options':[{'id':f'{i:03d}','text':f'text {i}'} for i in range(1,65)]}
        original=copy.deepcopy(task);answers=set()
        for repeat in range(1,41):
            shown,record=option_layout.prepare(task,repeat,'frozen bundle')
            self.assertEqual((shown,record),option_layout.prepare(task,repeat,'frozen bundle'))
            self.assertEqual(record['display_to_original'][shown['answer']],'017')
            self.assertEqual(next(o['text'] for o in shown['options'] if o['id']==shown['answer']),'text 17')
            answers.add(shown['answer'])
        self.assertGreater(len(answers),20);self.assertEqual(task,original)
        self.assertNotEqual(option_layout.prepare(task,1,'bundle','first-run')[0]['options'],option_layout.prepare(task,1,'bundle','next-run')[0]['options'])
    def test_names_normalize_without_guessing_versions_or_converting_units(self):
        self.assertEqual(run_naming.hardware('M3ULTRA 512gb'),'M3 Ultra 512 GB')
        self.assertEqual(run_naming.hardware('M3 ULTRA 512GB'),'M3 Ultra 512 GB')
        self.assertNotEqual(run_naming.hardware('M3 Ultra 512GB'),run_naming.hardware('M3 Ultra 512GiB'))
        manifest={'model_id':'Actual model ID','hardware':{'label':'M3 ULTRA 512gb','machine_key':'original'}}
        values={'run_name':'Old free text','server_name':'lmstudio','quantization':'q4_k_m'}
        before=copy.deepcopy((manifest,values));result=run_naming.describe(manifest,values)
        self.assertEqual(result['name'],'Old free text')
        self.assertEqual(result['generated_name'],'M3Ultra512GB-LM Studio-Actual model ID-Q4_K_M')
        self.assertEqual(result['legacy_label'],'Old free text');self.assertEqual(result['missing'],['server_version'])
        self.assertEqual((manifest,values),before)
        self.assertIn('hardware',run_naming.describe({},recorded_hardware={'label':'Hardware not recorded'})['missing'])
    def test_loopback_is_not_proof_of_local_inference(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(hardware_records.capture(Path(d),{'base_url':'http://127.0.0.1:38002/v1'}))
    def test_stale_review_is_rejected_before_any_queue_or_snapshot_write(self):
        with tempfile.TemporaryDirectory() as d,patch.object(web,'ROOT',Path(d)):
            (Path(d)/'models.json').write_text('{"models":[]}')
            with self.assertRaisesRegex(ValueError,'changed after review'):
                web.enqueue({'models_revision':'old','model':'fixture','tasks':['t']})
            self.assertFalse((Path(d)/'evaluations').exists())


class HardwareGroupTests(unittest.TestCase):
    def test_group_overlay_preserves_original_identity_and_rejects_overlapping_aliases(self):
        import hardware_groups
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);before={'label':'ExampleGPU 128gb','machine_key':'physical-one'}
            other={'label':'ExampleGPU 128 GB','machine_key':'physical-two'}
            saved=hardware_groups.save(root,{'revision':hardware_groups.revision(hardware_groups.load(root)),'groups':[{'label':'Equivalent GPUs','aliases':['ExampleGPU 128 GB']}]})
            a=hardware_groups.apply(root,before);b=hardware_groups.apply(root,other)
            self.assertEqual(a['comparison_key'],b['comparison_key'])
            self.assertNotEqual(a['machine_key'],b['machine_key']);self.assertEqual(before['label'],'ExampleGPU 128gb')
            self.assertEqual(a['original_label'],before['label'])
            with self.assertRaisesRegex(ValueError,'only one'):
                hardware_groups.save(root,{'revision':saved['revision'],'groups':[{'label':'First','aliases':['ExampleGPU 128gb']},{'label':'Second','aliases':['ExampleGPU 128 GB']}]})
            self.assertEqual(hardware_groups.snapshot(root)['revision'],saved['revision'])
    def test_unconfigured_download_has_no_owner_specific_groups(self):
        import hardware_groups
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);record={'label':'A user machine','machine_key':'physical'}
            self.assertEqual(hardware_groups.load(root),{'schema_version':1,'groups':[]})
            self.assertEqual(hardware_groups.apply(root,record),record)

if __name__=='__main__':unittest.main()
