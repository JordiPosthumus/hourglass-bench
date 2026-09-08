import unittest
import run_tracking as rt
class LiveSplitTests(unittest.TestCase):
 def test_partial_repeats_retry_errors_and_unattempted_zeros(self):
  m={'expected':[{'task':'t','repeat':2,'vision':False},{'task':'v','repeat':1,'vision':True},{'task':'skip','repeat':1,'vision':True}]}
  rows=[{'task':'t','run':1,'status':'error'},{'task':'t','run':1,'status':'completed','solved':True},{'task':'v','run':1,'status':'completed','solved':False},{'task':'skip','run':1,'status':'completed','solved':False,'score_reason':'wrong_streak_limit'}]
  p=rt.progress(m,rows,{'elapsed_s':10},100);t=p['breakdown']['text'];v=p['breakdown']['vision']
  self.assertEqual(t['points'],.5);self.assertEqual(t['finished_questions'],0);self.assertEqual(t['accuracy'],1);self.assertEqual(t['errors'],1)
  self.assertEqual(v['points'],0);self.assertEqual(v['total_questions'],2);self.assertEqual(v['finished_questions'],2);self.assertEqual(v['scored_attempts'],1);self.assertEqual(v['not_attempted'],1)
  self.assertEqual(p['points'],t['points']+v['points'])
 def test_empty_vision_lane_is_unknown_accuracy(self):
  p=rt.progress({'expected':[{'task':'t','repeat':1,'vision':False}]},[],{'elapsed_s':0},0)
  self.assertIsNone(p['breakdown']['vision']['accuracy']);self.assertEqual(p['breakdown']['vision']['total_questions'],0)
