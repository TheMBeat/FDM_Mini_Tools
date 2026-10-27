"""Reversible bounded planar decomposition with certified keyed glue joints.

All operations consume owned candidate copies. Source objects are never edited.
Unsafe cuts are rejected, not repaired with a detail-destroying voxel remesh.
"""
import json
import math

import bpy
import bmesh
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from . import core, orientation, tree_mesh


def remove(obj):
    tree_mesh.remove(obj)


def duplicate(obj, name):
    evaluated=obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh=bpy.data.meshes.new_from_object(evaluated)
    mesh.transform(obj.matrix_world)
    result=bpy.data.objects.new(name,mesh)
    bpy.context.scene.collection.objects.link(result)
    if obj.get(orientation.FRONT_KEY) is not None:
        result[orientation.FRONT_KEY]=list(obj.matrix_world.to_3x3() @ Vector(obj[orientation.FRONT_KEY]))
    result['fdm_optimization_role']='CANDIDATE'
    if obj.get('fdm_split_joint'): result['fdm_split_joint']=obj['fdm_split_joint']
    if obj.get('fdm_joint_type'): result['fdm_joint_type']=obj['fdm_joint_type']
    if obj.get('fdm_joint_up_axis') is not None:
        result['fdm_joint_up_axis']=list(obj.matrix_world.to_3x3() @ Vector(obj['fdm_joint_up_axis']))
    basis=obj.get('fdm_orientation_source_basis')
    if basis:
        old=Matrix([basis[i:i+3] for i in (0,3,6)])
        result['fdm_orientation_source_basis']=[v for row in obj.matrix_world.to_3x3() @ old for v in row]
    if obj.get('fdm_optimization_head_bounds') is not None:
        result['fdm_optimization_head_bounds']=list(obj['fdm_optimization_head_bounds'])
    return result


def mesh_qa(obj):
    bm=bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.transform(obj.matrix_world)
        bm.normal_update()
        bmesh.ops.triangulate(bm,faces=list(bm.faces))
        nm=sum(not e.is_manifold for e in bm.edges)
        inconsistent=sum(e.is_manifold and not e.is_contiguous for e in bm.edges)
        degenerate=sum(tree_mesh.triangle_cross_squared(*(v.co for v in f.verts)) <= 1e-30 for f in bm.faces)
        volume=bm.calc_volume(signed=True) if bm.faces else 0.
        pending=set(bm.faces)
        components=0
        positive=True
        while pending:
            face=pending.pop()
            todo, shell=[face],[]
            while todo:
                face=todo.pop();shell.append(face)
                for edge in face.edges:
                    for other in edge.link_faces:
                        if other in pending:
                            pending.remove(other);todo.append(other)
            origin=shell[0].verts[0].co
            vol=sum((f.verts[0].co-origin).dot((f.verts[1].co-origin).cross(f.verts[2].co-origin))/6 for f in shell)
            positive &= vol > 1e-9
            components+=1
        return dict(pass_gate=bool(bm.faces and nm==0 and inconsistent==0 and degenerate==0 and positive),
            nonmanifold_edges=nm,inconsistent_edges=inconsistent,degenerate_faces=degenerate,
            components=components,volume_mm3=float(volume))
    finally:
        bm.free()


def boolean(target, tool, operation):
    modifier=target.modifiers.new('MINI_SPLIT_SOLID','BOOLEAN')
    modifier.solver='MANIFOLD'
    modifier.operation=operation
    modifier.object=tool
    name=modifier.name
    try:
        core.activate(target)
        bpy.ops.object.modifier_apply(modifier=name)
        tree_mesh.triangulate(target)
    finally:
        if name in target.modifiers:
            target.modifiers.remove(target.modifiers[name])
    report=mesh_qa(target)
    if not report['pass_gate']:
        raise RuntimeError(f'Cut/joint rejected by mesh QA: {report}')
    return report


def frame(normal):
    n=Vector(normal).normalized()
    u=n.cross(Vector((0,0,1)) if abs(n.z)<.9 else Vector((0,1,0))).normalized()
    v=n.cross(u).normalized()
    return u,v,n


