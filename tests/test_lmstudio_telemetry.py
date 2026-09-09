import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import live_tps
import lmstudio_telemetry
from lmstudio_telemetry import Reader,timestamp

START=timestamp('2026-09-09 12:00:00')
def info(model,event,second=0):return f'[2026-09-09 12:00:{second:02d}][INFO][{model}] {event}'
def slot(action,number,task,detail,second=0):return f'[2026-09-09 12:00:{second:02d}][DEBUG] 01.00.000.000 I slot {action}: id {number} | task {task} | {detail}'
def begin(r,model='fixture',number=3,task=1,second=0):
 r.parse(info(model,'Running chat completion on conversation with 2 messages.',second))
 r.parse(slot('launch_slot_',number,task,'processing task, is_child = 0',second))
def decode(r,number=3,task=1,second=3):return r.parse(slot('print_timing',number,task,'n_gen = 165, tg = 54.90 t/s, tg_3s = 55.10 t/s',second))

class LmTelemetry(unittest.TestCase):
 def reader(self,**kw):return Reader('/fixture','fixture',START,**kw)
 def test_real_format_decode_preserves_timestamp_model_slot_and_request(self):
  r=self.reader();begin(r);s=decode(r)
  self.assertEqual((s['tps'],s['request_avg_tps'],s['at'],s['slot'],s['request_id']),(55.1,54.9,START+3,3,'1'))
  self.assertEqual(r.status()['observed_requests'],1)
  self.assertEqual(r.status()['server_phase'],'decode')
 def test_overlap_release_and_prefill_are_observed_without_inference(self):
  r=self.reader();begin(r);begin(r,number=2,task=2,second=1)
  self.assertEqual(decode(r)['observed_requests'],2)
  r.parse(slot('release',3,1,'stop processing: n_tokens = 100, truncated = 0',4))
  r.parse(info('fixture','Finished streaming response',4))
  self.assertEqual(r.status()['observed_requests'],1)
  self.assertEqual(r.status()['server_phase'],'prefill')
  r.parse(slot('release',2,2,'stop processing: n_tokens = 100, truncated = 0',5))
  self.assertEqual(r.status()['observed_requests'],0)
 def test_finished_previous_request_does_not_remove_new_pending_request(self):
  r=self.reader();begin(r)
  r.parse(slot('release',3,1,'stop processing: n_tokens = 100',3))
  r.parse(info('fixture','Running chat completion',3));r.parse(info('fixture','Finished streaming response',3))
  self.assertEqual(r.status()['observed_requests'],1)
 def test_other_models_count_for_overlap_but_not_this_models_speed(self):
  r=self.reader();begin(r);begin(r,'other',2,2,1)
  self.assertIsNone(decode(r,2,2))
  self.assertEqual(decode(r)['observed_requests'],2)
  self.assertEqual(r.status()['observed_model_requests'],1)
 def test_ambiguous_interleaving_fails_closed_and_prompts_are_not_captured(self):
  r=self.reader();r.parse(info('fixture','Running chat completion'));r.parse(info('other','Running chat completion'))
  r.parse(slot('launch_slot_',3,1,'processing task, is_child = 0'))
  self.assertIsNone(decode(r));self.assertIsNone(r.status()['observed_requests'])
  self.assertEqual(r.status()['attribution'],'ambiguous')
  self.assertIsNone(r.parse('PRIVATE PROMPT decoding chunk=23.95 t/s avg=24.01 t/s'))
  self.assertNotIn('PRIVATE PROMPT',json.dumps(r.status()))
 def test_pause_and_pre_run_requests_do_not_become_this_runs_samples(self):
  r=self.reader(intervals=[{'start':START+1,'end':START+4},{'start':START+20,'end':None}])
  begin(r,second=0);self.assertIsNone(decode(r))
  begin(r,number=2,task=2,second=2);self.assertIsNotNone(decode(r,2,2,3));self.assertIsNone(decode(r,2,2,10))
 def test_incremental_reads_partial_lines_rotation_and_no_false_freshness(self):
  with tempfile.TemporaryDirectory() as d:
   directory=Path(d)/'2026-09';directory.mkdir();p=directory/'a.log'
   lines=[info('fixture','Running chat completion'),slot('launch_slot_',3,1,'processing task, is_child = 0'),slot('print_timing',3,1,'n_gen = 165, tg = 54.90 t/s, tg_3s = 55.10 t/s',3)]
   p.write_text('\n'.join(lines))
   r=Reader(d,'fixture',START);self.assertEqual(r.poll(),[])
   with p.open('a') as f:f.write('\n')
   self.assertEqual(len(r.poll()),1);self.assertEqual(r.poll(),[])
   (directory/'b.log').write_text(slot('print_timing',3,1,'n_gen = 330, tg = 54.90 t/s, tg_3s = 55.10 t/s',6)+'\n')
   self.assertEqual(r.poll()[0]['at'],START+6)
   self.assertEqual(r.status()['last_server_event_at'],START+6)
 def test_endpoint_source_and_existing_remote_override_are_preserved(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'evaluations').mkdir();job={'id':'fixture','model':'saved'}
   (root/'evaluations/fixture.json').write_text(json.dumps({'model_config_snapshot':{'base_url':'http://localhost:1234/v1/','model':'fixture'}}))
   doc={'_endpoints':{'http://localhost:1234/v1':{'type':'lmstudio','log_dir':'/fixture'}}}
   (root/'telemetry-sources.json').write_text(json.dumps(doc));self.assertEqual(live_tps.source_for(root,job)['model_id'],'fixture')
   doc['saved']={'ssh_host':'existing','log_path':'/existing'};(root/'telemetry-sources.json').write_text(json.dumps(doc));self.assertEqual(live_tps.source_for(root,job)['ssh_host'],'existing')
 def test_missing_source_and_missing_logs_are_explicit(self):
  with tempfile.TemporaryDirectory() as d:
   snap=live_tps.snapshot(Path(d),{'id':'fixture','model':'fixture','state':'running'})
   self.assertIn('not connected',snap['error']);self.assertTrue(snap['stale'])
   with self.assertRaises(FileNotFoundError):Reader(d,'fixture',START).poll()
 def test_missing_launch_never_reports_zero_requests_while_decoding(self):
  r=self.reader();self.assertIsNone(decode(r));self.assertIsNone(r.status()['observed_requests'])
 def test_attached_collector_deduplicates_and_exits_when_run_stops(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'evaluations').mkdir();(root/'logs').mkdir()
   job={'id':'fixture','state':'running','started':START};manifest=root/'evaluations/fixture.json';manifest.write_text(json.dumps(job))
   reader=self.reader();begin(reader);sample=decode(reader)
   path=root/'logs/tps-fixture.jsonl';path.write_text(json.dumps(sample)+'\n')
   def stop(_):manifest.write_text(json.dumps({**job,'state':'stopped'}))
   with patch.object(Reader,'poll',return_value=[sample]),patch.object(lmstudio_telemetry.time,'sleep',side_effect=stop):
    lmstudio_telemetry.collect(root,job,{'log_dir':'/fixture','model_id':'fixture'},follow_manifest=True)
   rows=[json.loads(l) for l in path.read_text().splitlines()]
   self.assertEqual(sum(r.get('tps') is not None for r in rows),1)
   self.assertEqual(rows[-1]['phase'],'telemetry_status')
   self.assertFalse((root/'results/results.jsonl').exists())
