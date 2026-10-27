"""Classic GN execution regression; not a Classic printability qualification."""
import json
import sys
from pathlib import Path

import bpy

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import fdm_mini_tools
from fdm_mini_tools import core

fdm_mini_tools.register()
core.clear_scene(purge=False)
core.configure_mm_units()
bpy.ops.mesh.primitive_uv_sphere_add(segments=20,ring_count=12,radius=8.,location=(0,0,22))
mini=bpy.context.object
mini.name='CLASSIC_SMOKE_MINI'
cfg=core.config_from_preset('BALANCED',support_strategy='SLASG_CLASSIC')
support,scatter,generator=core.append_slasg(core.resolve_slasg_path())
core.configure_slasg(mini,support,scatter,generator,cfg)
core.bake_scatter(support,scatter,enable_generator=True)
assert generator.show_viewport and generator.show_render
deps=bpy.context.evaluated_depsgraph_get()
evaluated=support.evaluated_get(deps)
mesh=evaluated.to_mesh()
try:
    report=dict(blender=bpy.app.version_string,contact_vertices=len(support.data.vertices),
                generated_vertices=len(mesh.vertices),generated_faces=len(mesh.polygons),
                pipeline_pass=bool(mesh.vertices and mesh.polygons))
finally:
    evaluated.to_mesh_clear()
assert report['pipeline_pass'],'Classic GN produced no support mesh'
(ROOT/'reports').mkdir(exist_ok=True)
(ROOT/'reports/classic_smoke.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('[CLASSIC SMOKE]',json.dumps(report))
