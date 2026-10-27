"""Experimental candidate search; complete evidence before recommendation.

SLASG acquisition and the existing strict Tree/export gates are called intact.
Unresolved/audit warnings prohibit a printable recommendation. A candidate can
still be retained as an explicitly incomplete comparison preview.
"""
import json
import math
from pathlib import Path

import bpy
import bmesh
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
import numpy as np

from . import (bridge_analysis, contacts, core, mini_split as split, optimization_export,
               orientation, print_profile, slice_qa, tree_mesh, tree_support)

REPORT_KEY='fdm_mini_optimization_report'


def matrix_rows(matrix):
    return [[float(x) for x in row] for row in matrix]


def canonical(source,name='OPT_SOURCE_FRAME'):
    obj=split.duplicate(source,name)
    basis=obj.get('fdm_orientation_source_basis')
    inverse=Matrix([basis[i:i+3] for i in (0,3,6)]).inverted_safe() if basis else Matrix.Identity(3)
    obj.data.transform(inverse.to_4x4());obj.data.update()
    if obj.get(orientation.FRONT_KEY) is not None:
        obj[orientation.FRONT_KEY]=list(inverse @ Vector(obj[orientation.FRONT_KEY]))
    obj['fdm_orientation_source_basis']=[v for row in Matrix.Identity(3) for v in row]
    vertices=np.array([v.co[:] for v in obj.data.vertices],dtype=float)
    low,high=vertices.min(axis=0),vertices.max(axis=0);middle=(low+high)/2;span=high-low
    obj['fdm_optimization_head_bounds']=[float(middle[0]-.22*span[0]),float(middle[1]-.22*span[1]),float(low[2]+.6*span[2]),
        float(middle[0]+.22*span[0]),float(middle[1]+.22*span[1]),float(high[2])]
    return obj,inverse.to_4x4()


def source_detail_reference(obj,front_mode):
    data=orientation.geometry(obj)
    front,confidence=orientation.estimate_front(data[0],data[2],data[3])
    if front_mode=='VIEW':
        if obj.get(orientation.FRONT_KEY) is None:
            raise ValueError('Vorderseite fehlt: Ansicht zuerst festlegen')
        front=Vector(obj[orientation.FRONT_KEY]);confidence=1.
    elif front_mode!='AUTO':
        front=Vector(dict(POS_X=(1,0,0),NEG_X=(-1,0,0),POS_Y=(0,1,0),NEG_Y=(0,-1,0))[front_mode]);confidence=1.
    front_weights=np.maximum(0,data[0] @ np.array(front))* (data[4]>.45) if front is not None else np.zeros(len(data[2]))
    bvh=BVHTree.FromPolygons([v.co for v in obj.data.vertices],
        [tuple(p.vertices) for p in obj.data.polygons],all_triangles=False)
    return dict(bvh=bvh,detail=data[3],front=front_weights,ambiguous=confidence<.08)


def comparable_metrics(parts,transforms,to_reference,reference,joints,overhang_deg=45.):
    """Map each candidate surface back to immutable original detail weights.

    Re-estimating a 'head' on every cut arm/base would make the detail score
    incomparable. New cap/joint faces count as overhangs but not as old facial
    detail. This remains a geometric proxy, never semantic face recognition.
    """
    total=detail=front=0.
    for obj,transform in zip(parts,transforms):
        data=orientation.geometry(obj)
        bounds=core.bounds(obj)
        center=np.array([(bounds[0]+bounds[1])/2,(bounds[2]+bounds[3])/2,(bounds[4]+bounds[5])/2])
        query=to_reference @ transform.inverted()
        detail_weights=np.zeros(len(data[2]));front_weights=np.zeros(len(data[2]))
        for index,point in enumerate(data[1]+center):
            hit=reference['bvh'].find_nearest(query @ Vector(point))
            if hit[0] is not None and hit[3]<=.0001:
                detail_weights[index]=reference['detail'][hit[2]]
                front_weights[index]=reference['front'][hit[2]]
        down=data[0][:,2] < -math.cos(math.radians(overhang_deg))
        cost=data[2]*(1+np.maximum(data[1][:,2],0)*.01)*(1+np.abs(data[0][:,2]))
        total+=float(np.sum(cost[down]*(1+4*detail_weights[down]+6*front_weights[down])))
        detail+=float(np.sum(data[2][down]*detail_weights[down]))
        front+=float(np.sum(data[2][down]*front_weights[down]))
    return dict(overhang_score=total,detail_proxy_mm2=detail,front_proxy_mm2=front,
        seam_cost=sum(j['seam_cost'] for j in joints),front_ambiguous=reference['ambiguous'])


