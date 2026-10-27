"""First-layer birth witnesses, independent of angle-filtered scatter density.

Zero-dimensional persistence on the mesh height graph removes sub-layer bumps.
This is a conservative surface-topology screen, not full extrusion simulation.
Overlapping solids are checked separately against material immediately below.
"""
import math
import hashlib,struct
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from . import tree_collision as tc


def geometry_signature(model):
    from .tree_mesh import world_mesh
    vertices,triangles=world_mesh(model)
    digest=hashlib.sha256()
    for point in vertices:digest.update(struct.pack('<3f',*point))
    for triangle in triangles:digest.update(struct.pack('<3I',*triangle))
    return digest.hexdigest()


def find(model,layer_mm=.08,collider=None):
    if not math.isfinite(layer_mm) or not .01<=layer_mm<=.4:
        raise ValueError('Layer height must be 0.01..0.4 mm')
    evaluated=model.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh=evaluated.to_mesh()
    try:
        mesh.calc_loop_triangles()
        xyz=[evaluated.matrix_world @ v.co for v in mesh.vertices]
        triangles=[tuple(t.vertices) for t in mesh.loop_triangles]
        neighbors=[set() for _ in xyz];faces=[[] for _ in xyz]
        for index,tri in enumerate(triangles):
            for v in tri:faces[v].append(index)
            for a,b in ((tri[0],tri[1]),(tri[1],tri[2]),(tri[2],tri[0])):
                neighbors[a].add(b);neighbors[b].add(a)
        parent=list(range(len(xyz)));birth=list(range(len(xyz)));active=set();intervals=[]
        def root(i):
            while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
            return i
        for vertex in sorted(range(len(xyz)),key=lambda i:(xyz[i].z,i)):
            active.add(vertex)
            roots={root(j) for j in neighbors[vertex] if j in active}
            roots.add(vertex)
            elder=min(roots,key=lambda r:(xyz[birth[r]].z,birth[r]))
            for other in roots:
                if other==elder:continue
                depth=xyz[vertex].z-xyz[birth[other]].z
                if depth>=layer_mm-.00001:
                    intervals.append((birth[other],depth))
                parent[other]=elder
        for r in sorted({root(i) for i in range(len(xyz))}):intervals.append((birth[r],None))
        collider=collider or tc.ModelCollider(model)
        result=[]
        for vertex,depth in sorted(intervals,key=lambda row:(xyz[row[0]].z,row[0])):
            # Flood only the birth plateau, never an arbitrary radius around it.
            level=xyz[vertex].z;plateau={vertex};todo=[vertex]
            if level<=.0001:continue
            while todo:
                i=todo.pop()
                for j in neighbors[i]:
                    if j not in plateau and abs(xyz[j].z-level)<=.00001:
                        plateau.add(j);todo.append(j)
            point=sum((xyz[i] for i in sorted(plateau)),Vector())/len(plateau)
            flat=[t for t in {t for i in plateau for t in faces[i]}
                  if all(v in plateau for v in triangles[t])]
            if flat:
                flat_bvh=BVHTree.FromPolygons(xyz,[triangles[t] for t in sorted(flat)],all_triangles=True)
                point=flat_bvh.find_nearest(point)[0]
            else:flat_bvh=None
            below=point-Vector((0,0,layer_mm*.5))
            # Only actual solid directly below suppresses a birth. A nearby
            # higher contact, another side of a cloak, or a 10-mm profile gap
            # cannot count as already printed material.
            if not collider.outside_winding(below):continue
            options=[]
            for t in sorted({t for i in plateau for t in faces[i]}):
                a,b,c=[xyz[v] for v in triangles[t]]
                cross=(b-a).cross(c-a)
                if cross.length_squared<1e-20:continue
                normal=cross.normalized()
                if normal.z>=-.01:continue
                center=(a+b+c)/3
                anchor=min((xyz[v] for v in triangles[t] if v in plateau),key=lambda p:(p-point).length_squared)
                fraction=min(.12,.02/max(abs(center.z-anchor.z),1e-9),.025/max((center-anchor).length,1e-9))
                q=anchor+(center-anchor)*fraction
                if not any((q-Vector(p)).length<.0001 for p in options):options.append(list(q))
            result.append(dict(id=len(result),vertex=vertex,point=list(point),
                birth_z_mm=float(level),persistence_mm=float(depth) if depth is not None else None,
                plateau_vertices=len(plateau),flat_triangles=[[list(xyz[i]) for i in triangles[t]] for t in sorted(flat)],
                candidate_points=[list(point)]+options,
                note='Mandatory birth witness; conservative mesh-height topology, not semantic recognition'))
        return result
    finally:evaluated.to_mesh_clear()


