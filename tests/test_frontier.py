import tempfile,unittest
from pathlib import Path
import hourglass
class FrontierNullTierTests(unittest.TestCase):
 def report(self,rows):
  with tempfile.TemporaryDirectory() as d:
   hourglass.cmd_frontier(None,rows=rows,root=Path(d),emit=False)
   return (Path(d)/'frontier.md').read_text()
 def row(self,tier,solved=True):return {'model':'fixture','benchmark_version':'2.0.0','tier':tier,'solved':solved,'status':'completed','duration_s':10,'tok_per_s':5}
 def test_null_tiers_keep_accuracy_and_time_without_crashing(self):
  text=self.report([self.row(None),self.row(2,False)])
  self.assertIn('| 2.0.0 · fixture | 0.50 | 10s | 5.0 | 180.00 | 0.00 |',text)
 def test_all_null_or_zero_tiers_show_unavailable_weighted_metric(self):
  text=self.report([self.row(None),self.row(0)])
  self.assertIn('| 1.00 | 10s | 5.0 | 360.00 | — |',text)
 def test_numeric_tier_weighting_is_preserved(self):
  text=self.report([self.row(3),self.row(1,False)])
  self.assertIn('| 0.75 |',text)
