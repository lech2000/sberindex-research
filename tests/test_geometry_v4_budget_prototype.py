import sys,unittest
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'economic-atlas/src'))
from geometry_v4_budget_prototype import ConservedBudget,BudgetStop
class Budget(unittest.TestCase):
 def setUp(self):self.time=100.;self.b=ConservedBudget(lambda:self.time,startup_charge=82.)
 def check(self,stage='full_real',**kw):
  args=dict(own_tree_rss=1,free_bytes=1073741824,output_bytes=0,threads=1,native_preflight_pass=True);args.update(kw);return self.b.check(stage,**args)
 def test_all_stages_conserve_startup(self):
  self.time+=100;self.assertEqual(self.check()['elapsed_seconds'],182.)
  self.time+=200;self.assertEqual(self.check('full_controls_210')['elapsed_seconds'],382.)
  self.time+=100;self.assertEqual(self.check('finalization')['elapsed_seconds'],482.)
 def test_exact_wall_stop_no_restart(self):
  self.time+=4118
  with self.assertRaises(BudgetStop):self.check()
  self.time=100
  with self.assertRaises(BudgetStop):self.check()
 def test_invalid_measurement_and_resource_limits(self):
  for kw in [dict(own_tree_rss=None),dict(own_tree_rss=True),dict(own_tree_rss=1073741825),dict(free_bytes=0),dict(output_bytes=268435457),dict(native_preflight_pass=False),dict(threads=2)]:
   self.b=ConservedBudget(lambda:self.time)
   with self.assertRaises(BudgetStop):self.check(**kw)
 def test_stage_or_clock_cannot_reset(self):
  self.check('full_controls_210')
  with self.assertRaises(BudgetStop):self.check('full_real')
  self.b=ConservedBudget(lambda:self.time);self.time-=1
  with self.assertRaises(BudgetStop):self.check()
if __name__=='__main__':unittest.main()
