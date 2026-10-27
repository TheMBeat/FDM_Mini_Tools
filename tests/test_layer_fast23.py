import importlib.util, math, random, unittest
from pathlib import Path
from test_layer_islands import li, poly, cube
p=Path(__file__).parent/'reference/performance22_layer_islands.py'
spec=importlib.util.spec_from_file_location('reference22',p);prior=importlib.util.module_from_spec(spec);spec.loader.exec_module(prior)

class FastLayers23(unittest.TestCase):
    def test_overlap_matches_reference_for_concave_holes_nested_and_touching(self):
        rng=random.Random(23026)
        shapes=[poly(0,0,4,4),poly(1,1,3,3),poly(4,0,5,1)]
        hole=poly(0,0,4,4);hole['holes']=[[[1,1],[1,3],[3,3],[3,1]]];shapes.append(hole)
        for n in range(20):
            x,y=rng.uniform(-5,5),rng.uniform(-5,5)
            points=[]
            for i in range(97):
                a=2*math.pi*i/97;r=2+.7*math.sin(7*a)
                points.append([x+r*math.cos(a),y+r*math.sin(a)])
            shapes.append(dict(outer=points,holes=[]))
        for a in shapes:
            for b in shapes:self.assertEqual(li.overlap(a,b),prior.overlap(a,b))

    def test_local_component_follows_indirect_bridges(self):
        import numpy as np
        polygons=[poly(0,0,2,2),poly(1,.2,3,2.2),poly(2.5,.4,4,2.4),poly(10,0,11,1)]
        bounds=[(np.asarray(p['outer']).min(axis=0),np.asarray(p['outer']).max(axis=0)) for p in polygons]
        self.assertEqual(li._connected_parts(polygons,[0],bounds,{}),[0,1,2])

    def test_local_components_match_full_graph_for_random_seed_sets(self):
        import numpy as np
        rng=random.Random(237)
        for _ in range(30):
            polygons=[]
            for i in range(12):
                x,y=rng.uniform(-5,5),rng.uniform(-5,5)
                polygons.append(poly(x,y,x+3,y+3))
            bounds=[(np.asarray(p['outer']).min(axis=0),np.asarray(p['outer']).max(axis=0)) for p in polygons]
            groups=prior.components(polygons)
            for seeds in ([0],[3],[0,7],[]):
                expected=sorted(i for group in groups if set(group).intersection(seeds) for i in group)
                self.assertEqual(li._connected_parts(polygons,seeds,bounds,{}),expected)

    def test_boundary_and_thin_crossing_match_reference(self):
        a=poly(0,0,1,1)
        for offset in [-2e-7,-1e-8,0,1e-8,2e-7]:
            b=poly(1+offset,0,2,1)
            self.assertEqual(li.overlap(a,b),prior.overlap(a,b))
        self.assertTrue(li.overlap(poly(-5,-.001,5,.001),poly(-.001,-5,.001,5)))

    def test_full_diagnoses_equal_for_shared_layers_and_islands(self):
        shells=[cube((0,0,0),(1,1,4)),cube((.5,0,3),(6,1,4)),cube((8,0,2),(9,1,4))]
        records=[dict(id=i,point=p) for i,p in enumerate([[0,0,3],[1,.5,3],[5,.5,3],[8.5,.5,2],[8.5,.5,3],[15,15,3]])]
        self.assertEqual(li.diagnose(shells,records,workers=0),prior.diagnose(shells,records,workers=0))

    def test_priority_classification_matches_complete_report(self):
        shells=[cube((0,0,0),(1,1,4)),cube((.5,0,3),(6,1,4)),cube((8,0,2),(9,1,4))]
        records=[dict(id=i,point=p) for i,p in enumerate([[0,0,3],[1,.5,3],[5,.5,3],[8.5,.5,2],[8.5,.5,3],[15,15,3]])]
        full=prior.diagnose(shells,records,workers=0)
        quick=li.diagnose(shells,records,workers=0,classification_only=True)
        for a,b in zip(full['points'],quick['points']):
            for key in ('id','point','kind','certain','support_removal_allowed'):self.assertEqual(a[key],b[key])
            self.assertNotIn('current_contours',b)
        self.assertEqual(full['counts'],quick['counts'])

    def test_uncertain_open_sections_remain_uncertain(self):
        vertices,faces=cube((0,0,3),(2,2,4));shells=[(vertices,faces[:-2])]
        records=[dict(id=0,point=[1,1,3])]
        self.assertEqual(li.diagnose(shells,records,workers=0),prior.diagnose(shells,records,workers=0))

if __name__=='__main__':unittest.main()
