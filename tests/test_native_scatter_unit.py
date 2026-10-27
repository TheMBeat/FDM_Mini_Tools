"""Offline contract tests for the library-free sampler (no Blender required)."""
import importlib.util
import math
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class Vec:
    def __init__(self, xyz):
        self.v = tuple(float(x) for x in xyz)
    @property
    def x(self): return self.v[0]
    @property
    def y(self): return self.v[1]
    @property
    def z(self): return self.v[2]
    def __iter__(self): return iter(self.v)
    def __getitem__(self, i): return self.v[i]
    def __add__(self, other): return Vec(a + b for a, b in zip(self, other))
    def __sub__(self, other): return Vec(a - b for a, b in zip(self, other))
    def __mul__(self, value): return Vec(a * value for a in self)
    __rmul__ = __mul__
    def __truediv__(self, value): return Vec(a / value for a in self)
    @property
    def length_squared(self): return sum(a*a for a in self)
    @property
    def length(self): return math.sqrt(self.length_squared)
    def cross(self, other):
        a, b = self, other
        return Vec((a.y*b.z - a.z*b.y, a.z*b.x - a.x*b.z, a.x*b.y - a.y*b.x))
    def normalize(self):
        n = self.length
        self.v = tuple(a/n for a in self)
    def copy(self): return Vec(self.v)


class FakeIdentity:
    def __matmul__(self, x): return x
    def copy(self): return self


class FakeVertex:
    def __init__(self, xyz): self.co = Vec(xyz)


class FakeTri:
    def __init__(self, vertices): self.vertices = vertices


class FakeMesh:
    def __init__(self, vertices, triangles):
        self.vertices = [FakeVertex(p) for p in vertices]
        self.loop_triangles = [FakeTri(x) for x in triangles]


class FakeObj:
    type = 'MESH'
    matrix_world = FakeIdentity()
    def __init__(self, mesh): self.mesh = mesh
    def evaluated_get(self, depsgraph): return self
    def to_mesh(self, **kwargs): return self.mesh
    def to_mesh_clear(self): pass


def load_sampler():
    # import in isolation so tests work even without bpy installed
    fake_bpy = types.ModuleType('bpy')
    fake_bpy.context = types.SimpleNamespace(evaluated_depsgraph_get=lambda: None)
    fake_mu = types.ModuleType('mathutils')
    fake_mu.Vector = Vec
    sys.modules['bpy'] = fake_bpy
    sys.modules['mathutils'] = fake_mu
    spec = importlib.util.spec_from_file_location('fdm_native_scatter_test', ROOT/'fdm_mini_tools'/'native_scatter.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NativeScatterTest(unittest.TestCase):
    def setUp(self): self.sampler = load_sampler()

    def test_triangle_downward_creates_contacts(self):
        mesh = FakeMesh([(-4,-4,12), (0,4,12), (4,-4,12)], [(0,1,2)])
        points = self.sampler.sample_overhangs(FakeObj(mesh), {'spacing':1.2,'tree_contact_limit':40,'overhang_angle':45})
        self.assertTrue(1 <= len(points) <= 40)
        self.assertTrue(all(abs(p.z-12)<1e-9 for p in points))

    def test_upward_face_rejected(self):
        mesh = FakeMesh([(-4,-4,12), (4,-4,12), (0,4,12)], [(0,1,2)])
        with self.assertRaisesRegex(RuntimeError, 'No downward overhang'):
            self.sampler.sample_overhangs(FakeObj(mesh), {'spacing':1.2})

    def test_distance_filter(self):
        buckets = {}
        self.assertTrue(self.sampler._insert_spaced(Vec((0,0,0)), buckets, 1.0))
        self.assertFalse(self.sampler._insert_spaced(Vec((0.2,0.2,0)), buckets, 1.0))
        self.assertTrue(self.sampler._insert_spaced(Vec((2,0,0)), buckets, 1.0))

    def test_sample_limit(self):
        mesh = FakeMesh([(-10,-10,12), (0,10,12), (10,-10,12)], [(0,1,2)])
        points = self.sampler.sample_overhangs(FakeObj(mesh), {'spacing':0.5,'tree_contact_limit':20})
        self.assertEqual(len(points), 20)


if __name__ == '__main__':
    unittest.main()
