import unittest
import web
class DifficultyCycleTests(unittest.TestCase):
 def test_full_bank_cycles_and_preserves_every_question(self):
  catalog=[{'id':f'{section}-{tier}-{n}','section':section,'tier':tier} for section,tiers in [('chart',range(1,11)),('games',range(1,6)),('math_logic',(1,5,9))] for tier in tiers for n in range(2)]
  ids=[t['id'] for t in catalog];order=web.ordered_tasks(catalog,ids);lookup={t['id']:t for t in catalog}
  self.assertEqual(set(order),set(ids));self.assertEqual(len(order),len(ids))
  self.assertEqual(order,web.ordered_tasks(list(reversed(catalog)),list(reversed(ids))))
  self.assertEqual([web.difficulty_band(lookup[t]) for t in order[:9]],['easy','medium','hard']*3)
  for band in ('easy','medium','hard'):
   sections=[lookup[t]['section'] for t in order if web.difficulty_band(lookup[t])==band]
   self.assertGreater(len(set(sections[:3])),1)
 def test_category_scales_and_exhausted_bands(self):
  self.assertEqual([web.difficulty_band({'section':'games','tier':t}) for t in (1,2,3,4,5)],['easy','easy','medium','hard','hard'])
  tasks=[{'id':str(t),'section':'chart','tier':t} for t in (1,2,4,8,9,10)]
  order=web.ordered_tasks(tasks,[t['id'] for t in tasks]);self.assertEqual(order,['1','4','8','2','9','10'])
