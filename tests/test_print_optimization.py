import importlib.util
from pathlib import Path
import unittest
import sys
import types
from unittest.mock import patch

def module(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).resolve().parents[1]/'fdm_mini_tools'/(name+'.py'))
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result

profile=module('print_profile')
bridge=module('bridge_analysis')
pkg=types.ModuleType('fdm_qa_offline');pkg.__path__=[str(Path(__file__).resolve().parents[1]/'fdm_mini_tools')]
sys.modules[pkg.__name__]=pkg
spec=importlib.util.spec_from_file_location('fdm_qa_offline.slice_qa',Path(pkg.__path__[0])/'slice_qa.py')
slice_qa=importlib.util.module_from_spec(spec);spec.loader.exec_module(slice_qa)
import numpy as np

class ProfileBridgeTests(unittest.TestCase):
    def test_profile_span_is_not_a_measurement(self):
        info=profile.summary(dict(layer_height='0.08',nozzle_diameter=['0.2'],
            initial_layer_print_height='0.2',bridge_speed=['50'],bridge_flow='1',max_bridge_length='10'))
        self.assertEqual(info['profile_bridge_limit_mm'],10)
        self.assertIsNone(info['measured_bridge_limit_mm'])
        self.assertFalse(info['support_removal_enabled'])

    def test_invalid_profile_not_silently_defaulted(self):
        with self.assertRaises(ValueError):profile.summary({'layer_height':'nan'})

    def masks(self, gap=5):
        old=np.zeros((5,12),bool);old[:,1:3]=True;old[:,3+gap:10+gap]=True
        new=old.copy();new[:,3:3+gap]=True
        return new,old

    def test_two_anchors_at_limit(self):
        new,old=self.masks()
        regions=bridge.classify_layer(new,old,1.,5.,2.)
        self.assertEqual([r['kind'] for r in regions],['BRIDGE_CANDIDATE'])
        self.assertEqual(regions[0]['span_mm'],5.)

    def test_above_limit_not_bridge(self):
        new,old=self.masks()
        self.assertEqual(bridge.classify_layer(new,old,1.,4.,2.)[0]['kind'],'CANTILEVER')

    def test_cantilever_cannot_use_nearby_unconnected_wall(self):
        old=np.zeros((5,12),bool);old[:,0:3]=True
        new=old.copy();new[:,3:8]=True
        self.assertEqual(bridge.classify_layer(new,old,1.,20.,2.)[0]['kind'],'CANTILEVER')

    def test_detached_island_not_bridge(self):
        old=np.zeros((5,12),bool);old[:,0:2]=True
        new=old.copy();new[1:4,6:9]=True
        self.assertEqual(bridge.classify_layer(new,old,1.,20.,2.)[0]['kind'],'ISLAND')

    def test_bridge_other_direction(self):
        new,old=self.masks()
        self.assertEqual(bridge.classify_layer(new.T,old.T,1.,5.,2.)[0]['kind'],'BRIDGE_CANDIDATE')

    def test_partial_two_anchor_coverage_cannot_certify_whole_region(self):
        new,old=self.masks();old[0,8:]=False
        self.assertNotEqual(bridge.classify_layer(new,old,1.,5.,2.)[0]['kind'],'BRIDGE_CANDIDATE')

    def test_actual_gcode_bridge_moves_and_material_statistics(self):
        text='; filament used [mm] = 10\n; filament used [cm3] = 0.02\n; estimated printing time (normal mode) = 2m 3s\nM83\n; FEATURE: Bridge\nG1 X1 E.3\nG1 X2 E-.1\nG92 E0\n; FEATURE: Outer wall\nG1 Y2 E.4\n'
        result=slice_qa.gcode_metrics(text)
        self.assertEqual(result['bridge_extrusion_moves'],1)
        self.assertEqual(result['positive_extrusion_moves'],2)
        self.assertEqual(result['estimated_time'],'2m 3s')

    def test_import_only_or_incomplete_gcode_is_rejected(self):
        with self.assertRaises(RuntimeError):slice_qa.gcode_metrics('G1 X2 E0.4')
        with self.assertRaises(RuntimeError):slice_qa.gcode_metrics('; filament used [mm] = 1')

if __name__=='__main__':unittest.main()
