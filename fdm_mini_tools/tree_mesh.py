"""Closed Tree solids, native boolean union, and pre-export geometry gates."""
import json
import math

import bpy
import bmesh
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from . import tree_collision, containment

TOL = 0.0001
CONTEXT_KEY = 'fdm_tree_mesh_context'


def triangle_cross_squared(a, b, c):
    # BMesh.calc_area() can report zero for thin valid triangles at MINI-world
    # coordinates. Subtract first in Python float64, then form the cross.
    u = [float(b[i])-float(a[i]) for i in range(3)]
    v = [float(c[i])-float(a[i]) for i in range(3)]
    cross = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
    return sum(x*x for x in cross)


def _ear_triangles(ids, coordinates, normal):
    """Float64 ear clipping for planar boolean caps with collinear vertices.

    Keep boundary vertices (also used by neighboring faces); deleting them
    would create T-junctions. This only replaces tessellations with true zeros.
    """
    axis = max(range(3), key=lambda i:abs(normal[i]))
    axes = [i for i in range(3) if i != axis]
    origin = coordinates[ids[0]]
    xy = {i:tuple(float(coordinates[i][j])-float(origin[j]) for j in axes) for i in ids}
    def cross(a,b,c):
        return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    area = math.fsum(xy[ids[i]][0]*xy[ids[(i+1)%len(ids)]][1]-xy[ids[(i+1)%len(ids)]][0]*xy[ids[i]][1] for i in range(len(ids)))
    sign = 1 if area>0 else -1
    remaining = list(ids)
    triangles = []
    while len(remaining)>3:
        for index,b in enumerate(remaining):
            a,c = remaining[index-1],remaining[(index+1)%len(remaining)]
            if sign*cross(xy[a],xy[b],xy[c]) <= 1e-20:
                continue
            if any(all(sign*cross(x,y,xy[p]) >= -1e-20
                       for x,y in ((xy[a],xy[b]),(xy[b],xy[c]),(xy[c],xy[a])))
                   for p in remaining if p not in (a,b,c)):
                continue
            triangles.append((a,b,c))
            remaining.pop(index)
            break
        else:
            raise RuntimeError('Tree boolean cap cannot be triangulated without zero-area faces')
    if triangle_cross_squared(*(coordinates[i] for i in remaining)) <= 1e-30:
        shortest=min((coordinates[a]-coordinates[b]).length for a in remaining for b in remaining if a!=b)
        if shortest > .00002:
            raise RuntimeError('Tree boolean cap ends in a zero-area triangle')
        # A long residual can contain a microscopic duplicate-edge spike
        # (Robust route witness: 0.000000715 mm). Keep its boundary here and
        # let the existing bounded, link-checked collapse handle it below.
        # Final topology still requires zero degenerate faces and no holes.
    triangles.append(tuple(remaining))
    return triangles


def remove(obj):
    if obj is None or obj.name not in bpy.data.objects:
        return
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if data.users == 0:
        if isinstance(data, bpy.types.Mesh):
            bpy.data.meshes.remove(data)


def _object(name, verts, faces):
    mesh = bpy.data.meshes.new(name+'_MESH')
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


def closed_edge(edge, cfg, name='TREE_EDGE'):
    """Shared ring/cap vertices; small junction overlap stays in endpoint balls."""
    a, b = edge.a.copy(), edge.b.copy()
    axis = (b-a).normalized()
    reference = Vector((1,0,0)) if abs(axis.z) > .9 else Vector((0,0,1))
    u = axis.cross(reference).normalized()
    v = axis.cross(u).normalized()
    n = max(8, min(32, int(cfg.get('resolution', 8))))
    rings = []
    extension = min(.02, (b-a).length*.1, edge.radius_a*.1, edge.radius_b*.1)
    if edge.kind != 'TIP_CONE' and a.z-extension*abs(axis.z) > TOL:
        rings.append((a-axis*extension, math.sqrt(edge.radius_a**2-extension**2)))
    rings.extend(((a, edge.radius_a), (b, edge.radius_b)))
    if b.z-extension*abs(axis.z) > TOL:
        rings.append((b+axis*extension, math.sqrt(edge.radius_b**2-extension**2)))
    verts = []
    for center, radius in rings:
        for i in range(n):
            angle = 2*math.pi*i/n
            verts.append(tuple(center+radius*(math.cos(angle)*u+math.sin(angle)*v)))
    last = (len(rings)-1)*n
    faces = [tuple(reversed(range(n))), tuple(range(last,last+n))]
    for ring in range(len(rings)-1):
        lo, hi = ring*n, (ring+1)*n
        faces.extend((lo+i, lo+(i+1)%n, hi+(i+1)%n, hi+i) for i in range(n))
    return _object(name, verts, faces)


