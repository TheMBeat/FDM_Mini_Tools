"""Geometric missing-support screen; no semantic weapon/face recognition.

Connected downward surface patches get low-point witnesses. Nearby ROOTED
contact zones cover them; raw/rejected scatter points cannot count as support.
The screen is conservative and requires annotated fixtures/print validation.
"""
import math,json
import bpy
from mathutils import Vector
from mathutils.kdtree import KDTree

ROLE='FDM_TREE_DIAGNOSTIC'


def audit(model,rooted,spacing=1.45,angle=45.,min_area=.04,direct_bed=False):
    deps=bpy.context.evaluated_depsgraph_get()
    obj=model.evaluated_get(deps)
    mesh=obj.to_mesh()
    try:
        mesh.calc_loop_triangles()
        xyz=[obj.matrix_world @ v.co for v in mesh.vertices]
        rows=[]
        bed_triangles=0
        edge_faces={}
        cutoff=-math.cos(math.radians(angle))
        for tri in mesh.loop_triangles:
            ids=tuple(tri.vertices)
            a,b,c=(xyz[i] for i in ids)
            cross=(b-a).cross(c-a)
            if cross.length_squared<1e-20 or cross.normalized().z>cutoff:
                continue
            if direct_bed and max(abs(v.z) for v in (a,b,c))<=1e-5 and cross.normalized().z<-.9999:
                bed_triangles+=1
                continue
            idx=len(rows)
            rows.append((ids,(a+b+c)/3,cross.length*.5))
            for i,j in ((ids[0],ids[1]),(ids[1],ids[2]),(ids[2],ids[0])):
                edge_faces.setdefault(tuple(sorted((i,j))),[]).append(idx)
        neighbors=[set() for _ in rows]
        for linked in edge_faces.values():
            for i in linked:
                neighbors[i].update(j for j in linked if j!=i)
        kd=KDTree(len(rooted)) if rooted else None
        if kd:
            for i,p in enumerate(rooted): kd.insert(Vector(p),i)
            kd.balance()
        unseen=set(range(len(rows)))
        patches=[]
        while unseen:
            seed=min(unseen)
            unseen.remove(seed)
            todo=[seed]
            component=[]
            while todo:
                i=todo.pop()
                component.append(i)
                for j in sorted(neighbors[i]):
                    if j in unseen:
                        unseen.remove(j)
                        todo.append(j)
            area=sum(rows[i][2] for i in component)
            if area<min_area: continue
            low=min(rows[i][1].z for i in component)
            probes=[rows[i][1] for i in component if rows[i][1].z<=low+.30]
            distances=[kd.find(p)[2] if kd else float('inf') for p in probes]
            # One contact near the arm must not hide an unsupported distal
            # low surface of a long weapon. Retain the WORST low-point probe.
            witness=max(range(len(probes)),key=lambda i:(distances[i],tuple(probes[i])))
            distance=distances[witness]
            patches.append(dict(id=len(patches),point=list(probes[witness]),area_mm2=area,
                nearest_rooted_contact_mm=distance if math.isfinite(distance) else None,
                missing=distance>max(.30,1.5*spacing)))
        missing=[p for p in patches if p['missing']]
        # Scanned STL detail can split one physical underside into hundreds of
        # tiny normal-threshold patches. Group neighboring witnesses spatially
        # for the UI, retaining every original patch in the diagnostic report.
        regions=[]
        if missing:
            group_tree=KDTree(len(missing))
            for i,p in enumerate(missing): group_tree.insert(Vector(p['point']),i)
            group_tree.balance()
            unseen=set(range(len(missing)))
            while unseen:
                seed=min(unseen);unseen.remove(seed)
                members=[];todo=[seed]
                while todo:
                    i=todo.pop();members.append(i)
                    for _,j,_ in group_tree.find_range(Vector(missing[i]['point']),max(.5,spacing)):
                        if j in unseen: unseen.remove(j);todo.append(j)
                witness=max(members,key=lambda i:(missing[i]['nearest_rooted_contact_mm'] or 1e30,-i))
                regions.append(dict(point=missing[witness]['point'],patch_ids=[missing[i]['id'] for i in sorted(members)],
                    area_mm2=sum(missing[i]['area_mm2'] for i in members)))
        return dict(patches=patches,regions=regions,missing_count=len(regions),raw_missing_patches=len(missing),
            bed_supported_triangles=bed_triangles,
            policy='Geometric downward-patch low-point screen; not semantic ground truth',
            radius_mm=max(.30,1.5*spacing))
    finally:
        obj.to_mesh_clear()


def clear_markers():
    for obj in list(bpy.data.objects):
        if obj.get('fdm_role')==ROLE:
            bpy.data.objects.remove(obj,do_unlink=True)


def markers(model,report,unresolved,rejected):
    clear_markers()
    rows=[(p['point'],'PRUEFBEREICH_HEURISTIK') for p in report['regions']]
    rows += [(point,'ROUTE_FEHLT') for route in unresolved for point in route.get('contacts',[])]
    rows += [(p['point'],'KONTAKT_VERWORFEN') for p in rejected]
    rows += [(p['point'],'TIEFPUNKT_UNGESICHERT') for p in report.get('required_minima',{}).get('points',[]) if not p['covered']]
    rows += [(p['top'],'STAMM_UNGESICHERT') for p in report.get('stability',{}).get('risky_spans',[])]
    for i,(point,reason) in enumerate(rows):
        obj=bpy.data.objects.new(f'{reason}_{i+1:03}',None)
        obj['fdm_role']=ROLE
        obj['fdm_reason']=reason
        obj['fdm_model']=model.name
        obj.empty_display_type='SPHERE'
        obj.empty_display_size=.35
        obj.location=point
        obj.color=(1.,.05,.01,1.)
        obj.show_in_front=True
        obj.hide_render=True
        bpy.context.scene.collection.objects.link(obj)


def export_status(support,model=None):
    text=support.get('fdm_tree_contact_audit')
    if not text:
        return dict(incomplete=True,reason="Contact audit is missing; regenerate supports")
    report=json.loads(text)
    if 'required_minima' not in report:
        return dict(incomplete=True,reason="Required low-point audit is missing; regenerate supports")
    if model is not None:
        from .required_minima import geometry_signature
        if report['required_minima'].get('model_signature')!=geometry_signature(model):
            return dict(incomplete=True,reason="MINI changed since the low-point audit; regenerate supports")
    missing=int(report['missing_count'])
    unresolved=int(support.get('fdm_tree_unresolved_tips',0))
    required=int(report.get('required_minima',{}).get('missing',0))
    stability=report.get('stability')
    if stability is None:return dict(incomplete=True,reason="Stem audit is missing; regenerate supports")
    from .required_minima import geometry_signature
    if stability.get('support_signature')!=geometry_signature(support):
        return dict(incomplete=True,reason="Supports changed since the stem audit; regenerate supports")
    unstable=int(stability.get('unresolved',0))
    return dict(incomplete=bool(missing or unresolved or required or unstable),missing=missing,unresolved=unresolved,
        required_minima_missing=required,
        unstable_stem_spans=unstable,
        reason=f'{missing} geometric review regions (heuristic), {unresolved} unresolved contacts, {required} unsupported low points, {unstable} unsupported stem spans above the limit')
