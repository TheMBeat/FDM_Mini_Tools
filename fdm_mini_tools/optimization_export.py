"""Multi-part print assembly with independent meshes and assembly transforms."""
import json
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

from mathutils import Matrix
from . import mini_split,tree_mesh

NS='http://schemas.microsoft.com/3dmanufacturing/core/2015/02'


def write(path,records,status):
    ET.register_namespace('',NS)
    tag=lambda value:f'{{{NS}}}{value}'
    model=ET.Element(tag('model'),unit='millimeter')
    ET.SubElement(model,tag('metadata'),name='FDMTree:ContactStatus').text=status
    ET.SubElement(model,tag('metadata'),name='FDM:AssemblyFromPrint').text=json.dumps([
        dict(name=r['mini'].name,assembly_from_print=r['assembly_from_print']) for r in records])
    resources=ET.SubElement(model,tag('resources'))
    expected={}
    groups=[];index=1
    for record in records:
        ids=[]
        for role in ('mini','support'):
            obj=record.get(role)
            if obj is None:continue
            vertices,triangles=record['geometry'][role]
            resource=ET.SubElement(resources,tag('object'),id=str(index),type='model',name=obj.name)
            mesh=ET.SubElement(resource,tag('mesh'))
            verts=ET.SubElement(mesh,tag('vertices'));tris=ET.SubElement(mesh,tag('triangles'))
            for co in vertices:
                ET.SubElement(verts,tag('vertex'),**{k:f'{v:.9f}' for k,v in zip('xyz',co)})
            for triangle in triangles:
                ET.SubElement(tris,tag('triangle'),**{k:str(v) for k,v in zip(('v1','v2','v3'),triangle)})
            expected[str(index)]=(obj,record,role)
            ids.append(str(index));index+=1
        group=ET.SubElement(resources,tag('object'),id=str(index),type='model',name=record['mini'].name+'_WITH_SUPPORTS')
        components=ET.SubElement(group,tag('components'))
        for identifier in ids:ET.SubElement(components,tag('component'),objectid=identifier)
        groups.append((str(index),record['placement']));index+=1
    root=ET.SubElement(resources,tag('object'),id=str(index),type='model',name='FDM_MINI_PRINT_LAYOUT')
    components=ET.SubElement(root,tag('components'))
    for identifier,placement in groups:
        # 3MF matrices are 3x4 column-major (basis columns followed by XYZ).
        values=[placement[row][column] for column in range(4) for row in range(3)]
        ET.SubElement(components,tag('component'),objectid=identifier,
            transform=' '.join(f'{v:.12f}' for v in values))
    build=ET.SubElement(model,tag('build'));ET.SubElement(build,tag('item'),objectid=str(index))
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr('[Content_Types].xml','<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        package.writestr('_rels/.rels','<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        package.writestr('3D/3dmodel.model',ET.tostring(model,encoding='utf-8',xml_declaration=True))
    # Inspect actual serialized geometry in the strict pre-placement frame.
    with zipfile.ZipFile(path) as package:
        xml=ET.fromstring(package.read('3D/3dmodel.model'))
    created={};max_delta=0.;qa=[]
    try:
        for resource in xml.findall(tag('resources')+'/'+tag('object')):
            if resource.get('id') not in expected:continue
            original,record,role=expected[resource.get('id')]
            mesh=resource.find(tag('mesh'))
            vertices=[tuple(float(v.get(k)) for k in 'xyz') for v in mesh.findall(tag('vertices')+'/'+tag('vertex'))]
            triangles=[tuple(int(t.get(k)) for k in ('v1','v2','v3')) for t in mesh.findall(tag('triangles')+'/'+tag('triangle'))]
            wanted,wanted_tris=record['geometry'][role]
            if triangles!=wanted_tris or len(vertices)!=len(wanted):
                raise RuntimeError('3MF geometry changed during export')
            delta=max(abs(float(a)-float(b)) for co,ref in zip(vertices,wanted) for a,b in zip(co,ref))
            max_delta=max(max_delta,delta)
            if delta>.000001:raise RuntimeError('3MF coordinate mismatch')
            obj=tree_mesh._object('OPT_QA_READBACK',vertices,triangles)
            obj.matrix_world=Matrix.Identity(4)
            created[(id(record),role)]=obj
        import bpy
        bpy.context.view_layer.update()
        for record in records:
            mini=created[(id(record),'mini')]
            if not mini_split.mesh_qa(mini)['pass_gate']:
                raise RuntimeError('MINI 3MF readback is not manifold')
            if record.get('support'):
                support=created[(id(record),'support')]
                context=json.loads(record['support'][tree_mesh.CONTEXT_KEY])
                qa.append(tree_mesh.validate_support(mini,support,context))
        return dict(pass_gate=True,pieces=len(records),strict_support_gates=qa,
            max_coordinate_delta_mm=max_delta,assembly_metadata=True)
    finally:
        for obj in created.values():tree_mesh.remove(obj)