def union(objects, name):
    """Consume owned inputs. Always clean operands on success AND failure."""
    objects = list(objects)
    if not objects:
        raise RuntimeError('Tree mesh union has no solids')
    result = objects[0]
    operands = None
    success = False
    try:
        if len(objects) > 1:
            operands = bpy.data.collections.new('TREE_BOOLEAN_OPERANDS')
            bpy.context.scene.collection.children.link(operands)
            for obj in objects[1:]:
                operands.objects.link(obj)
            modifier = result.modifiers.new('TREE_SOLID_UNION', 'BOOLEAN')
            modifier.operation = 'UNION'
            modifier.operand_type = 'COLLECTION'
            modifier.collection = operands
            modifier.solver = 'MANIFOLD'
            bpy.ops.object.select_all(action='DESELECT')
            result.select_set(True)
            bpy.context.view_layer.objects.active = result
            bpy.ops.object.modifier_apply(modifier=modifier.name)
        if not result.data.polygons:
            raise RuntimeError('Tree solid union returned an empty mesh')
        result.name = name
        result.data.name = name+'_MESH'
        result['fdm_tree_mesh_method'] = 'CLOSED_SOLIDS_MANIFOLD_UNION_V1'
        success = True
        return result
    finally:
        for obj in objects[1:]:
            remove(obj)
        if not success:
            remove(result)
        if operands is not None:
            bpy.data.collections.remove(operands)


def junctions(edges):
    """Round bent graph joints inside ALL incident certified endpoint balls.

    Contact starts remain untouched. Matching uses the routing graph's existing
    0.0001-mm key; subtract actual endpoint offsets rather than moving edges.
    """
    nodes={};protected=set()
    for edge in edges:
        for point,other,radius in ((edge.a,edge.b,edge.radius_a),(edge.b,edge.a,edge.radius_b)):
            key=tuple(round(float(c),4) for c in point)
            nodes.setdefault(key,[]).append((point,other,float(radius)))
        if edge.kind=='TIP_CONE':protected.add(tuple(round(float(c),4) for c in edge.a))
    result=[]
    for key,incident in nodes.items():
        if len(incident)<2 or key in protected:continue
        center=incident[0][0]
        directions=[(other-point).normalized() for point,other,_ in incident]
        if len(directions)==2 and directions[0].dot(directions[1]) < -1.+1e-7:continue
        guard=containment.roundoff_guard(max(abs(c) for c in center),TOL)
        radius=min(r-(point-center).length for point,_,r in incident)-2*guard
        radius=min(radius,float(center.z)-2*guard)
        if radius<=TOL:continue
        result.append(dict(center=list(center),radius=radius,core_radius=radius*.95))
    return result


_JOINT_TEMPLATE=None

def rounded_joint(joint):
    """Inscribed sphere: no vertex expands the endpoint collision envelope."""
    global _JOINT_TEMPLATE
    if _JOINT_TEMPLATE is None:
        bm=bmesh.new()
        try:
            bmesh.ops.create_icosphere(bm,subdivisions=3,radius=1.)
            bm.verts.index_update()
            _JOINT_TEMPLATE=([tuple(v.co.normalized()) for v in bm.verts],
                [tuple(v.index for v in f.verts) for f in bm.faces])
        finally:bm.free()
    xyz,faces=_JOINT_TEMPLATE;center=Vector(joint['center']);radius=joint['radius']
    return _object('TREE_ROUNDED_JOINT',[tuple(center+Vector(v)*radius) for v in xyz],faces)


