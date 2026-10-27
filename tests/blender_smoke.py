"""Execute inside Blender 5.2: blender --background --python tests/blender_smoke.py

Tests whether the Blender runtime can:
- register the add-on;
- sample underside contacts using bundled SLASG reference;
- plan Tree support geometry + raft;
- create export-only repaired mesh copy.
It does NOT prove slicer/physical-print correctness.
"""

import os
import sys
import traceback
import argparse
import json
from pathlib import Path

import bpy

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

import fdm_mini_tools
from fdm_mini_tools import core, contacts, tree_support, tree_mesh
sys.path.insert(0, str(Path(__file__).resolve().parent))
from diagnose_tree_blender import topology


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    parser.add_argument('--strict-geometry', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    if not hasattr(bpy.types.Scene, 'fdm_mini_tools'):
        fdm_mini_tools.register()

    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    core.configure_mm_units()
    bpy.ops.mesh.primitive_uv_sphere_add(segments=20, ring_count=12, radius=8.0, location=(0, 0, 22.0))
    mini = bpy.context.object
    mini.name = 'SMOKE_MINI'

    cfg = core.config_from_preset(
        'BALANCED',
        support_strategy='FDM_TREE',
        tree_contact_backend='SLASG',
        tree_contact_limit=120,
        tree_merge_rounds=4,
        tree_ground_search_radius=18.0,
    )
    slasg_path = core.resolve_slasg_path()
    assert slasg_path, 'Bundled SLASG library missing'
    points = contacts.create_tree_point_object(mini, cfg, slasg_path)
    try:
        assert len(points.data.vertices) > 0, 'SLASG baseline scatter returned no points'
        support, stats = tree_support.generate_tree_supports(mini, points, cfg)
    finally:
        tree_support.remove_point_source(points)
    assert support and support.type == 'MESH', 'Missing Tree mesh'
    assert stats['rooted_tips'] > 0, 'Tree did not root any tips'
    assert support.get('fdm_tree_raft_style') == 'UNIFIED_CONVEX_V0', 'Missing common raft'

    before = core.nonmanifold_edge_count(support, evaluated=True)
    mesh_report = topology(support)
    copy = core._evaluated_export_copy(support, 'SMOKE_EXPORT_SUPPORTS')
    try:
        export_qa = tree_mesh.validate_support(mini, copy, json.loads(support[tree_mesh.CONTEXT_KEY]))
        report = dict(before=before, after=core.nonmanifold_edge_count(copy, evaluated=False),
            voxel_used=False, note='Validated Tree export geometry kept unchanged')
        print('[SMOKE] Pipeline execution: PASS')
        print('[SMOKE] Raw geometry gate:', 'PASS' if before == 0 and mesh_report['connected_components'] == 1 else 'FAIL')
        print('[SMOKE] contacts:', stats['contacts'], 'rooted:', stats['rooted_tips'], 'unresolved:', stats['unresolved_tips'])
        print('[SMOKE] mesh original nonmanifold:', before, 'export repaired:', report.get('after'))
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(dict(blender=bpy.app.version_string, stats=stats,
                raw_topology=mesh_report, repair_report=report,
                export_qa=export_qa,
                geometry_gate=before == 0 and mesh_report['connected_components'] == 1,
                note='Repair edge count alone proves neither clearance, retained tips nor printability.'), indent=2), encoding='utf-8')
    finally:
        core._remove_temp_object(copy)

    print('[SMOKE] Blender:', bpy.app.version_string)
    print('[SMOKE] Note: geometry and printability still need visual/slicer checks')
    if args.strict_geometry:
        assert before == 0 and mesh_report['connected_components'] == 1, 'Raw geometry gate failed'


try:
    run()
except Exception:
    traceback.print_exc()
    sys.exit(1)
