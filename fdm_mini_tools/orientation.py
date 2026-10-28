"""Geometry-based pose search. Face protection is a heuristic, not recognition.

Automatic mode weights upper central detail; a user-defined front can override
the estimate. No contact is suppressed: SLASG and the collision gates still run
on the chosen pose. Scores describe support risk, not measured print quality.
"""
import math
import numpy as np
from mathutils import Matrix, Vector

FRONT_KEY = 'fdm_front_direction_local'


def geometry(obj):
    import bpy
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        return _geometry_mesh(mesh)
    finally:
        evaluated.to_mesh_clear()


def _geometry_mesh(mesh):
    n = len(mesh.polygons)
    if not n or not len(mesh.vertices):
        raise ValueError('Empty MINI cannot be oriented')
    xyz = np.empty(len(mesh.vertices)*3, dtype=np.float64)
    mesh.vertices.foreach_get('co', xyz)
    xyz = xyz.reshape(-1, 3)
    normals = np.empty(n*3, dtype=np.float64)
    mesh.polygons.foreach_get('normal', normals)
    normals = normals.reshape(-1, 3)
    centers = np.array([p.center[:] for p in mesh.polygons], dtype=np.float64)
    area = np.array([p.area for p in mesh.polygons], dtype=np.float64)
    lo, hi = xyz.min(axis=0), xyz.max(axis=0)
    centers -= (lo+hi)/2
    # Local normal variation, averaged through vertices. Mesh density alone
    # must not make a flat, heavily triangulated patch look like facial detail.
    loop_vertex = np.empty(len(mesh.loops), dtype=np.int32)
    mesh.loops.foreach_get('vertex_index', loop_vertex)
    count = np.array([p.loop_total for p in mesh.polygons])
    loop_face = np.repeat(np.arange(n), count)
    summed = np.zeros_like(xyz)
    np.add.at(summed, loop_vertex, normals[loop_face]*area[loop_face,None])
    summed /= np.maximum(np.linalg.norm(summed,axis=1)[:,None], 1e-15)
    variation = 1-np.einsum('ij,ij->i',normals[loop_face],summed[loop_vertex])
    curvature = np.zeros(n)
    np.add.at(curvature, loop_face, np.maximum(0,variation))
    curvature /= np.maximum(count,1)
    span = np.maximum(hi-lo, 1e-8)
    height = (centers[:,2]+span[2]/2)/span[2]
    # Exclude the base and outstretched weapons from the head/detail proxy.
    central = ((np.abs(centers[:,0]) < span[0]*.22) &
               (np.abs(centers[:,1]) < span[1]*.22) &
               (height > .60) & (height < .96))
    detail = central * (1+np.minimum(curvature*20,4))
    return normals, centers, area, detail, height


def estimate_front(normals, area, detail):
    weights = area*detail
    moment = np.sum(normals[:,:2]*weights[:,None],axis=0)
    confidence = float(np.linalg.norm(moment)/max(float(weights.sum()),1e-12))
    if confidence < .08:
        return None, confidence
    return Vector((float(moment[0]),float(moment[1]),0)).normalized(), confidence


def score(data, rotation, overhang_deg, front=None):
    normals, centers, area, detail, height = data
    mat = np.asarray(rotation, dtype=np.float64)
    rotated = normals @ mat.T
    down = rotated[:,2] < -math.cos(math.radians(overhang_deg))
    front_weight = np.zeros(len(area))
    if front is not None:
        f = np.asarray(front, dtype=np.float64)
        front_weight = np.maximum(0,normals @ f) * (height > .45)
    weight = 1+4*detail+6*front_weight
    z = (centers @ mat.T)[:,2]
    cost = area * (1+np.maximum(z,0)*.01)*(1+np.abs(rotated[:,2]))
    return dict(score=float(np.sum(cost[down]*weight[down])),
        overhang_area_mm2=float(area[down].sum()),
        detail_overhang_area_mm2=float(np.sum(area[down]*detail[down])),
        front_overhang_area_mm2=float(np.sum(area[down]*front_weight[down])))


def choose(obj, overhang_deg=45, front_mode='AUTO'):
    data = geometry(obj)
    front, confidence = estimate_front(data[0],data[2],data[3])
    source = 'geometry estimate' if front is not None else 'ambiguous; detail weighting only'
    if front_mode == 'VIEW':
        stored = obj.get(FRONT_KEY)
        if stored is None:
            raise ValueError("Front direction is missing; use the current view as front first")
        front = Vector(stored).normalized()
        source, confidence = 'user view', 1.
    elif front_mode != 'AUTO':
        front = {'POS_Y':Vector((0,1,0)), 'NEG_Y':Vector((0,-1,0)),
                 'POS_X':Vector((1,0,0)), 'NEG_X':Vector((-1,0,0))}[front_mode]
        source, confidence = 'user axis', 1.
    if front is not None:
        horizontal = Vector((front.x,front.y,0))
        if horizontal.length < .2:
            raise ValueError("Front direction is almost vertical; use a side view")
        yaw_values = (math.atan2(front.x,front.y),)
    else:
        yaw_values = (0,math.pi/2,math.pi,3*math.pi/2)
    best = None
    for yaw in yaw_values:
        for x in (25,30,35,40,45):
            for y in (-12,-7,0,7,12):
                rot = (Matrix.Rotation(math.radians(y),3,'Y') @
                       Matrix.Rotation(math.radians(x),3,'X') @ Matrix.Rotation(yaw,3,'Z'))
                if front is not None and (rot @ front).z < .25:
                    continue
                row = score(data,rot,overhang_deg,front)
                cost = row['score']*(1+(x+abs(y))*.0015)
                key = (cost,x,abs(y),y,yaw)
                if best is None or key < best[0]:
                    best = key,rot,row
    if best is None:
        raise ValueError("No safe orientation for the selected front direction")
    _,rot,row = best
    row.update(front_source=source,front_confidence=confidence,
        front_direction=list(front) if front is not None else None,
        rotation_matrix=[list(r) for r in rot],
        note='Geometry heuristic; no semantic face recognition or print-quality proof')
    return rot,row