def build_edges(edges, cfg, name):
    solids = []
    try:
        for edge in edges:
            if (edge.b-edge.a).length < .0001:
                raise RuntimeError('Tree mesh received a degenerate edge')
            solids.append(closed_edge(edge, cfg))
        joints=junctions(edges)
        solids.extend(rounded_joint(j) for j in joints)
        result=union(solids, name)
        result['fdm_tree_rounded_joints']=len(joints)
        result['fdm_tree_joint_profile']='INSCRIBED_ENDPOINT_BALL_V1'
        return result
    except Exception:
        for obj in solids:
            # union may already have consumed these objects.
            try:
                remove(obj)
            except ReferenceError:
                pass
        raise


def world_mesh(obj):
    deps = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(deps)
    mesh = evaluated.to_mesh()
    try:
        mesh.calc_loop_triangles()
        verts = [evaluated.matrix_world@v.co for v in mesh.vertices]
        tris = [tuple(t.vertices) for t in mesh.loop_triangles]
        return verts, tris
    finally:
        evaluated.to_mesh_clear()


def _repair_cap_duplicates(obj, ids):
    """Transactional, single bounded retry; full production gates still apply."""
    original = obj.data
    bm = bmesh.new()
    candidate = None
    try:
        bm.from_mesh(original)
        bm.verts.ensure_lookup_table()
        mapping = {}
        displacement = 0.
        for index, a in enumerate(ids):
            target = bm.verts[a]
            if target in mapping:
                continue
            for b in ids[index+1:]:
                source = bm.verts[b]
                if source is target or source in mapping:
                    continue
                distance = (source.co-target.co).length
                if distance <= 0.000002:
                    mapping[source] = target
                    displacement = max(displacement, distance)
        if not mapping:
            return False
        count = len(mapping)
        bmesh.ops.weld_verts(bm, targetmap=mapping)
        candidate = original.copy()
        bm.to_mesh(candidate)
        candidate.update()
        obj.data = candidate
        try:
            triangulate(obj, _allow_cap_repair=False)
            qa = topology(obj, require_single=False)
            if any(qa[key] for key in ('nonmanifold_edges', 'inconsistent_edges', 'degenerate_faces', 'nonfinite_vertices')):
                raise RuntimeError('Cap endpoint repair failed topology gate')
        except Exception:
            failed = obj.data
            obj.data = original
            if failed.users == 0:
                bpy.data.meshes.remove(failed)
            return False
        obj['fdm_tree_cap_endpoint_welds'] = count
        obj['fdm_tree_cap_max_displacement_mm'] = displacement
        if original.users == 0:
            bpy.data.meshes.remove(original)
        return True
    finally:
        bm.free()