def _in_cone(point,edge):
    p=Vector(point);delta=edge.b-edge.a;length2=delta.length_squared
    if length2<=0:return False
    t=(p-edge.a).dot(delta)/length2
    if not 0<=t<=1:return False
    radius=(edge.radius_a+(edge.radius_b-edge.radius_a)*t)*math.cos(math.pi/8)
    return (p-(edge.a+delta*t)).length <= radius-.00001


def _flat_hit(record,point):
    if not record['flat_triangles'] or abs(point[2]-record['birth_z_mm'])>.0001:return False
    tris=record['flat_triangles'];vertices=[Vector(p) for t in tris for p in t]
    bvh=BVHTree.FromPolygons(vertices,[tuple(range(i,i+3)) for i in range(0,len(vertices),3)],all_triangles=True)
    hit=bvh.find_nearest(Vector(point))
    return hit[0] is not None and hit[3]<.0001


def covered_by_edges(record,edges):
    for edge in edges:
        if edge.kind!='TIP_CONE':continue
        if _in_cone(record['point'],edge):return True
        if edge.contact_zone and _flat_hit(record,edge.contact_zone[0]):return True
    return False


from .support_budget import contact_budget

@contact_budget
def choose_contact(record,collider,cfg,route_finder=None):
    """Try only certified local cone/adapter alternatives; retain all gates."""
    from . import tree_support as ts
    failures={}
    seen=set(); impossible={}
    schedules=[(0.,0),(.6,0),(1.1,0),(1.8,0),(2.2,0),(1.8,1),(1.8,2),(2.2,1)]
    for length,choice in schedules:
        for point in record['candidate_points'][:3]:
            local=dict(cfg,_required_adapter_choice=choice,_required_adapter_min_length=length)
            key_point=tuple(point)
            if key_point in impossible:
                reason=impossible[key_point]
                failures[reason]=failures.get(reason,0)+1
                continue
            reasons=[]
            contact=ts._contact_from_point(collider,Vector(point),local,reasons)
            if not contact:
                reason=reasons[-1] if reasons else 'invalid_contact'
                failures[reason]=failures.get(reason,0)+1
                # All later schedules retain the same cone/neck and only
                # restrict adapter choices from the initial exhaustive search.
                if length <= 0. and choice == 0:impossible[key_point]=reason
                continue
            node,edges=contact
            if not covered_by_edges(record,edges):
                failures['cone_misses_birth']=failures.get('cone_misses_birth',0)+1
                continue
            key=tuple(round(x,4) for x in node)
            if key in seen:continue
            seen.add(key)
            route=(route_finder(ts.TreeNode(node)) if route_finder else
                   ts._find_ground_route(ts.TreeNode(node),cfg,collider))
            if route.points:
                return (ts.TreeComponent(ts.TreeNode(node),edges,1,route),dict(point=list(point),adapter_choice=choice,adapter_min_length=length,method=route.method))
            failures[route.reason]=failures.get(route.reason,0)+1
    return None,dict(reasons=failures)


def audit(model,support,records,rooted_edges):
    # The support has ALREADY passed tree_mesh.validate_support. Its legitimate
    # Boolean precision triangles use that mesh gate's stricter float64 logic;
    # do not feed it into the MINI-specific 1e-20 triangle-size precondition.
    from .tree_mesh import world_mesh
    vertices,triangles=world_mesh(support)
    bvh=BVHTree.FromPolygons(vertices,triangles,all_triangles=True)
    rows=[]
    for record in records:
        point=Vector(record['point'])
        # Flat births may be anchored elsewhere on that SAME connected plateau.
        candidates=[point]
        for edge in rooted_edges:
            if edge.kind=='TIP_CONE' and edge.contact_zone and _flat_hit(record,edge.contact_zone[0]):
                candidates.append(Vector(edge.contact_zone[0]))
        covered=False
        for p in candidates:
            counts=[tc.ray_winding(bvh,p,d.normalized()) for d in
                    (Vector((1,.371,.529)),Vector((-.217,1,.413)))]
            if counts==[1,1]:covered=True;break
            if counts != [0,0]:
                winding=tc.solid_angle_winding(p,vertices,triangles)
                if math.isfinite(winding) and abs(winding-1)<.0001:covered=True;break
        rows.append(dict(id=record['id'],point=record['point'],birth_z_mm=record['birth_z_mm'],
            persistence_mm=record['persistence_mm'],covered=covered,
            nearest_support_surface_mm=float(bvh.find_nearest(point)[3])))
    return dict(required=len(rows),missing=sum(not r['covered'] for r in rows),points=rows,
        model_signature=geometry_signature(model),
        policy='Actual closed rooted solid must contain a birth witness; no spacing-radius coverage')
