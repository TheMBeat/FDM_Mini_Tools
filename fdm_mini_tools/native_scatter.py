"""Native deterministic overhang contact sampler.

Blender-native implementation with no external node group or .blend resource.
It yields conservative overhang candidates; contact and path validation belong
in tree_support. Classic SLASG is deliberately kept as an optional backend.
"""

from __future__ import annotations

import math

import bpy
from mathutils import Vector


POINT_ROLE = "FDM_TREE_SCATTER_POINTS"


def _cell(pos, inv):
    return tuple(int(math.floor(float(x) * inv)) for x in pos)


def _insert_spaced(pos, buckets, spacing):
    inv = 1.0 / spacing
    key = _cell(pos, inv)
    radius_sq = spacing * spacing
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                for existing in buckets.get((key[0] + dx, key[1] + dy, key[2] + dz), ()):
                    if (existing - pos).length_squared < radius_sq:
                        return False
    buckets.setdefault(key, []).append(pos.copy())
    return True


def _area(a, b, c):
    return 0.5 * (b - a).cross(c - a).length


def _barycentric_candidates(a, b, c, spacing):
    """Sample interiors of a triangle without placing points on shared edges."""
    area = _area(a, b, c)
    if area <= 1.0e-9:
        return
    # Small faces get one candidate; large faces get a regular interior grid.
    divisions = max(1, min(18, int(math.ceil(math.sqrt(2.0 * area) / spacing))))
    if divisions == 1:
        yield (a + b + c) / 3.0
        return
    for i in range(divisions):
        for j in range(divisions - i):
            u = (i + 1.0 / 3.0) / divisions
            v = (j + 1.0 / 3.0) / divisions
            if u + v < 0.999:
                yield a * (1.0 - u - v) + b * u + c * v


def sample_overhangs(model, cfg, progress=None):
    """Return world-space overhang points, normal orientation tested on each face.

    This is a fast candidate sampler, not a guarantee of mechanically sufficient
    coverage. The tree planner may subsequently reject points for clearance.
    """
    if model is None or model.type != 'MESH':
        raise ValueError("Native contact sampling needs an active MINI mesh")
    spacing = max(0.5, float(cfg.get('spacing', 1.45)))
    max_points = max(20, min(1500, int(cfg.get('tree_contact_limit', 400))))
    # 45 degrees detects approximately the downward-facing half of underside
    # surfaces; vertical walls should not get supported.
    threshold = -math.cos(math.radians(float(cfg.get('overhang_angle', 45.0))))

    dg = bpy.context.evaluated_depsgraph_get()
    evaluated = model.evaluated_get(dg)
    mesh = evaluated.to_mesh(preserve_all_data_layers=False, depsgraph=dg)
    if mesh is None:
        raise RuntimeError('Could not evaluate MINI mesh for contact sampling')
    try:
        if hasattr(mesh, "calc_loop_triangles"):
            mesh.calc_loop_triangles()
        world = evaluated.matrix_world.copy()
        coords = [world @ v.co for v in mesh.vertices]
        # Sorting by deterministic spatial hash helps avoid a sequential bias
        # toward the first polygons in large imported STL objects.
        triangles = []
        for tri in mesh.loop_triangles:
            indices = tri.vertices
            a, b, c = coords[indices[0]], coords[indices[1]], coords[indices[2]]
            face_normal = (b - a).cross(c - a)
            if face_normal.length_squared < 1.0e-12:
                continue
            face_normal.normalize()
            if face_normal.z > threshold:
                continue
            area = _area(a, b, c)
            centroid = (a + b + c) / 3.0
            # World-position based ordering, independent of polygon index.
            hashed = (
                int(centroid.x * 193) * 73856093
                ^ int(centroid.y * 197) * 19349663
                ^ int(centroid.z * 199) * 83492791
            ) & 0xFFFFFFFF
            triangles.append((hashed, -area, a, b, c))
        triangles.sort(key=lambda row: (row[0], row[1]))

        points = []
        buckets = {}
        for index, (_key, _area_neg, a, b, c) in enumerate(triangles):
            for point in _barycentric_candidates(a, b, c, spacing):
                if _insert_spaced(point, buckets, spacing):
                    points.append(point)
                    if len(points) >= max_points:
                        break
            if len(points) >= max_points:
                break
            if progress and index > 0 and index % 5000 == 0:
                progress(min(95, 20 + 70 * index / max(1, len(triangles))), 'Sampling overhangs')
        if not points:
            raise RuntimeError(
                'No downward overhang candidates detected. Check orientation, normals and overhang angle.'
            )
        return points
    finally:
        evaluated.to_mesh_clear()


def create_point_object(model, cfg, progress=None):
    points = sample_overhangs(model, cfg, progress=progress)
    mesh = bpy.data.meshes.new('FDM_TREE_NATIVE_POINTS_MESH')
    mesh.from_pydata([tuple(p) for p in points], [], [])
    mesh.update()
    obj = bpy.data.objects.new('FDM_TREE_NATIVE_POINTS', mesh)
    bpy.context.collection.objects.link(obj)
    obj['fdm_mini_tools_role'] = POINT_ROLE
    obj['fdm_scatter_backend'] = 'NATIVE_V1'
    return obj