def prism(name, center, normal, half_u, half_v, low, high):
    u,v,n=frame(normal);center=Vector(center)
    verts=[center+u*x+v*y+n*z for x,y,z in
        ((-half_u,-half_v,low),(half_u,-half_v,low),(half_u,half_v,low),(-half_u,half_v,low),
         (-half_u,-half_v,high),(half_u,-half_v,high),(half_u,half_v,high),(-half_u,half_v,high))]
    return tree_mesh._object(name,verts,[(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)])


def keyed_prism(name,center,normal,half_u,half_v,low,high,clearance=0.):
    """One chamfered corner prevents a nominal 180-degree assembly mistake.

    Socket clearance offsets every polygon edge by the same perpendicular
    distance, including the chamfer; scaling the polygon would not do that.
    """
    chamfer=.45
    polygon=[(-half_u,-half_v),(half_u,-half_v),(half_u,half_v-chamfer),
             (half_u-chamfer,half_v),(-half_u,half_v)]
    lines=[]
    for a,b in zip(polygon,polygon[1:]+polygon[:1]):
        dx,dy=b[0]-a[0],b[1]-a[1]
        length=math.hypot(dx,dy)
        outward=np.array((dy,-dx))/length
        lines.append((outward,float(outward@a)+clearance))
    expanded=[]
    for previous,current in zip(lines[-1:]+lines[:-1],lines):
        expanded.append(np.linalg.solve(np.array([previous[0],current[0]]),np.array([previous[1],current[1]])))
    u,v,n=frame(normal);center=Vector(center)
    verts=[center+u*float(x)+v*float(y)+n*z for z in (low,high) for x,y in expanded]
    count=len(expanded)
    faces=[tuple(reversed(range(count))),tuple(range(count,2*count))]
    faces += [(i,(i+1)%count,(i+1)%count+count,i+count) for i in range(count)]
    return tree_mesh._object(name,verts,faces)


def section(obj, center, normal, protect=True):
    vertices,tris=tree_mesh.world_mesh(obj)
    xyz=np.asarray(vertices,dtype=float)[np.array(tris)]
    n=np.asarray(normal,dtype=float);n/=np.linalg.norm(n)
    center=np.array(center,dtype=float)
    distances=(xyz-center)@n
    active=(distances.min(axis=1)<-1e-6)&(distances.max(axis=1)>1e-6)
    crossing=xyz[active]
    if not len(crossing):
        raise ValueError('Cut does not cross the model')
    # Strict protection of the upper central detail proxy in the SOURCE frame.
    low=np.min(xyz.reshape(-1,3),axis=0);high=np.max(xyz.reshape(-1,3),axis=0)
    span=np.maximum(high-low,1e-8);middle=(low+high)/2
    segments=[]
    for triangle in crossing:
        d=(triangle-center)@n
        hits=[]
        for a,b in ((0,1),(1,2),(2,0)):
            if (d[a]<0)!=(d[b]<0):
                hits.append(triangle[a]+d[a]/(d[a]-d[b])*(triangle[b]-triangle[a]))
        if len(hits)==2:
            segments.append(hits)
    if not segments:
        raise ValueError('Ambiguous cut contour')
    segments=np.array(segments)
    section_low=segments.reshape(-1,3).min(axis=0)
    section_high=segments.reshape(-1,3).max(axis=0)
    protected_low=np.array((middle[0]-.22*span[0],middle[1]-.22*span[1],low[2]+.60*span[2]))
    protected_high=np.array((middle[0]+.22*span[0],middle[1]+.22*span[1],high[2]))
    stored=obj.get('fdm_optimization_head_bounds')
    if stored is not None:
        protected_low=np.array(stored[:3]);protected_high=np.array(stored[3:])
    if protect and np.all(section_high>=protected_low) and np.all(section_low<=protected_high):
        raise ValueError('Cut intersects protected upper detail/head region')
    perimeter=float(np.linalg.norm(segments[:,1]-segments[:,0],axis=1).sum())
    front=np.array(obj.get(orientation.FRONT_KEY,(0.,1.,0.)))
    normals=np.cross(crossing[:,1]-crossing[:,0],crossing[:,2]-crossing[:,0])
    normals/=np.maximum(np.linalg.norm(normals,axis=1)[:,None],1e-12)
    visible=float(np.maximum(0,normals@front).mean())
    return dict(perimeter_mm=perimeter,visible_fraction=visible,
        seam_cost=perimeter*(1+6*visible),crossing_triangles=len(crossing)),segments


