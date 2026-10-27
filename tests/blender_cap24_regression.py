"""Bounded Boolean cap repair: topology, displacement and rollback."""
import sys,unittest
from pathlib import Path
import bpy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fdm_mini_tools import tree_mesh as tm,core
class CapRepair(unittest.TestCase):
 def setUp(self):core.clear_scene(purge=False)
 def seam(self,offset=1e-7):
  vertices=[(0,0,0),(1,0,0),(1,1,0),(0,1,0),(0,0,1),(1,0,1),(1,1,1),(0,1,1),(offset,0,0)]
  faces=[(8,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]
  return tm._object('CAP_SEAM',vertices,faces)
 def test_local_duplicate_repairs_closed_solid_with_bounded_motion(self):
  obj=self.seam();self.assertTrue(tm._repair_cap_duplicates(obj,(0,8)))
  qa=tm.topology(obj);self.assertTrue(qa['pass'],qa)
  self.assertEqual(obj['fdm_tree_cap_endpoint_welds'],1)
  self.assertLessEqual(obj['fdm_tree_cap_max_displacement_mm'],.000002)
  self.assertAlmostEqual(qa['volume_mm3'],1.,places=6)
 def test_distinct_endpoints_are_never_welded(self):
  obj=self.seam(.00003);old=obj.data
  self.assertFalse(tm._repair_cap_duplicates(obj,(0,8)));self.assertEqual(obj.data,old)
 def test_failed_topology_rolls_back_mesh_and_does_not_leak(self):
  obj=tm._object('OPEN',[(0,0,0),(1,0,0),(0,1,0),(1e-7,0,0)],[(0,1,2),(3,2,1)])
  old=obj.data;count=len(bpy.data.meshes)
  self.assertFalse(tm._repair_cap_duplicates(obj,(0,3)))
  self.assertEqual(obj.data,old);self.assertEqual(len(bpy.data.meshes),count)
 def test_only_failed_cap_vertices_are_candidates(self):
  obj=self.seam();self.assertFalse(tm._repair_cap_duplicates(obj,(1,2,3)))
  self.assertEqual(len(obj.data.vertices),9)
 def test_patch_recovery_is_bounded_and_failed_candidates_stay_unrecovered(self):
  from unittest.mock import patch
  from fdm_mini_tools import tree_support as ts,contact_audit,contact_completion
  from mathutils import Vector
  sys.path.insert(0,str(Path(__file__).resolve().parent))
  from diagnose_tree_blender import box
  model=box('MINI',(-2,-2,10),(2,2,11));points=tm._object('POINTS',[(0,0,10)],[])
  cfg=core.config_from_preset('BALANCED',support_strategy='FDM_TREE',tree_required_minima=True,
      tree_complete_contacts=True,tree_show_missing=False)
  regions=[dict(point=[100+i,0,10],area_mm2=30-i,patch_ids=[i]) for i in range(20)]
  fake=dict(regions=regions,patches=[],missing_count=20,raw_missing_patches=20,radius_mm=2.)
  with patch.object(contact_audit,'audit',return_value=fake), patch.object(contact_completion,'choose',return_value=(None,{'point':[0,0,0],'reasons':{'test_no_route':1}})):
   support,stats=ts.generate_tree_supports(model,points,cfg)
  patch_stats=stats['completion']['surface_patches']
  self.assertEqual(len(patch_stats['attempted']),16)
  self.assertEqual(patch_stats['recovered'],0)
  self.assertEqual([r['point'][0] for r in patch_stats['attempted']],list(range(100,116)))
  self.assertTrue(stats['mesh_qa']['pass'])
if __name__=='__main__':
 suite=unittest.defaultTestLoader.loadTestsFromTestCase(CapRepair)
 result=unittest.TextTestRunner(verbosity=2).run(suite)
 if not result.wasSuccessful():raise RuntimeError('cap regression failed')