def triangulate(obj, _allow_cap_repair=True):
    """Freeze Blender's checked tessellation; avoid a second ngon fan/beauty pass."""
    old = obj.data
    old.calc_loop_triangles()
    coordinates = [v.co for v in old.vertices]
    bad_polygons = {}
    for tri in old.loop_triangles:
        if triangle_cross_squared(*(coordinates[i] for i in tri.vertices)) <= 1e-30:
            extent = max((coordinates[a]-coordinates[b]).length for a in tri.vertices for b in tri.vertices)
            bad_polygons[tri.polygon_index] = max(bad_polygons.get(tri.polygon_index,0.),extent)
    replacements = {}
    duplicate_cap_fallbacks=0
    for i,extent in bad_polygons.items():
        polygon = old.polygons[i]
        # Microscopic collinear bridge quads have no planar area to ear-clip;
        # leave them for the bounded topology-preserving edge collapse below.
        if len(polygon.vertices)>3 and extent>.00002:
            try:
                replacements[i] = _ear_triangles(tuple(polygon.vertices),coordinates,polygon.normal)
            except RuntimeError:
                # MANIFOLD may return a weakly-simple cap with a sub-micron
                # duplicate endpoint. Repair only that cap's near duplicates;
                # never discard a long zero triangle or weld the whole model.
                if _allow_cap_repair and _repair_cap_duplicates(obj, tuple(polygon.vertices)):
                    return
                bad=[t for t in old.loop_triangles if t.polygon_index==i
                    and triangle_cross_squared(*(coordinates[j] for j in t.vertices))<=1e-30]
                # Exact duplicate endpoints from MANIFOLD are not a long
                # collinear cap. Keep Blender's tessellation and let the
                # existing link-checked collapse remove only its zero edge.
                if not bad or any(not any(coordinates[a]==coordinates[b]
                        for a,b in ((t.vertices[0],t.vertices[1]),(t.vertices[1],t.vertices[2]),(t.vertices[2],t.vertices[0]))) for t in bad):
                    raise
                duplicate_cap_fallbacks+=1
    source_triangles = [tuple(t.vertices) for t in old.loop_triangles if t.polygon_index not in replacements]
    source_triangles.extend(tri for triangles in replacements.values() for tri in triangles)
    # Tessellating boolean ngons with internal bridges can emit identical
    # triangles with opposite winding. They cancel as an oriented surface;
    # keeping both creates zero-thickness sheets/non-manifold export data.
    groups = {}
    for ids in source_triangles:
        parity = sum(ids[i]>ids[j] for i in range(3) for j in range(i+1,3))%2
        groups.setdefault(tuple(sorted(ids)), [[],[]])[parity].append(ids)
    triangles = []
    cancelled = 0
    for positive,negative in groups.values():
        count = min(len(positive),len(negative))
        cancelled += 2*count
        positive,negative = positive[count:],negative[count:]
        if positive:
            triangles.append(positive[0])
        elif negative:
            triangles.append(negative[0])
    used = sorted({i for tri in triangles for i in tri})
    remap = {old_index:new_index for new_index,old_index in enumerate(used)}
    mesh = bpy.data.meshes.new(old.name+'_TRIS')
    mesh.from_pydata([tuple(old.vertices[i].co) for i in used], [],
                     [tuple(remap[i] for i in t) for t in triangles])
    bm = bmesh.new()
    collapses = 0
    max_edge = 0.
    try:
        bm.from_mesh(mesh)
        original_positions = {v:v.co.copy() for v in bm.verts}
        for _ in range(1000):
            candidates = []
            for face in bm.faces:
                if triangle_cross_squared(*(v.co for v in face.verts)) > 1e-30:
                    continue
                # The shortest edge may fail the link condition while another
                # microscopic edge in the same collinear face is safe to collapse.
                for edge in sorted(face.edges,key=lambda e:e.calc_length()):
                    if edge.calc_length() > .00002 or len(edge.link_faces) != 2:
                        continue
                    a,b = edge.verts
                    common = ({e.other_vert(a) for e in a.link_edges}-{b}) & ({e.other_vert(b) for e in b.link_edges}-{a})
                    opposite = {v for f in edge.link_faces for v in f.verts if v not in (a,b)}
                    if len(opposite)==2 and common == opposite:
                        candidates.append(edge)
                        break
            if not candidates:
                break
            edge = candidates[0]
            max_edge = max(max_edge, edge.calc_length())
            bmesh.ops.collapse(bm, edges=[edge], uvs=False)
            collapses += 1
        max_displacement = max(((v.co-original_positions[v]).length for v in bm.verts), default=0.)
        if max_displacement > .00002:
            raise RuntimeError('Tree numeric cleanup exceeded its 0.00002 mm displacement budget')
        # MANIFOLD can emit a detached, exactly collinear triangle at a numeric
        # junction (Luca Fine witness: extent 0.000000119 mm). It represents no
        # surface or volume. Remove only an isolated ZERO-area triangle within
        # the same precision budget, never a finite-area unrooted component.
        zero_surface_fragments = 0
        for face in list(bm.faces):
            if (triangle_cross_squared(*(v.co for v in face.verts)) <= 1e-30
                    and all(len(e.link_faces)==1 for e in face.edges)
                    and all(len(v.link_faces)==1 for v in face.verts)
                    and max(e.calc_length() for e in face.edges) <= .00002):
                bmesh.ops.delete(bm,geom=list(face.verts),context='VERTS')
                zero_surface_fragments += 1
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.update()
    obj.data = mesh
    if old.users == 0:
        bpy.data.meshes.remove(old)
    obj['fdm_tree_exact_duplicate_cap_fallbacks'] = duplicate_cap_fallbacks
    obj['fdm_tree_precision_collapses'] = collapses
    obj['fdm_tree_precision_max_edge_mm'] = max_edge
    obj['fdm_tree_precision_max_displacement_mm'] = max_displacement
    obj['fdm_tree_cancelled_opposite_triangles'] = cancelled
    obj['fdm_tree_zero_surface_fragments'] = zero_surface_fragments


