import unittest
from types import SimpleNamespace
from optimization_cli import load_module
b=load_module('support_budget')

class BudgetPolicy(unittest.TestCase):
 def setUp(self):
  self.now=[0.];self.collider=SimpleNamespace()
  self.budget=b.RecoveryBudget(dict(tree_recovery_seconds=10,tree_recovery_region_seconds=2),clock=lambda:self.now[0])
  self.collider.recovery_budget=self.budget
 def test_region_time_restores_collider(self):
  @b.contact_budget
  def choose(p,c,cfg):self.now[0]+=3;c._active_search_budget.check();return 'bad',{}
  result,detail=choose((0,0,1),self.collider,{})
  self.assertIsNone(result);self.assertTrue(detail['budget_exhausted'])
  self.assertIsNone(self.collider._active_search_budget)
  self.assertEqual(self.budget.summary()['exhausted'][0]['reason'],'search_region_time_budget')
 def test_cumulative_region_cannot_restart(self):
  with self.budget.region(self.collider,(0,0,1)):self.now[0]+=1.5
  with self.budget.region(self.collider,(0,0,1)):
   self.now[0]+=.6
   with self.assertRaisesRegex(b.SearchLimit,'region_time'):self.budget.check()
  with self.budget.region(self.collider,(1,0,1)):self.budget.check()
 def test_global_time_across_regions(self):
  self.budget.total_seconds=1
  with self.budget.region(self.collider,(0,0,1)):self.now[0]+=1.1
  with self.assertRaisesRegex(b.SearchLimit,'global_time'):
   with self.budget.region(self.collider,(1,0,1)):pass
 def test_work_limit_is_deterministic(self):
  self.budget.region_queries=2
  with self.budget.region(self.collider,(0,0,1)):
   self.budget.check()
   with self.assertRaisesRegex(b.SearchLimit,'region_work'):self.budget.check()
 def test_no_manager_keeps_reference_path(self):
  @b.contact_budget
  def choose(p,c,cfg):return 'verified',{'p':p}
  self.assertEqual(choose((0,0,1),object(),{})[0],'verified')
 def test_other_failure_is_not_masked(self):
  @b.contact_budget
  def choose(p,c,cfg):raise ValueError('bad geometry')
  with self.assertRaisesRegex(ValueError,'bad geometry'):choose((0,0,1),self.collider,{})
  self.assertIsNone(self.collider._active_search_budget)
 def test_disabled_work_budget_never_accepts_fake_success(self):
  self.budget.total_queries=0
  @b.contact_budget
  def choose(p,c,cfg):return 'unsafe',{}
  result,detail=choose({'point':[0,0,1]},self.collider,{})
  self.assertIsNone(result);self.assertIn('search_global_work_budget',detail['reasons'])

 def test_keyword_call_keeps_record_signature(self):
  @b.contact_budget
  def choose(record,collider,cfg):return 'verified',record
  self.assertEqual(choose(record={'point':[0,0,1]},collider=self.collider,cfg={})[0],'verified')

 def test_part_quotas_do_not_multiply_global_budget(self):
  cfg={'tree_recovery_seconds':20,'tree_recovery_region_seconds':3}
  parts=b.part_config(cfg,4)
  self.assertEqual(parts['tree_recovery_seconds']*4,20)
  self.assertEqual(parts['tree_recovery_queries']*4,2400000)
  self.assertNotIn('tree_recovery_queries',cfg)

if __name__=='__main__':unittest.main()
