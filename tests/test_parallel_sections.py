"""Workers must reproduce ordered contours, including conservative failures."""
import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
from optimization_cli import load_module
from test_layer_islands import cube
li=load_module('layer_islands');parallel=load_module('layer_parallel')


class ParallelSections(unittest.TestCase):
    def test_legacy_contour_numbers_are_local_to_shell_order(self):
        import importlib.util
        path=Path(__file__).with_name('reference')/'performance16_layer_islands.py'
        spec=importlib.util.spec_from_file_location('_legacy_part_ids',path)
        prior=importlib.util.module_from_spec(spec);spec.loader.exec_module(prior)
        shells=[cube((0,0,1),(2,2,3)),cube((4,0,1),(6,2,3))]
        records=[dict(id=0,point=[5,1,1])]
        first=prior.diagnose(shells,records)['points'][0]
        second=prior.diagnose(list(reversed(shells)),records)['points'][0]
        self.assertEqual(first['kind'],second['kind'])
        self.assertEqual(first['current_parts'],[1]);self.assertEqual(second['current_parts'],[0])

    def test_batched_polygon_classification_preserves_holes_and_epsilon_boundaries(self):
        import numpy as np
        poly=dict(outer=[[0,0],[4,0],[4,4],[0,4]],holes=[[[1,1],[1,3],[3,3],[3,1]]])
        rng=np.random.default_rng(16)
        points=rng.uniform(-1,5,size=(600,2)).tolist()
        for delta in [-li.EPS*1.01,-li.EPS,-li.EPS*.99,0,li.EPS*.99,li.EPS,li.EPS*1.01]:
            points.extend([[delta,2],[1+delta,2],[4+delta,2],[2,delta],[2,1+delta],[2,4+delta]])
        self.assertEqual(li.inside_many(poly,points).tolist(),[li.inside(poly,p) for p in points])
        self.assertEqual(li.inside_many(poly,[]).tolist(),[])

    def test_vector_sections_match_frozen_scalar_reference_on_rotated_meshes(self):
        import importlib.util
        import numpy as np
        path=Path(__file__).with_name('reference')/'performance16_layer_islands.py'
        spec=importlib.util.spec_from_file_location('_scalar_sections',path)
        prior=importlib.util.module_from_spec(spec);spec.loader.exec_module(prior)
        rng=np.random.default_rng(1601)
        for _ in range(12):
            xyz,faces=cube((-1,-1,-1),(1,1,1))
            rotation,_=np.linalg.qr(rng.normal(size=(3,3)))
            if np.linalg.det(rotation)<0:rotation[:,0]*=-1
            xyz=np.asarray(xyz)@rotation+rng.uniform(-3,3,size=3)
            shells=[(xyz,faces)]
            heights=list(xyz[:,2])+list(np.linspace(xyz[:,2].min()-.1,xyz[:,2].max()+.1,11))
            for z in heights:
                try:expected=prior.section(shells,z)
                except ValueError as error:
                    with self.assertRaisesRegex(ValueError,str(error)):li.section(shells,z)
                else:self.assertEqual(li.section(shells,z),expected)

    def test_worker_contours_and_errors_exactly_match_serial(self):
        xyz,faces=cube((0,0,1),(2,2,3))
        for shells in [[(xyz,faces)],[(xyz,faces[:-2])]]:
            prepared=li.prepare_sections(shells);heights=[.5,1.,1.08,1.16,2.,2.99,3.,4.]
            actual=parallel.sections(prepared,heights,2)
            self.assertIsNotNone(actual)
            for z in heights:
                try:expected=(li.section(shells,z,prepared),None)
                except (ValueError,FloatingPointError) as error:expected=(None,str(error))
                self.assertEqual(actual[z],expected)

    def test_parallel_diagnosis_matches_serial_including_support_footprints(self):
        shells=[cube((0,0,1),(2,2,3)),cube((1,1,3),(4,4,4))]
        records=[dict(id=i,point=[1,1,z]) for i,z in enumerate([1,1.08,1.16,2,3,3.08])]
        self.assertEqual(li.diagnose(shells,records,support_shells=shells,workers=0),
                         li.diagnose(shells,records,support_shells=shells,workers=2))

    def test_failed_process_launch_falls_back_to_identical_serial_diagnosis(self):
        shells=[cube((0,0,1),(2,2,3))];records=[dict(id=i,point=[1,1,1+i*.08]) for i in range(2)]
        expected=li.diagnose(shells,records,workers=0)
        with patch.object(parallel.subprocess,'Popen',side_effect=OSError('test launch failure')):
            self.assertEqual(li.diagnose(shells,records,workers=2),expected)

    def test_timed_out_workers_are_reaped_and_serial_fallback_available(self):
        prepared=li.prepare_sections([cube((0,0,1),(2,2,3))])
        launched=[];original=parallel.subprocess.Popen
        def launch(command,**kwargs):
            process=original(command,**kwargs);launched.append((process,Path(command[-1]).parent));return process
        with patch.object(parallel.subprocess,'Popen',side_effect=launch):
            self.assertIsNone(parallel.sections(prepared,[1.,2.],2,timeout=-1))
        self.assertEqual(len(launched),2)
        for process,folder in launched:
            self.assertIsNotNone(process.poll());self.assertFalse(folder.exists())


if __name__=='__main__':unittest.main()
