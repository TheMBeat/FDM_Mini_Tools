"""Regression checks for RC1 collisions and closed segment caps.

Exit 0 means collision regressions pass, NEVER full geometry acceptance.
"""
import argparse
import json
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fdm_mini_tools import core, tree_support as ts


def topology(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    try:
        unseen = set(bm.verts)
        sizes = []
        while unseen:
            todo = [unseen.pop()]
            count = 0
            while todo:
                v = todo.pop()
                count += 1
                for edge in v.link_edges:
                    w = edge.other_vert(v)
                    if w in unseen:
                        unseen.remove(w)
                        todo.append(w)
            sizes.append(count)
        return dict(vertices=len(bm.verts), faces=len(bm.faces),
                    boundary_edges=sum(e.is_boundary for e in bm.edges),
                    nonmanifold_edges=sum(not e.is_manifold for e in bm.edges),
                    connected_components=len(sizes), component_sizes=sorted(sizes))
    finally:
        bm.free()


def box(name, low, high):
    bpy.ops.mesh.primitive_cube_add(size=2)
    obj = bpy.context.object
    obj.name = name
    obj.location = (Vector(low) + Vector(high)) / 2
    obj.scale = (Vector(high) - Vector(low)) / 2
    bpy.context.view_layer.update()
    return obj


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    core.clear_scene(purge=False)
    core.configure_mm_units()
    rows = {}
    # Cylinder radius .1 intersects a closed obstacle at x=.06..08.
    # The ray at x=0 misses; samples z=.5 apart miss its narrow Z band.
    obstacle = box('GRAZING_THIN_OBSTACLE', (.06, -.01, 4.99), (.08, .01, 5.01))
    bvh = core._world_bvh_from_object(obstacle)
    a, b = Vector((0, 0, 10)), Vector((0, 0, 0))
    accepted = ts._segment_clear(bvh, a, b, clearance=.1, sample_step=.55)
    exact_gap = bvh.find_nearest(Vector((0, 0, 5.00)))[3] - .1
    assert not accepted and exact_gap < 0
    rows['radius_between_samples'] = dict(accepted=accepted, surface_gap_mm=exact_gap,
                                         a=list(a), b=list(b), radius_mm=.1,
                                         obstacle_bounds=[[.06, -.01, 4.99], [.08, .01, 5.01]])
    solid = box('CONTAINING_SOLID', (-3, -3, 2), (3, 3, 12))
    bvh = core._world_bvh_from_object(solid)
    accepted = ts._segment_clear(bvh, Vector((0, 0, 9)), Vector((0, 0, 5)), clearance=.5)
    assert not accepted
    rows['inside_closed_solid'] = dict(accepted=accepted, reason='Inside segment rejected')

    core.clear_scene(purge=False)
    model = box('CONTACT_SURFACE', (-2, -2, 10), (2, 2, 11))
    blocker = box('NECK_BLOCKER', (-.1, -.1, 9.45), (.1, .1, 9.50))
    bpy.ops.object.select_all(action='DESELECT')
    model.select_set(True)
    blocker.select_set(True)
    bpy.context.view_layer.objects.active = model
    bpy.ops.object.join()
    bvh = core._world_bvh_from_object(model)
    contact = ts._contact_from_point(bvh, Vector((0, 0, 10)), core.config_from_preset('BALANCED'))
    assert contact is None
    rows['unvalidated_tip_neck'] = dict(accepted=False)

    edge = ts.SupportEdge(Vector((10, 0, 10)), Vector((10, 0, 2.4)), .5, .5, 'TRUNK')
    support = ts._build_curve_mesh([edge], {})
    rows['one_capped_spline'] = topology(support)
    assert rows['one_capped_spline']['boundary_edges'] == 0
    assert rows['one_capped_spline']['connected_components'] == 1
    raft = ts._build_unified_raft([Vector((10, 0, .6))], {})
    rows['raft_alone'] = topology(raft)
    support = ts._join_into_support(support, [raft])
    rows['joined_spline_and_raft'] = topology(support)
    # The deliberately isolated sample trunk ends at 2.4 mm and has no flare:
    # boolean union cannot invent the missing physical connection to the raft.
    assert rows['joined_spline_and_raft']['boundary_edges'] == 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dict(blender=bpy.app.version_string,
        meaning='COLLISION/CAP REGRESSIONS PASS; DISCONNECTED NEGATIVE FIXTURE IS NOT ACCEPTANCE', cases=rows), indent=2), encoding='utf-8')
    print(json.dumps(rows, indent=2))


if __name__ == '__main__':
    main()

