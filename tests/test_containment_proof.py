import math,random,unittest
from optimization_cli import load_module
proof=load_module('containment')

def nearest_sphere(point):
 length=math.dist(point,(0,0,0));return ((1,0,0),(1,0,0),0,abs(length-1))
def outside_sphere(point):return math.dist(point,(0,0,0))>1

class ContainmentProof(unittest.TestCase):
 def classify(self,points,faces,eligible=None,nearest=nearest_sphere,outside=outside_sphere,guard=.0001):
  return proof.classify(points,faces,[True]*len(points) if eligible is None else eligible,nearest,outside,guard)
 def test_clear_connected_outside_region_uses_one_membership_query(self):
  points=[(3,0,0),(3,.1,0),(3,.2,0)];r=self.classify(points,[(0,1,2)])
  self.assertEqual(r['winding_queries'],1);self.assertEqual(r['inside'],0);self.assertEqual(r['certified_links'],2)
 def test_inside_region_still_rejects_every_vertex(self):
  r=self.classify([(0,0,0),(.1,0,0),(0,.1,0)],[(0,1,2)])
  self.assertEqual(r['inside'],3);self.assertEqual(r['winding_queries'],1)
 def test_edge_crossing_surface_cannot_reuse_membership(self):
  r=self.classify([(0,0,0),(2,0,0)],[(0,1,1)])
  self.assertEqual(r['inside'],1);self.assertEqual(r['winding_queries'],2);self.assertEqual(r['certified_links'],0)
 def test_outside_endpoints_with_obstacle_between_do_not_join(self):
  r=self.classify([(-2,0,0),(2,0,0)],[(0,1,1)])
  self.assertEqual(r['winding_queries'],2);self.assertEqual(r['certified_links'],0)
 def test_approved_vertex_does_not_bridge_two_regions(self):
  r=self.classify([(0,0,0),(1,0,0),(2,0,0)],[(0,1,1),(1,2,2)],[True,False,True])
  self.assertEqual(r['inside'],1);self.assertEqual(r['winding_queries'],2)
 def test_uncertain_or_touching_distances_stay_individual(self):
  for value in [0.,float('nan'),float('inf')]:
   near=lambda p:((0,0,0),(1,0,0),0,value)
   r=self.classify([(3,0,0),(3,.01,0)],[(0,1,1)],nearest=near)
   self.assertEqual(r['winding_queries'],2)
 def test_roundoff_guard_grows_and_never_weakens_tolerance(self):
  self.assertGreaterEqual(proof.roundoff_guard(1),.0001)
  self.assertGreater(proof.roundoff_guard(1000000),proof.roundoff_guard(10))
 def test_seeded_random_mesh_graph_matches_all_vertex_reference(self):
  rng=random.Random(151)
  for _ in range(20):
   points=[tuple(rng.uniform(-2,2) for _ in range(3)) for i in range(100)]
   faces=[tuple(rng.randrange(len(points)) for _ in range(3)) for i in range(200)]
   r=self.classify(points,faces)
   self.assertEqual(r['inside'],sum(not outside_sphere(p) for p in points))
 def test_disconnected_and_empty_graphs_keep_independent_witnesses(self):
  r=self.classify([(0,0,0),(2,0,0)],[]);self.assertEqual(r['winding_queries'],2)
  r=self.classify([],[]);self.assertEqual(r['winding_queries'],0)
 def test_invalid_guard_and_mask_fail(self):
  for guard in [0.,-1.,float('nan')]:
   with self.assertRaises(ValueError):self.classify([(0,0,0)],[],guard=guard)
  with self.assertRaises(ValueError):self.classify([(0,0,0)],[],[])

if __name__=='__main__':unittest.main()