def pose(part, mode, front_mode, lift):
    """Return assembly-from-print transform even when Blender bakes a rotation."""
    # Attach a tiny witness frame as mesh custom data is unnecessary: the rigid
    # change is recovered from three non-collinear ORIGINAL vertex coordinates.
    before=[v.co.copy() for v in part.data.vertices]
    if mode=='AUTO' and part.get('fdm_joint_type')=='FLAT':
        split.pose_flat_on_bed(part)
    elif mode=='AUTO' and part.get('fdm_joint_up_axis') is not None:
        split.pose_joint_up(part,lift)
    elif mode=='AUTO':
        core.orient_scored(part,lift=lift,front_mode=front_mode)
    else:
        core._place_lowest_at(part,lift)
    after=[part.matrix_world @ v.co for v in part.data.vertices]
    if len(before)!=len(after):
        raise RuntimeError('Pose must not modify topology')
    a=0
    b=max(range(len(before)),key=lambda i:(before[i]-before[a]).length_squared)
    ab=before[b]-before[a]
    c=max(range(len(before)),key=lambda i:ab.cross(before[i]-before[a]).length_squared)
    def basis(points):
        u=(points[b]-points[a]).normalized()
        n=u.cross(points[c]-points[a]).normalized()
        return Matrix((u,n.cross(u),n)).transposed()
    rot=basis(after) @ basis(before).transposed()
    transform=rot.to_4x4()
    transform.translation=after[a]-rot @ before[a]
    # All vertices, not just witnesses: reject a non-rigid pose or wrong frame.
    error=max((transform @ a-b).length for a,b in zip(before,after))
    if error>.00005:
        raise RuntimeError(f'Assembly pose witness error: {error}')
    return transform,error


def coarse(source,max_parts=6,clearance=.15,manual_plane=None,progress=None,joint_type='FLAT'):
    if joint_type not in {'FLAT','HEMISPHERE'}:
        raise ValueError('Unknown joint type: '+str(joint_type))
    if not 1 <= max_parts <= 6:
        raise ValueError('Part limit must be 1..6')
    base,inverse=canonical(source)
    owned=[base]
    candidates=[]
    rejections=[]
    try:
        # Restore the original asset basis for cutting/detail protection. KEEP
        # remains an independent exact copy of the current selected pose.
        if manual_plane is not None:
            manual_plane=dict(center=list(inverse @ Vector(manual_plane['center'])),
                normal=list(inverse.to_3x3() @ Vector(manual_plane['normal'])))
        current=[base]
        joints=[]
        cut_trials=0
        for depth in range(1,max_parts):
            if progress:
                progress(8+depth*3,f'Schnittvarianten pruefen: bis {depth+1} Teile')
            best=None
            # Split only one part per depth; bounded greedy beam. Every rejected
            # proposal is recorded; this is not a proof that no other cut exists.
            order=sorted(range(len(current)),key=lambda i:-split.mesh_qa(current[i])['volume_mm3'])
            for index in order:
                obj=current[index]
                if manual_plane is not None:
                    options=[manual_plane] if depth==1 else []
                else:
                    options=split.cut_options(obj,limit=12)
                for option in options:
                    if cut_trials>=6:
                        rejections.append(dict(depth=depth,part=index,reason='global_cut_trial_budget'))
                        break
                    cut_trials+=1
                    try:
                        parts,joint=split.split(obj,option['center'],option['normal'],clearance,joint_type=joint_type)
                        owned.extend(parts)
                        key=(joint['seam_cost'],index,tuple(option['center']))
                        if best is None or key<best[0]:
                            if best:
                                for item in best[2]:
                                    split.remove(item);owned.remove(item)
                            best=(key,index,parts,joint)
                        else:
                            for item in parts:
                                split.remove(item);owned.remove(item)
                    except (ValueError,RuntimeError) as exc:
                        rejections.append(dict(depth=depth,part=index,plane=option,reason=str(exc)))
                if best or manual_plane is not None:
                    break
            if best is None:
                break
            _,index,parts,joint=best
            current=current[:index]+list(parts)+current[index+1:]
            joints=joints+[joint]
            copies=[split.duplicate(p,f'OPT_SPLIT_{depth+1}_{i+1}') for i,p in enumerate(current)]
            candidates.append(dict(id=f'SPLIT_{depth+1}',parts=copies,joints=list(joints),pose='AUTO'))
        return candidates,rejections
    except Exception:
        for candidate in candidates:
            for obj in candidate['parts']:
                split.remove(obj)
        raise
    finally:
        for obj in owned:
            split.remove(obj)


