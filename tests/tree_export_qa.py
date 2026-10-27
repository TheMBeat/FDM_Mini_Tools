"""Actual production export + read-back checks; used by Blender benchmarks."""
import json
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

from fdm_mini_tools import core, tree_mesh


def export_and_verify(mini, support, source, output_dir):
    ctx = json.loads(support[tree_mesh.CONTEXT_KEY])
    paths = core.export_outputs(mini, support, str(source), output_dir=str(output_dir),
        save_blend=False, use_level_cube=False, export_3mf=True,
        use_raft=ctx['use_raft'], do_final_manifold_repair=True, manifold_repair_mode='AUTO',allow_incomplete_tree_export=True)
    readback = core.import_stl(paths['supports'])
    try:
        stl_qa = tree_mesh.validate_support(mini, readback, ctx)
    finally:
        core._remove_temp_object(readback)
    with zipfile.ZipFile(paths['3mf']) as archive:
        xml = ET.fromstring(archive.read('3D/3dmodel.model'))
    ns = {'m':'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'}
    assert xml.get('unit') == 'millimeter'
    resources = xml.findall('m:resources/m:object', ns)
    assert len(resources) == 3
    build = xml.findall('m:build/m:item', ns)
    assert [item.get('objectid') for item in build] == ['3']
    assert all(item.get('transform') is None for item in build)
    assembly = next(obj for obj in resources if obj.get('id')=='3')
    components = assembly.findall('m:components/m:component',ns)
    assert [part.get('objectid') for part in components]==['1','2']
    assert all(part.get('transform') is None for part in components)
    objects = {}
    max_delta = 0.
    try:
        for resource, expected in zip(resources, (mini,support)):
            vertices = [tuple(float(v.get(c)) for c in 'xyz')
                        for v in resource.findall('m:mesh/m:vertices/m:vertex', ns)]
            triangles = [tuple(int(t.get(c)) for c in ('v1','v2','v3'))
                         for t in resource.findall('m:mesh/m:triangles/m:triangle', ns)]
            expected_vertices, expected_triangles = tree_mesh.world_mesh(expected)
            assert len(vertices)==len(expected_vertices), '3MF vertex count changed'
            delta = max(abs(a-b) for xyz,co in zip(vertices,expected_vertices) for a,b in zip(xyz,co))
            max_delta = max(max_delta,delta)
            assert delta < .000001, 'MINI/SUPPORTS world coordinate mismatch'
            if expected is support:
                assert triangles==expected_triangles, 'Tree triangles changed in 3MF'
            objects[resource.get('name')] = tree_mesh._object('QA_3MF_'+resource.get('name'), vertices, triangles)
        three_mf_qa = tree_mesh.validate_support(objects['MINI'], objects['SUPPORTS'], ctx)
    finally:
        for obj in objects.values():
            tree_mesh.remove(obj)
    return dict(paths=paths, stl_qa=stl_qa, three_mf_qa=three_mf_qa,
                max_world_coordinate_delta_mm=max_delta, slicer_validation=False)
