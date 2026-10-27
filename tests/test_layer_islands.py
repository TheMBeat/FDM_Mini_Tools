import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from optimization_cli import load_module
li=load_module('layer_islands')

def poly(x0,y0,x1,y1):return dict(outer=[[x0,y0],[x1,y0],[x1,y1],[x0,y1]],holes=[])
def cube(low,high):
    x,y,z=low;X,Y,Z=high
    vertices=[(x,y,z),(X,y,z),(X,Y,z),(x,Y,z),(x,y,Z),(X,y,Z),(X,Y,Z),(x,Y,Z)]
    faces=[(0,2,1),(0,3,2),(4,5,6),(4,6,7),(0,1,5),(0,5,4),(1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7)]
    return vertices,faces

class LayerIslands(unittest.TestCase):
    def test_closed_cube_section_has_correct_inside_and_outside(self):
        parts=li.section([cube((0,0,1),(2,2,3))],2)
        self.assertEqual(len(parts),1);self.assertEqual(li.inside(parts[0],(1,1)),1)
        self.assertEqual(li.inside(parts[0],(3,1)),-1)

    def test_prepared_sections_match_independent_planes_and_preserve_face_ids(self):
        shells=[cube((0,0,1),(2,2,3)),cube((4,0,2),(6,2,5))]
        prepared=li.prepare_sections(shells)
        for z in [.5,1,1.01,2,2.5,3,4.99,5]:
            self.assertEqual(li.section(shells,z),li.section(shells,z,prepared))

    def test_diagnosis_prepares_once_including_incident_face_fallback(self):
        from unittest.mock import patch
        shells=[cube((0,0,1),(2,2,3))]
        records=[dict(id=i,point=[0,0,z]) for i,z in enumerate([1,1.08,1.16])]
        with patch.object(li,'prepare_sections',wraps=li.prepare_sections) as prepare:
            li.diagnose(shells,records,support_shells=shells)
        self.assertEqual(prepare.call_count,2)

    def test_hole_is_not_material(self):
        p=poly(0,0,4,4);p['holes']=[[[1,1],[1,3],[3,3],[3,1]]]
        self.assertEqual(li.inside(p,(2,2)),-1)
        self.assertFalse(li.overlap(p,poly(1.2,1.2,2.8,2.8)))

    def test_identical_contours_overlap_without_boundary_crossings(self):
        self.assertTrue(li.overlap(poly(0,0,2,2),poly(0,0,2,2)))

    def test_zero_width_touch_is_not_a_confirmed_anchor(self):
        self.assertFalse(li.overlap(poly(0,0,1,1),poly(1,0,2,1)))

    def test_overlapping_shells_form_one_component_not_xor(self):
        self.assertEqual(len(li.components([poly(0,0,2,2),poly(1,1,3,3)])),1)

    def test_detached_birth_is_a_true_section_island(self):
        result=li.diagnose([cube((0,0,3),(2,2,4))],[dict(id=0,point=[1,1,3])])
        self.assertEqual(result['points'][0]['kind'],'NEW_ISLAND')
        self.assertFalse(result['points'][0]['support_removal_allowed'])

    def test_anchor_does_not_prove_long_cantilever_or_enable_removal(self):
        shells=[cube((0,0,0),(1,1,4)),cube((.5,0,3),(6,1,4))]
        row=li.diagnose(shells,[dict(id=0,point=[5,.5,3])])['points'][0]
        self.assertEqual(row['kind'],'ANCHORED_OVERHANG')
        self.assertFalse(row['local_previous_model_footprint'])
        self.assertFalse(row['support_removal_allowed'])

    def test_previous_material_is_different_from_a_rooting_certificate(self):
        row=li.diagnose([cube((0,0,2),(2,2,4))],[dict(id=0,point=[1,1,3])])['points'][0]
        self.assertTrue(row['local_previous_model_footprint'])
        self.assertFalse(row['local_previous_material_rooting_verified'])

    def test_open_section_is_uncertain_and_never_accepted(self):
        vertices,faces=cube((0,0,3),(2,2,4));faces=faces[:-2]
        row=li.diagnose([(vertices,faces)],[dict(id=0,point=[1,1,3])])['points'][0]
        self.assertEqual(row['kind'],'UNCERTAIN_SECTION');self.assertFalse(row['certain'])

    def test_layer_phase_uses_first_layer_then_profile_height(self):
        row=li.diagnose([cube((0,0,3),(2,2,4))],[dict(id=0,point=[1,1,3])])['points'][0]
        self.assertAlmostEqual(row['z_mm'],3.04);self.assertAlmostEqual(row['previous_z_mm'],2.96)

if __name__=='__main__':unittest.main()