def connector_center(obj, center, normal, clearance=.15, wall=.8, depth=1.5):
    """Certify two unequal spherical socket envelopes inside one solid shell."""
    from .tree_collision import ModelCollider, ray_winding
    collider=ModelCollider(obj)
    info,segments=section(obj,center,normal)
    u,v,n=frame(normal);center=Vector(center)
    points=np.concatenate(segments,axis=0)
    projected=np.array([[Vector(p-center).dot(u),Vector(p-center).dot(v)] for p in points])
    low,high=projected.min(axis=0),projected.max(axis=0)
    for radii in ((.75,.35),(.55,.25)):
        separation=sum(radii)+2*clearance+wall
        for shell_index,(shell,shell_low,shell_high) in enumerate(collider.shells):
            candidates=[]
            for x in np.linspace(low[0],high[0],9):
                for y in np.linspace(low[1],high[1],9):
                    p=center+u*float(x)+v*float(y)
                    near=shell.find_nearest(p)
                    if near[0] is not None and near[3]>radii[0]+clearance+wall and (p-near[0]).dot(near[1])<0:
                        candidates.append((-near[3],float(x),float(y),p))
            for _,_,_,p in sorted(candidates,key=lambda row:row[:3]):
                for direction in (u,-u,v,-v):
                    centers=(p,p+direction*separation)
                    if all((near:=shell.find_nearest(c))[0] is not None
                           and near[3]>=r+clearance+wall
                           and [ray_winding(shell,c,d.normalized()) for d in
                                (Vector((1,.371,.529)),Vector((-.217,1,.413))) ]==[1,1]
                           for c,r in zip(centers,radii)):
                        info.update(hemisphere_centers=[list(c) for c in centers],
                                    hemisphere_radii_mm=list(radii),containing_shell=shell_index)
                        return p,radii,info
    raise ValueError('No paired hemispherical joint with sufficient wall clearance')


def sphere_tool(name,center,radius):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32,ring_count=16,radius=radius,location=center)
    obj=bpy.context.object;obj.name=name
    core.apply_transforms(obj)
    return obj


def _pose_joint_axis(part,target,lift):
    axis=part.matrix_world.to_3x3() @ Vector(part['fdm_joint_up_axis'])
    rotation=axis.normalized().rotation_difference(Vector(target)).to_matrix().to_4x4()
    bb=core.bounds(part)
    pivot=Vector(((bb[0]+bb[1])/2,(bb[2]+bb[3])/2,(bb[4]+bb[5])/2))
    part.matrix_world=Matrix.Translation(pivot) @ rotation @ Matrix.Translation(-pivot) @ part.matrix_world
    core.apply_transforms(part)
    part['fdm_joint_up_axis']=list(target)
    core._place_lowest_at(part,lift)


def pose_joint_up(part,lift=0.):
    _pose_joint_axis(part,(0.,0.,1.),lift)


def pose_flat_on_bed(part):
    _pose_joint_axis(part,(0.,0.,-1.),0.)


