import datetime
import json
import subprocess
import unittest
import tempfile
from pathlib import Path

import diagnostics
import hour_score
import web


class RepositoryDiscoveryTests(unittest.TestCase):
    def test_external_private_backup_is_registered_in_both_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);workspace=root/'sandbox';workspace.mkdir()
            private=root/'external-bank'
            (root/'private-data-paths.json').write_text(json.dumps({'paths':[str(private)]}))
            for base in ('(version 1)\n(allow default)', '(version 1)\n(allow default)\n(deny network*)'):
                profile=diagnostics.protected_profile(base,[root],workspace)
                self.assertIn(f'(deny file-read* file-write* (subpath "{private.resolve()}"))',profile)
            (root/'private-data-paths.json').write_text(json.dumps({'paths':[str(workspace)]}))
            with self.assertRaises(ValueError):diagnostics.protected_profile('',[root],workspace)

    def cases(self):
        return [{'id':f'R{letter}{i:02d}', 'section':'repository_discovery', 'discovery_domain':domain}
                for i in range(1,6) for letter,domain in [('G','games'),('H','hourglass'),('D','dsg')]]

    def test_full_insertion_keeps_entire_existing_challenge_sequence(self):
        regular=[{'id':f'base-{i:03d}', 'section':('games','charts','math_logic')[i%3], 'tier':i%5+1} for i in range(100)]
        challenges=[{'id':f'challenge-{i:02d}', 'section':'challenge', 'challenge_rank':i} for i in range(20)]
        original=regular+challenges
        old=web.ordered_tasks(original,[t['id'] for t in original])
        cases=self.cases();catalog=original+cases
        result=web.ordered_tasks(catalog,[t['id'] for t in reversed(catalog)])
        self.assertEqual(len(result),135)
        self.assertEqual(len(set(result)),135)
        self.assertEqual([tid for tid in result if not tid.startswith('R')],old)
        self.assertEqual(result[8::9],[t['id'] for t in cases])
        self.assertEqual(web.ordered_tasks(catalog,[t['id'] for t in reversed(cases)]),[t['id'] for t in cases])
        self.assertEqual(web.ordered_tasks(catalog,['RG01','base-000','RG01']),['base-000','RG01'])

    def test_subtotals_preserve_scoring_and_browser_parity(self):
        expected=[{'task':t['id'],**t,'repeat':1,'weight':1,'vision':False} for t in self.cases()]
        job={'id':'test','expected':expected,'started':100,'ended':3800,'state':'done','scoring_policy':'net-hour-v2'}
        def row(tid,solved,at,reason=None):
            return {'task':tid,'evaluation_id':'test','solved':solved,'status':'completed','run':1,
                    'ts':datetime.datetime.fromtimestamp(at,datetime.timezone.utc).isoformat(),'score_reason':reason}
        rows=[row('RG01',False,150),row('RG01',True,160),row('RH01',False,180),row('RD01',False,190,'unsupported_vision'),row('RG02',True,3700),row('RD02',True,3700.001)]
        result=hour_score.score(job,rows,expected,3800)
        self.assertEqual(result['weighted_points'],1)
        self.assertEqual(result['repository_discovery'],{'games':{'points':2,'weighted_points':2,'completed_questions':2,'total_questions':5},'hourglass':{'points':0,'weighted_points':-1,'completed_questions':1,'total_questions':5},'dsg':{'points':0,'weighted_points':0,'completed_questions':1,'total_questions':5}})
        script="const {hourScore}=require('./ui/hour-score');const x=JSON.parse(process.argv[1]);console.log(JSON.stringify(hourScore(...x)))"
        browser=json.loads(subprocess.check_output(['node','-e',script,json.dumps([job,rows,expected,3800])],text=True))
        self.assertEqual(browser['repository_discovery'],result['repository_discovery'])
        self.assertEqual(browser['weighted_points'],result['weighted_points'])


if __name__=='__main__':unittest.main()