def topology(obj, require_single=True):
    verts, tris = world_mesh(obj)
    bm = bmesh.new()
    try:
        for co in verts:
            bm.verts.new(co)
        bm.verts.ensure_lookup_table()
        for tri in tris:
            bm.faces.new(tuple(bm.verts[i] for i in tri))
        bm.normal_update()
        unseen = set(bm.verts)
        component_z = []
        component_info = []
        while unseen:
            todo = [unseen.pop()]
            z = []
            component = []
            while todo:
                vert = todo.pop()
                z.append(vert.co.z)
                component.append(vert)
                for edge in vert.link_edges:
                    neighbor = edge.other_vert(vert)
                    if neighbor in unseen:
                        unseen.remove(neighbor)
                        todo.append(neighbor)
            component_z.append(min(z))
            faces = {f for v in component for f in v.link_faces}
            anchor = component[0].co
            volume = sum((f.verts[0].co-anchor).dot((f.verts[1].co-anchor).cross(f.verts[2].co-anchor))/6 for f in faces)
            component_info.append(dict(vertices=len(component), z_min=min(z), z_max=max(z), volume_mm3=volume))
        report = dict(vertices=len(verts), triangles=len(tris),
            nonfinite_vertices=sum(not all(math.isfinite(c) for c in v) for v in verts),
            nonmanifold_edges=sum(not e.is_manifold for e in bm.edges),
            inconsistent_edges=sum(e.is_manifold and not e.is_contiguous for e in bm.edges),
            degenerate_faces=sum(triangle_cross_squared(*(v.co for v in f.verts)) <= 1e-30 for f in bm.faces),
            components=len(component_z),
            component_info=component_info,
            ungrounded_components=sum(abs(z) > TOL for z in component_z),
            z_min=min(v.z for v in verts) if verts else None,
            bottom_triangles=sum(all(verts[i].z == 0.0 for i in t) for t in tris),
            volume_mm3=bm.calc_volume(signed=True) if bm.faces else 0.)
        report['pass'] = bool(tris and report['nonmanifold_edges']==0
            and report['inconsistent_edges']==0 and report['degenerate_faces']==0
            and report['nonfinite_vertices']==0 and all(c['volume_mm3']>1e-12 for c in component_info)
            and report['ungrounded_components']==0 and report['bottom_triangles']>0
            and report['volume_mm3']>0 and (not require_single or report['components']==1))
        return report
    finally:
        bm.free()


def _surface_clear(verts, tris, collider, gap, max_depth=20):
    """Bound EVERY raft triangle continuously, rather than its vertices only."""
    queries = 0
    for tri in tris:
        pending = [(tuple(verts[i] for i in tri), 0)]
        while pending:
            (a,b,c), depth = pending.pop()
            center = (a+b+c)/3
            hit = collider.find_nearest(center)
            queries += 1
            if not hit or hit[0] is None or not collider.outside(center, hit):
                return False, 'raft_inside_or_touching_mini', queries
            radius = max((p-center).length for p in (a,b,c))
            if hit[3]-radius > gap+TOL:
                continue
            if hit[3] <= gap+TOL:
                return False, 'raft_clearance', queries
            if depth >= max_depth or queries > 200000:
                return False, 'raft_clearance_uncertified', queries
            pairs = [(a,b,c), (b,c,a), (c,a,b)]
            x,y,z = max(pairs, key=lambda p:(p[1]-p[0]).length_squared)
            mid = (x+y)/2
            pending.extend((((x,mid,z), depth+1), ((mid,y,z), depth+1)))
    return True, None, queries


