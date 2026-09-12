import copy
import math
import re
import unittest
import xml.etree.ElementTree as ET

import report_charts
import score_report


NS = '{http://www.w3.org/2000/svg}'


def report(index, accuracy=1, tokens=1000, speed=1):
    return {
        'model': f'model-{index}',
        'display_name': f'machine-{index}-512GB-engine (0.1.dev20073+g8e685d198)-model-27b-optimized-quality-fp16-XXX',
        'hardware': {'label': f'Computer {index} · 512 GB'},
        'machine_key': 'test', 'bank_fingerprint': 'test',
        'benchmark_version': '3.0.0', 'scoring': 'net-hour-v2',
        'timing_policy': 'hour-v1', 'state': 'final',
        'efficiency': {'token_data_complete': True, 'accuracy': accuracy,
                       'median_output_tokens': tokens, 'scored_answers': 10,
                       'answers_per_active_minute': speed},
    }


class ChartLabelTests(unittest.TestCase):
    def assert_layout(self, reports):
        before = copy.deepcopy(reports)
        svg = score_report.quadrants(reports, 'history')['quadrants.svg']
        self.assertEqual(reports, before)
        root = ET.fromstring(svg)
        labels = root.findall(f'.//{NS}g[@data-label-for]')
        circles = root.findall(f'.//{NS}circle[@data-point]')
        leaders = root.findall(f'.//{NS}path[@data-leader-for]')
        self.assertEqual(len(labels), len(reports))
        self.assertEqual(len(leaders), len(reports))
        boxes = [dict(zip(('x', 'y', 'w', 'h'), map(float, label.attrib['data-box'].split(',')))) for label in labels]
        points = [{'x': float(c.attrib['cx']), 'y': float(c.attrib['cy']), 'r': float(c.attrib['r'])} for c in circles]
        for i, (label, box) in enumerate(zip(labels, boxes)):
            visible = ''.join(label.itertext())
            expected = reports[i]['display_name']
            self.assertEqual(''.join(visible.split()), ''.join(expected.split()))
            self.assertEqual(label.findall(f'{NS}rect'), [])
            self.assertNotIn('…', visible)
            self.assertGreaterEqual(box['x'], 0)
            self.assertGreaterEqual(box['y'], 0)
            self.assertLessEqual(box['x'] + box['w'], float(root.attrib['width']))
            self.assertLessEqual(box['y'] + box['h'], float(root.attrib['height']))
            for other in boxes[i + 1:]:
                self.assertFalse(report_charts.boxes_overlap(box, other, 7.9))
            for point in points:
                self.assertFalse(report_charts.box_hits_circle(box, point, 6.9))
            for text in label.findall(f'{NS}text'):
                self.assertEqual(text.attrib['font-size'], '9')
                self.assertLessEqual(report_charts.text_width(text.text, int(text.attrib['font-size'])), box['w'] - 15.9)
        for leader in leaders:
            index = int(leader.attrib['data-leader-for'])
            coords = list(map(float, re.findall(r'-?\d+(?:\.\d+)?', leader.attrib['d'])))
            route = list(zip(coords[::2], coords[1::2]))
            for a, b in zip(route, route[1:]):
                for i, box in enumerate(boxes):
                    if i != index:
                        self.assertFalse(report_charts.segment_hits_box((*a, *b), box, 1.9))
        return root, boxes, points

    def test_dense_top_edge_retains_names_and_original_data_geometry(self):
        reports = [report(i, a, t, s) for i, (a, t, s) in enumerate([
            (1, 14144, .28), (.8, 1466, .58), (1, 1304, .5),
            (.96, 1451, .42), (1, 2688, .17),
        ])]
        root, _, _ = self.assert_layout(reports)
        self.assertEqual(root.attrib['data-label-layout'], 'near')
        self.assertEqual(ET.tostring(root), ET.tostring(ET.fromstring(score_report.quadrants(reports, 'history')['quadrants.svg'])))
        circles = {int(c.attrib['data-point']): c for c in root.findall(f'.//{NS}circle')}
        for i, r in enumerate(reports):
            e = r['efficiency']
            self.assertAlmostEqual(float(circles[i].attrib['cx']), 840 - (math.log10(e['median_output_tokens']) - 3) / 2 * 750)
            self.assertAlmostEqual(float(circles[i].attrib['r']) ** 2, 400 * e['answers_per_active_minute'] / .58)
        self.assertAlmostEqual(float(circles[1].attrib['cy']) - float(circles[0].attrib['cy']), .2 / .23 * 390)

    def test_coincident_points_keep_all_labels_and_route_around_them(self):
        for count in (2, 6, 16):
            with self.subTest(count=count):
                self.assert_layout([report(i) for i in range(count)])

    def test_long_unicode_and_unbroken_names_stay_visible(self):
        reports = [report(i, a, t) for i, (a, t) in enumerate([(0, 1), (1, 1000), (.5, 10)])]
        reports[0]['display_name'] = '超長いモデル名' * 12
        reports[1]['display_name'] = 'W' * 160
        reports[2]['display_name'] = 'Engine & build <revision> · ' + 'very-long-identifier-' * 15
        self.assert_layout(reports)

    def test_quadrant_captions_move_clear_of_observations(self):
        reports = [report(0, 0, 1000), report(1, 1, 100000), report(2, 1 - 40 / 390, 1100)]
        root, boxes, points = self.assert_layout(reports)
        for text in root.findall(f'.//{NS}text'):
            if not (text.text or '').startswith(('ACCURATE ·', 'LESS ACCURATE ·')):
                continue
            width = report_charts.text_width(text.text, 10)
            box = {'x': float(text.attrib['x']) - (width if text.attrib['text-anchor'] == 'end' else 0),
                   'y': float(text.attrib['y']) - 12, 'w': width, 'h': 16}
            for point in points:
                self.assertFalse(report_charts.box_hits_circle(box, point, 5.9))
            for label in boxes:
                self.assertFalse(report_charts.boxes_overlap(box, label, 7.9))

    def test_empty_token_comparison_still_renders(self):
        r = report(0)
        r['efficiency']['token_data_complete'] = False
        svg = score_report.quadrants([r])['quadrants.svg']
        self.assertIn('No complete output-token records', svg)
        self.assertEqual(len(ET.fromstring(svg).findall(f'.//{NS}circle')), 0)


if __name__ == '__main__':
    unittest.main()
