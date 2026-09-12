import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

import score_report


NS = '{http://www.w3.org/2000/svg}'
BASE = {'state': 'in_progress', 'window_s': 3600, 'elapsed_s': 600,
        'resolved_questions': 1, 'total_questions': 3, 'points': 1,
        'incorrect_questions': 0, 'weighted_points': 1,
        'total_available_points': 3, 'resolved_available_points': 1,
        'auc_point_seconds': 0, 'score_denominator_point_seconds': 54,
        'scoring_policy': 'net-hour-v2'}


def report(name, value, state='final', prediction=None):
    return {'model': name, 'hourglass_score': value, 'state': state,
            'prediction': {'hourglass_score': prediction} if prediction is not None else None,
            'hardware': {'label': 'Test machine · 512 GB'}, 'machine_key': 'one',
            'bank_fingerprint': 'same', 'benchmark_version': '3.0.0',
            'scoring': 'net-hour-v2', 'timing_policy': 'hour-v1',
            'execution': {'question_timeout_s': 900}}


class RankingChartTests(unittest.TestCase):
    def test_ranks_only_recorded_totals_including_live_and_partial(self):
        reports=[report('live',.2,'in_progress',1000),report('complete',20),
                 report('partial',.1,'partial',999),report('negative',-4),report('waiting',0,'in_progress')]
        before=copy.deepcopy(reports)
        svg=score_report.ranking(reports,'history')['ranking.svg']
        groups=ET.fromstring(svg).findall(f'.//{NS}g[@data-rank]')
        self.assertEqual([g.attrib['data-model'] for g in groups],['complete','live','partial','waiting','negative'])
        self.assertEqual([g.attrib['data-score'] for g in groups],['20','0.2','0.1','0','-4'])
        self.assertIn('not extrapolated',svg)
        self.assertNotIn('Predicted final',svg)
        self.assertEqual(reports,before)

    def test_full_angled_labels_fit_canvas_and_disclose_rules(self):
        reports = [report('A <revision> & ' + 'very-long-model-name-' * 12, 30), report('Other model', 10)]
        root = ET.fromstring(score_report.ranking(reports)['ranking.svg'])
        width, height = float(root.attrib['width']), float(root.attrib['height'])
        for r, label in zip(reports, root.findall(f'.//{NS}g[@data-name-for]')):
            self.assertIn('rotate(-45)', label.attrib['transform'])
            visible = ''.join(label.itertext())
            self.assertIn(''.join(r['model'].split()), ''.join(visible.split()))
            self.assertIn('512 GB', visible)
            self.assertIn('net-hour-v2', visible)
            self.assertNotIn('…', visible)
            x, y, w, h = map(float, label.attrib['data-label-bounds'].split(','))
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x + w, width)
            self.assertLessEqual(y + h, height)

    def test_scope_and_unavailable_scores_are_preserved(self):
        reports = [report('correct-machine', 12), {**report('other-machine', 20), 'machine_key': 'two'}, report('unknown-score', None)]
        svg = score_report.ranking(reports)['ranking.svg']
        self.assertIn('correct-machine', svg)
        self.assertNotIn('other-machine', svg)
        self.assertNotIn('unknown-score', svg)
        empty = score_report.ranking([report('unknown', None)])['ranking.svg']
        self.assertIn('No comparable Hourglass scores available', empty)


if __name__ == '__main__':
    unittest.main()
