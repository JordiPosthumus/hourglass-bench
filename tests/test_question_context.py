import datetime as dt
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

import question_context
import report_charts
import score_report


def row(task, stamp, **extra):
    return {'evaluation_id':'fixture','task':task,'run':1,'status':'completed','solved':True,'ts':dt.datetime.fromtimestamp(stamp,dt.timezone.utc).isoformat(),**extra}


class ContextTests(unittest.TestCase):
    def test_timeline_excludes_pauses_and_includes_retries(self):
        job={'id':'fixture','state':'running','started':100,'current_task':'b','active_intervals':[{'start':100,'end':130},{'start':300,'end':None}]}
        manifest={'id':'fixture','expected':[{'task':'a','task_sha':'sha','repeat':1},{'task':'b','task_sha':'sha','repeat':1}]}
        entries={'a':{'task_sha':'sha','summary':'Count line crossings across two panels'},'b':{'task_sha':'sha','summary':'Choose camera coverage around a planet'}}
        rows=[row('a',120),row('b',125,status='error',solved=False)]
        result=question_context.timeline(job,manifest,rows,entries,320)
        self.assertEqual(result['end_s'],50)
        self.assertEqual([(p['task'],p['start_s'],p['end_s']) for p in result['spans']],[('a',0,20),('b',20,50)])
        self.assertEqual(result['spans'][-1]['status'],'Working')
        self.assertEqual(result['spans'][-1]['summary'],entries['b']['summary'])

    def test_timeout_remains_a_question_and_skipped_zeros_are_not_work(self):
        job={'id':'fixture','state':'stopped','started':100,'ended':1000,'current_task':'a'}
        manifest={'id':'fixture','expected':[{'task':'a','repeat':1},{'task':'b','repeat':1}]}
        result=question_context.timeline(job,manifest,[row('a',1000,status='timeout'),row('b',1000,score_reason='wrong_streak_limit')],{},1200)
        self.assertEqual(len(result['spans']),1)
        self.assertEqual(result['spans'][0]['status'],'Timed out')
        self.assertEqual(result['spans'][0]['end_s'],900)

    def test_stale_or_malformed_summaries_are_not_attached_to_other_versions(self):
        expected={'task':'a','task_sha':'correct'}
        for entry in ({'task_sha':'stale','summary':'Count line crossings across two panels'},[],{'task_sha':'correct','summary':'Too short'}):
            self.assertEqual(question_context.summary({'a':entry},expected),'Summary unavailable for this question version')

    def test_summary_catalogue_matches_every_available_question(self):
        root=Path(__file__).resolve().parents[1];entries=question_context.catalog(root)
        tasks=list((root/'examples').glob('*/task.json')) or list((root/'tasks').glob('*/task.json'))
        self.assertTrue(tasks)
        for task in tasks:
            entry=entries[task.parent.name]
            self.assertTrue(5<=len(entry['summary'].split())<=7)
            self.assertEqual(entry['task_sha'],hashlib.sha256(task.read_bytes()).hexdigest()[:16])

    def test_plot_allocates_room_for_all_run_labels(self):
        base={'model':'model','weighted_points':1,'state':'partial','curve':[{'seconds':0,'weighted':0},{'seconds':600,'weighted':1}]}
        two=ET.fromstring(report_charts.progress_chart([base]*2,legend=False))
        forty=ET.fromstring(report_charts.progress_chart([base]*40,legend=False))
        self.assertGreater(int(forty.attrib['height']),int(two.attrib['height']))
        self.assertEqual(len(forty.findall('.//{http://www.w3.org/2000/svg}g[@data-series]')),40)
        self.assertEqual(len(set(report_charts.color_for(i) for i in range(40))),40)

    def test_public_exports_do_not_include_local_question_context(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);expected=[{'task':'PRIVATE-ID','task_sha':'sha','repeat':1,'weight':1,'weight_version':'weighted-hour-v1'}]
            (root/'question-summaries.json').write_text(json.dumps({'questions':{'PRIVATE-ID':{'summary':'PRIVATE question content stays inside this bench','task_sha':'sha'}}}))
            job={'id':'fixture','model':'demo','state':'stopped','started':100,'ended':130,'tasks':['PRIVATE-ID']}
            manifest={'id':'fixture','expected':expected,'order':['PRIVATE-ID'],'benchmark_version':'2.5.0'}
            files=score_report.build(root,job,[row('PRIVATE-ID',120)],manifest)
            self.assertTrue(all('PRIVATE' not in value for value in files.values()))


if __name__=='__main__':unittest.main()