def split(obj, center, normal, clearance=.15, protect=True, joint_type='FLAT'):
    if joint_type not in {'FLAT','HEMISPHERE'}:
        raise ValueError('Unknown joint type: '+str(joint_type))
    if joint_type=='HEMISPHERE' and not .02 <= clearance <= .5:
        raise ValueError('Joint clearance must be between 0.02 and 0.5 mm per side')
    info,_=section(obj,center,normal,protect=protect)
    # Only the hemispherical joint removes material for sockets. Flat caps
    # deliberately have no bosses, sockets or mating clearance.
    if joint_type=='HEMISPHERE':
        joint,half,info=connector_center(obj,center,normal,clearance)
    vertices,_=tree_mesh.world_mesh(obj)
    extent=max((Vector(v)-Vector(center)).length for v in vertices)+10
    left=right=tool=None
    try:
        left=duplicate(obj,obj.name+'_A');right=duplicate(obj,obj.name+'_B')
        for part,lo,hi in ((left,-extent,0),(right,0,extent)):
            tool=prism('CUT_HALFSPACE',center,normal,extent,extent,lo,hi)
            boolean(part,tool,'INTERSECT');remove(tool);tool=None
        before=mesh_qa(obj)['volume_mm3']
        closed_volume=mesh_qa(left)['volume_mm3']+mesh_qa(right)['volume_mm3']
        # Overlapping source shells can union during boolean operations; reject
        # rather than quietly lose source material or accept changed geometry.
        if abs(closed_volume-before) > max(.02,before*.001):
            raise ValueError('Cut changes source volume beyond 0.1 percent')
        for c,radius in zip(info.get('hemisphere_centers',[]),info.get('hemisphere_radii_mm',[])):
            tool=sphere_tool('HEMISPHERE_BOSS',c,radius)
            boolean(left,tool,'UNION');remove(tool);tool=None
            tool=sphere_tool('HEMISPHERE_SOCKET',c,radius+clearance)
            boolean(right,tool,'DIFFERENCE');remove(tool);tool=None
        for part in (left,right):
            if mesh_qa(part)['volume_mm3'] < 4:
                raise ValueError('Cut produces a fragile tiny part')
        record=dict(center=list(center),normal=list(Vector(normal).normalized()),
            joint_type=joint_type,key_shape='FLAT' if joint_type=='FLAT' else 'UNEQUAL_HEMISPHERE_PAIR',
            rotation_keyed=joint_type=='HEMISPHERE',
            clearance_per_side_mm=0. if joint_type=='FLAT' else clearance,
            source_volume_mm3=before,capped_volume_mm3=closed_volume,
            fit_validated=False,**info)
        if joint_type=='HEMISPHERE':
            record.update(joint_center=list(joint),key_half_widths_mm=list(half),
                          pin_depth_mm=max(half),minimum_wall_mm=.8)
        for part in (left,right):
            part['fdm_split_joint']=json.dumps(record)
            part['fdm_joint_type']=joint_type
            part['fdm_joint_up_axis']=list(Vector(normal).normalized() * (1 if part is left else -1))
        return (left,right),record
    except Exception:
        remove(left);remove(right)
        raise
    finally:
        remove(tool)


def cut_options(obj, limit=4):
    verts,_=tree_mesh.world_mesh(obj)
    xyz=np.asarray(verts,dtype=float);low,high=xyz.min(axis=0),xyz.max(axis=0)
    candidates=[]
    for axis in range(3):
        normal=np.eye(3)[axis]
        for fraction in (.20,.30,.40,.50,.60,.70,.80):
            center=(low+high)/2;center[axis]=low[axis]+fraction*(high[axis]-low[axis])
            try:
                info,_=section(obj,center,normal)
            except ValueError:
                continue
            # Cross-section perimeter relative to the model diameter favors
            # narrow transitions. Large broad cuts lose to uncut candidates.
            candidates.append((info['seam_cost'],axis,fraction,list(center),list(normal)))
    return [dict(center=row[3],normal=row[4],seam_cost=row[0]) for row in sorted(candidates)[:limit]]


def calibration_objects(clearance=.15):
    """Bridge spans 2..14 mm and a keyed peg/socket fit coupon, printable as-is."""
    objects=[]
    try:
        for index,span in enumerate((2.,4.,6.,8.,10.,12.,14.)):
            y=index*8
            parts=[prism('ANCHOR_L',(-span/2-2,y,0),(0,0,1),2,2,0,5),
                   prism('ANCHOR_R',(span/2+2,y,0),(0,0,1),2,2,0,5),
                   prism('BRIDGE',(0,y,0),(0,0,1),span/2+4,2,5,5.6)]
            obj=tree_mesh.union(parts,f'BRIDGE_{span:g}mm')
            tree_mesh.triangulate(obj)
            if not mesh_qa(obj)['pass_gate']:
                raise RuntimeError('Calibration bridge is not manifold')
            objects.append(obj)
        block=prism('FIT_SOURCE',(25,15,0),(0,0,1),4,4,0,12)
        # Fit coupon bypasses only the semantic head proxy, not wall checks.
        # connector_center uses the same protection internally; z=4 is below it.
        pieces,record=split(block,(25,15,5),(0,0,1),clearance,protect=False,joint_type='HEMISPHERE')
        remove(block)
        for part in pieces:pose_joint_up(part)
        pieces[1].location.x += 12
        bpy.context.view_layer.update()
        objects.extend(pieces)
        return objects
    except Exception:
        for obj in objects:
            remove(obj)
        raise