def validate_raft(raft, model, collider, gap):
    verts, tris = world_mesh(raft)
    clear, reason, queries = _surface_clear(verts, tris, collider, gap)
    if not clear:
        raise RuntimeError(f'Tree raft rejected: {reason} ({queries} queries)')
    # Surface separation alone misses a MINI completely enclosed in the raft.
    raft_bvh = BVHTree.FromPolygons(verts, tris, all_triangles=True)
    low = Vector(tuple(min(v[i] for v in verts) for i in range(3)))
    high = Vector(tuple(max(v[i] for v in verts) for i in range(3)))
    mini_verts, _ = world_mesh(model)
    for p in mini_verts:
        if all(low[i]-TOL <= p[i] <= high[i]+TOL for i in range(3)):
            hit = raft_bvh.find_nearest(p)
            if hit[0] is not None and (p-hit[0]).dot(hit[1]) <= TOL:
                raise RuntimeError('Tree raft rejected: MINI contained in raft')
    return dict(pass_gate=True, surface_queries=queries, required_gap_mm=gap)


def context(edges, cfg):
    return dict(use_raft=bool(cfg.get('use_raft', True)),joints=junctions(edges),joint_policy='INSCRIBED_ENDPOINT_BALL_V1',
        gap_mm=float(cfg.get('tree_model_clearance', .45)),
        zones=[dict(center=list(e.contact_zone[0]), radius=e.contact_zone[1])
               for e in edges if e.kind=='TIP_CONE' and e.contact_zone],
        tips=[list(e.a) for e in edges if e.kind=='TIP_CONE'])