def _collection(name,objects):
    collection=bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(collection)
    for obj in objects:
        for previous in list(obj.users_collection):
            previous.objects.unlink(obj)
        collection.objects.link(obj)
    return collection


def support_config_for_part(part,cfg,count):
    from .support_budget import part_config
    local=part_config(cfg,count)
    # The existing convex shared raft can enclose a flat-cut part's bed
    # footprint. Direct-bed pieces use the existing individually rooted mode.
    # Do not alter clearance, radius, contact or export validation thresholds.
    if part.get('fdm_joint_type')=='FLAT':
        local['use_raft']=False
        local['_direct_bed']=True
    return local


def evaluate(candidate,profile,profile_dir,out,cfg,front_mode,orca,source_path,progress=None):
    directory=out/candidate['id'];directory.mkdir(parents=True,exist_ok=True)
    parts=candidate['parts']; supports=[];pieces=[]
    incomplete=False
    export_records=[]
    x=y=5.;row_height=0.
    settings=profile['settings']
    bed=[tuple(map(float,p.split('x'))) for p in settings['printable_area']]
    xmin,xmax=min(p[0] for p in bed),max(p[0] for p in bed)
    ymin,ymax=min(p[1] for p in bed),max(p[1] for p in bed)
    x+=xmin;y+=ymin
    for index,part in enumerate(parts):
        transform,pose_error=pose(part,candidate['pose'],front_mode,cfg.get('optimization_lift',3.))
        qa=split.mesh_qa(part)
        if not qa['pass_gate']:
            raise RuntimeError(f'MINI mesh gate: {qa}')
        bridges=bridge_analysis.analyze(part,profile)
        piece_cfg=support_config_for_part(part,cfg,len(parts))
        points=contacts.create_tree_point_object(part,piece_cfg,core.resolve_slasg_path())
        try:
            support,stats=tree_support.generate_tree_supports(part,points,piece_cfg,progress=progress)
        finally:
            tree_support.remove_point_source(points)
        if support:
            supports.append(support)
        # Missing/invalid scatter points remain relevant even if some tips root.
        audit=json.loads(support.get('fdm_tree_contact_audit','{}')) if support else {}
        unresolved=stats.get('unresolved_tips',0)
        missing=audit.get('missing_count',0)
        incomplete |= bool((not support and not stats.get('no_support_required',False)) or unresolved or missing or stats.get('required_minima',{}).get('missing',0) or stats.get('stability',{}).get('unresolved',0) or stats.get('rejected_points',0) or not bridges['complete'])
        mesh_volume=split.mesh_qa(support)['volume_mm3'] if support else 0.
        # Keep validated float32 coordinates unchanged in 3MF resources. Bed
        # placement is serialized as a component transform, avoiding precision
        # loss when a 1e-6-mm edge is translated to a larger world coordinate.
        export_geometry=dict(mini=tree_mesh.world_mesh(part),
            support=tree_mesh.world_mesh(support) if support else None)
        bb=core.bounds(part)
        if support:
            sb=core.bounds(support)
            bb=tuple(min(bb[i],sb[i]) if i%2==0 else max(bb[i],sb[i]) for i in range(6))
        width,height=bb[1]-bb[0],bb[3]-bb[2]
        if width>xmax-xmin-10 or height>ymax-ymin-10:
            raise RuntimeError('Candidate exceeds printer bed')
        if x+width>xmax-5:
            x=xmin+5;y+=row_height+5;row_height=0.
        if y+height>ymax-5:
            raise RuntimeError('Candidate layout exceeds printer bed')
        shift=Vector((x-bb[0],y-bb[2],0))
        placement=Matrix.Translation(shift)
        assembly_from_print=(placement @ transform).inverted()
        # Export and QA BEFORE translating the Tree: its collision context is
        # expressed in current coordinates. Translate copies for the combined
        # plate; per-piece production exports preserve the strict context.
        paths=None
        if support:
            paths=core.export_outputs(part,support,str(source_path),str(directory/f'part_{index+1}'),
                save_blend=False,use_level_cube=False,use_raft=piece_cfg.get('use_raft',True),allow_incomplete_tree_export=True)
            # Real STL read-back must still pass the unchanged strict validator.
            back=core.import_stl(paths['supports'])
            try:
                ctx=json.loads(support[tree_mesh.CONTEXT_KEY])
                tree_mesh.validate_support(part,back,ctx)
            finally:
                core._remove_temp_object(back)
        elif stats.get('no_support_required',False):
            target=directory/f'part_{index+1}'/'MINI_DIRECT_BED.stl'
            target.parent.mkdir(parents=True,exist_ok=True)
            core.export_selected_stl(str(target),[part])
            back=core.import_stl(str(target))
            try:
                if not split.mesh_qa(back)['pass_gate']:
                    raise RuntimeError('Direct-bed MINI failed STL read-back')
            finally:core._remove_temp_object(back)
            paths=dict(mini=str(target),supports=None)
        part.matrix_world=placement @ part.matrix_world
        if support:
            support.matrix_world=placement @ support.matrix_world
        bpy.context.view_layer.update()
        pieces.append(dict(name=part.name,object=part.name,support=support.name if support else None,
            assembly_from_print=matrix_rows(assembly_from_print),pose_error_mm=pose_error,
            mesh_qa=qa,tree=stats,contact_audit=audit,bridges=bridges,
            direct_bed=part.get('fdm_joint_type')=='FLAT',support_raft_enabled=piece_cfg.get('use_raft',True),
            support_raft_volume_mm3=mesh_volume,paths=paths))
        export_records.append(dict(mini=part,support=support,assembly_from_print=matrix_rows(assembly_from_print),
            unplaced_from_print=matrix_rows(placement.inverted()),placement=matrix_rows(placement),
            geometry=export_geometry))
        x+=width+5;row_height=max(row_height,height)
    stem='PREVIEW_INCOMPLETE' if incomplete else 'GEOMETRY_CHECKED_NOT_PRINT_VALIDATED'
    package=directory/(stem+'.3mf')
    package_qa=optimization_export.write(package,export_records,stem)
    sliced=slice_qa.slice_project(orca,package,profile_dir,directory/'orca')
    result=dict(id=candidate['id'],parts_count=len(parts),pieces=pieces,
        joints=candidate['joints'],geometric=candidate['geometric'],
        incomplete=incomplete,printable_recommendation=False,slicing=sliced,
        unresolved_tips=sum(p['tree'].get('unresolved_tips',0) for p in pieces),
        support_raft_volume_mm3=sum(p['support_raft_volume_mm3'] for p in pieces),
        total_filament_mm3=sum(p['filament_volume_mm3'] or 0 for p in sliced['plates']),
        project=str(package),fit_validated=False,print_validated=False)
    result['combined_export_qa']=package_qa
    candidate['supports']=supports
    # Separate comparison collection, original remains visible and unchanged.
    collection=_collection('FDM_OPT_'+candidate['id'],parts+supports)
    collection.hide_render=True
    collection.hide_viewport=True
    result['collection']=collection.name
    (directory/'candidate.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


def recommend(results):
    eligible=[r for r in results if r.get('slicing',{}).get('pass_gate') and not r['incomplete']]
    if not eligible:
        return None,'No complete candidate; comparison previews only'
    # Detail protection precedes material. Seams carry an explicit cost so a
    # cut never wins on filament savings alone at equal detail risk.
    def key(r):
        g=r['geometric']
        return (round(g['front_proxy_mm2']+4*g['detail_proxy_mm2']+g['seam_cost'],6),
                r['total_filament_mm3'],r['parts_count'],r['id'])
    uncut=[r for r in eligible if r['parts_count']==1]
    # A fully checked split can make an otherwise unsupported model printable.
    # Retain failed uncut controls as evidence, not as a ban on improvement.
    controls=[r for r in results if r['parts_count']==1 and r.get('slicing',{}).get('pass_gate')]
    if not controls:
        return None,'No sliced uncut baseline; cannot establish a split advantage'
    baseline=min(uncut,key=key) if uncut else None
    best=min(eligible,key=key)
    if best['parts_count']>1 and best['geometric']['front_ambiguous']:
        return (baseline['id'] if baseline else None),'Front ambiguous; split needs review'
    if baseline and best['parts_count']>1:
        # Detail improvement is useful even when it costs some material.
        detail=lambda r:r['geometric']['front_proxy_mm2']+4*r['geometric']['detail_proxy_mm2']
        if detail(best)>=detail(baseline) and best['total_filament_mm3']>=baseline['total_filament_mm3']:
            best=baseline
    return best['id'],'Geometry/slicing comparison only; physical detail quality and fit unconfirmed'


def optimize(source,profile_path,output_dir,orca,cfg=None,max_parts=6,clearance=.15,
             front_mode='AUTO',manual_plane=None,progress=None,joint_type='FLAT'):
    if joint_type not in {'FLAT','HEMISPHERE'}:
        raise ValueError('Unknown joint type: '+str(joint_type))
    out=Path(output_dir).resolve();out.mkdir(parents=True,exist_ok=True)
    if (out/'optimization.json').exists():
        raise ValueError('Choose a new output directory; existing comparison must remain reproducible')
    profile_path=Path(profile_path).resolve()
    profile=print_profile.load(profile_path)
    if print_profile.sha256(orca) != profile.get('orca_sha256'):
        raise RuntimeError('Orca executable changed: resolve the profile again')
    cfg=dict(cfg or core.config_from_preset('BALANCED',support_strategy='FDM_TREE'))
    cfg['support_strategy']='FDM_TREE';cfg['tree_contact_backend']='SLASG'
    cfg['tree_show_missing']=False
    source_path=Path(source.get('fdm_source_path') or 'MINI.stl')
    before_vertices,before_triangles=tree_mesh.world_mesh(source)
    initial=set(bpy.data.objects)
    candidates=[];results=[];failures=[]
    report=dict(schema=1,experimental=True,profile=profile['summary'],
        recovery_budget_seconds=float(cfg.get('tree_recovery_seconds',20)),
        recovery_budget_scope='equal_part_quotas_per_candidate',
        bridge_contact_removal=False,max_parts=max_parts,joint_type=joint_type,
        joint_clearance_per_side_mm=clearance if joint_type=='HEMISPHERE' else 0.,
        source_object=source.name,source_mesh_qa=split.mesh_qa(source),
        measured_bridge_limit_mm=None,search='bounded greedy planar decomposition; not globally optimal')
    try:
        reference_object,to_reference=canonical(source,'OPT_DETAIL_REFERENCE')
        reference=source_detail_reference(reference_object,front_mode)
        candidates=[dict(id='KEEP',parts=[split.duplicate(source,'OPT_KEEP')],joints=[],pose='KEEP'),
                    dict(id='AUTO',parts=[split.duplicate(source,'OPT_AUTO')],joints=[],pose='AUTO')]
        cuts,rejections=coarse(source,max_parts,clearance,manual_plane,progress,joint_type=joint_type)
        candidates+=cuts
        for candidate in candidates:
            # Work on copies for coarse orientation so assembly coordinates of
            # finalists remain intact until their full evaluation.
            proxies=[split.duplicate(p,'OPT_SCORE') for p in candidate['parts']]
            try:
                transforms=[]
                for p in proxies:
                    transform,_=pose(p,candidate['pose'],front_mode,cfg.get('optimization_lift',3.))
                    transforms.append(transform)
                    core.apply_transforms(p)
                candidate['geometric']=comparable_metrics(proxies,transforms,
                    Matrix.Identity(4) if candidate['joints'] else to_reference,reference,candidate['joints'],cfg['overhang_angle'])
            finally:
                for p in proxies:split.remove(p)
        # Preserve both mandatory uncut controls, plus the best split variant.
        finalists=candidates[:2]
        if cuts:
            finalists.append(min(cuts,key=lambda c:(c['geometric']['front_proxy_mm2']+
                4*c['geometric']['detail_proxy_mm2']+c['geometric']['seam_cost'],
                len(c['parts']),c['id'])))
        report['coarse_candidates']=[dict(id=c['id'],parts=len(c['parts']),geometric=c['geometric']) for c in candidates]
        report['cut_rejections']=rejections
        for index,candidate in enumerate(finalists):
            if progress:progress(30+index*20,f"Vergleich {candidate['id']}: Supports und Orca-Slicing")
            attempt_objects=set(bpy.data.objects)
            try:
                results.append(evaluate(candidate,profile,profile_path.parent,out,cfg,front_mode,orca,source_path,
                    (lambda pct,step,base=30+index*20:progress(base+min(100,pct)*.18,step)) if progress else None))
            except Exception as exc:
                # Failed candidates must not remain visible beside the winner.
                current=set(bpy.data.objects)
                doomed=(current-attempt_objects) | (current & set(candidate['parts']))
                for obj in doomed:
                    if obj is not source:split.remove(obj)
                failures.append(dict(id=candidate['id'],reason=str(exc)))
                print(f"[OPT] {candidate['id']} rejected: {exc}",flush=True)
        recommended,reason=recommend(results)
        report.update(candidates=results,failures=failures,recommended=recommended,recommendation_reason=reason)
        after_vertices,after_triangles=tree_mesh.world_mesh(source)
        if before_vertices!=after_vertices or before_triangles!=after_triangles:
            raise RuntimeError('Original MINI changed during optimization')
        report['source_unchanged']=True
        source[REPORT_KEY]=str(out/'optimization.json')
        (out/'optimization.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        bpy.context.scene['fdm_optimization_report']=str(out/'optimization.json')
        if progress:progress(100,'Vergleich gespeichert; Vorschau und offene Bereiche pruefen')
        return report
    finally:
        retained={o for c in candidates if c.get('supports') for o in c['parts']+c['supports']}
        for obj in set(bpy.data.objects)-initial-retained:
            # SLASG templates are pipeline owned and may be cached; remove only
            # optimization candidates and supports created during failed runs.
            if obj.get('fdm_optimization_role') or obj.name.startswith(('SUPPORTS','OPT_')):
                split.remove(obj)