def validate_support(model, support, ctx=None, collider=None):
    """Validate the actual unified surface, also usable AFTER export repair."""
    if ctx is None:
        text = support.get(CONTEXT_KEY)
        if not text:
            raise RuntimeError('Tree export rejected: missing mesh QA context; regenerate supports')
        ctx = json.loads(text)
        if ctx.get('joint_policy')!='INSCRIBED_ENDPOINT_BALL_V1' or 'joints' not in ctx:
            raise RuntimeError('Tree export rejected: regenerate supports for checked neck/tip junctions')
    report = topology(support, require_single=ctx['use_raft'])
    if not report['pass']:
        raise RuntimeError(f'Tree mesh topology gate failed: {report}')
    collider = collider or tree_collision.ModelCollider(model)
    verts, tris = world_mesh(support)
    support_bvh = BVHTree.FromPolygons(verts, tris, all_triangles=True)
    joint_min_ratio=None
    joint_geometry=None
    for joint in ctx.get('joints',[]):
        point=Vector(joint['center']);hit=support_bvh.find_nearest(point)
        if not hit or hit[0] is None or hit[3] < joint['core_radius']-TOL:
            raise RuntimeError('Tree junction neck core is missing or too thin')
        counts=[tree_collision.ray_winding(support_bvh,point,d.normalized())
            for d in (Vector((1,.371,.529)),Vector((-.217,1,.413)))]
        if counts!=[1,1]:
            if joint_geometry is None:joint_geometry=tree_collision.prepare_solid_angles(verts,tris)
            winding=tree_collision.solid_angle_winding(point,verts,tris,prepared=joint_geometry)
            if not math.isfinite(winding) or abs(winding-1.)>.0001:
                raise RuntimeError('Tree junction neck core is not inside the support solid')
        ratio=hit[3]/joint['radius']
        joint_min_ratio=ratio if joint_min_ratio is None else min(joint_min_ratio,ratio)
    report['rounded_joints']=len(ctx.get('joints',[]))
    report['joint_min_core_radius_ratio']=joint_min_ratio
    zones = [(Vector(z['center']), z['radius']+TOL) for z in ctx['zones']]
    low = Vector(tuple(min(v[i] for v in verts) for i in range(3)))
    high = Vector(tuple(max(v[i] for v in verts) for i in range(3)))
    bounds=[low,high]+[p for _,lo,hi in collider.shells for p in (lo,hi)]
    guard=containment.roundoff_guard(max(abs(c) for p in bounds for c in p),TOL)
    # KD-tree only broad-phases the original exact sphere predicate.
    from mathutils.kdtree import KDTree
    zone_tree=KDTree(len(zones)) if zones else None
    if zone_tree is not None:
        for i,(center,radius) in enumerate(zones):zone_tree.insert(center,i)
        zone_tree.balance()
    zone_range=max((r for _,r in zones),default=0.)+guard
    def allowed(point):
        if zone_tree is None:return False
        return any((point-zones[i][0]).length<=zones[i][1] for _,i,_ in zone_tree.find_range(point,zone_range))
    forbidden_pairs = 0
    for _mini_idx, support_idx in collider.bvh.overlap(support_bvh):
        # A triangle must be wholly inside ONE local approved cone bound;
        # partial/ambiguous exemptions fail closed.
        tri = tris[support_idx]
        if not any(all((verts[i]-center).length <= radius for i in tri)
                   for center,radius in zones):
            forbidden_pairs += 1
    support_membership=containment.classify(verts,tris,(not allowed(p) for p in verts),
        collider.find_nearest,collider.outside_winding,guard=guard)
    inside_vertices=support_membership['inside']
    if forbidden_pairs or inside_vertices:
        raise RuntimeError(f'Tree final mesh collision gate failed: {forbidden_pairs} triangle pairs, {inside_vertices} inside vertices')
    mini_verts, mini_tris = world_mesh(model)
    false_containment_screens = 0
    winding_geometry = None
    def observe_nearest(index,point,hit):
        nonlocal false_containment_screens
        if hit and hit[0] is not None and (point-hit[0]).dot(hit[1]) < -TOL:
            false_containment_screens+=1
    def outside_support(point):
        nonlocal winding_geometry
        counts=[tree_collision.ray_winding(support_bvh,point,d.normalized())
                for d in (Vector((1,.371,.529)),Vector((-.217,1,.413)))]
        if counts==[0,0]:return True
        if winding_geometry is None:winding_geometry=tree_collision.prepare_solid_angles(verts,tris)
        winding=tree_collision.solid_angle_winding(point,verts,tris,prepared=winding_geometry)
        return math.isfinite(winding) and abs(winding)<=.0001
    mini_membership=containment.classify(mini_verts,mini_tris,
        (not allowed(p) and all(low[i]<=p[i]<=high[i] for i in range(3)) for p in mini_verts),
        support_bvh.find_nearest,outside_support,guard=guard,on_nearest=observe_nearest)
    if mini_membership['inside']:
        point=mini_verts[mini_membership['first_inside']]
        raise RuntimeError(f'Tree final mesh collision gate failed: MINI enclosed in support solid at {tuple(point)}')
    missing_tips = 0
    for zone in ctx['zones']:
        hit = collider.find_nearest(Vector(zone['center']))
        if hit[0] is None or hit[3] > .001:
            raise RuntimeError('Tree export changed the MINI contact surface; regenerate against repaired MINI')
    for tip in ctx['tips']:
        point = Vector(tip)
        hit = support_bvh.find_nearest(point)
        # A contact witness must still be on or in the united solid.
        if hit[0] is None or (hit[3] > .001 and (point-hit[0]).dot(hit[1]) > TOL):
            missing_tips += 1
    if missing_tips:
        raise RuntimeError(f'Tree mesh lost {missing_tips} contact tips during union/repair')
    report.update(forbidden_triangle_pairs=forbidden_pairs, inside_vertices=inside_vertices,
                  false_containment_screens=false_containment_screens,
                  retained_tip_witnesses=len(ctx['tips']), missing_tips=missing_tips,
                  containment_proof=dict(support=support_membership,mini=mini_membership))
    return report

