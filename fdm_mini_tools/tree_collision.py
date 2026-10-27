"""Conservative Tree collision predicates, independent of SLASG bindings.

Distances to a surface are 1-Lipschitz. At an interval midpoint, distance
minus half the interval length bounds the ENTIRE centerline interval below.
Adding the maximum interpolated radius bounds the swept body, including caps.
Uncertified intervals fail closed; reducing the subdivision limit cannot
silently turn a collision into an accepted route.
"""
import math
from collections import Counter
from .containment import roundoff_guard

import bmesh
from mathutils import Vector
from mathutils.bvhtree import BVHTree

EPS_MM = 0.0001
NEAREST_CACHE_LIMIT = 65536
SEGMENT_CACHE_LIMIT = 32768


def _bounds_contains(bounds, point):
    lo, hi = bounds
    x, y, z = point
    return lo[0] <= x <= hi[0] and lo[1] <= y <= hi[1] and lo[2] <= z <= hi[2]


class ShellBoundsIndex:
    """Exact broad phase over immutable shell AABBs; never a solid classifier."""
    def __init__(self, shells):
        self.bounds = [(tuple(lo), tuple(hi)) for _, lo, hi in shells]
        def build(indices):
            lo = tuple(min(self.bounds[i][0][axis] for i in indices) for axis in range(3))
            hi = tuple(max(self.bounds[i][1][axis] for i in indices) for axis in range(3))
            if len(indices) <= 4:
                return (lo, hi), tuple(indices), None, None
            axis = max(range(3), key=lambda k: hi[k]-lo[k])
            indices.sort(key=lambda i: self.bounds[i][0][axis]+self.bounds[i][1][axis])
            middle = len(indices)//2
            return (lo, hi), (), build(indices[:middle]), build(indices[middle:])
        self.root = build(list(range(len(shells)))) if shells else None

    def candidates(self, point):
        pending = [self.root] if self.root is not None else []
        found = []
        while pending:
            bounds, indices, left, right = pending.pop()
            if not _bounds_contains(bounds, point):
                continue
            if indices:
                found.extend(i for i in indices if _bounds_contains(self.bounds[i], point))
            else:
                pending.extend((right, left))
        # Preserve original shell order, including overlapping/nested solids.
        return sorted(found)


class ModelCollider:
    """World-space closed, consistently oriented, positive-volume shells.

Classify against each shell separately: overlapping/disconnected solids must
not cancel through odd/even counting on a combined mesh. Nearest oriented
surface classification assumes non-self-intersecting shells. Open meshes,
reversed shells and inconsistent winding are unsupported and rejected.
"""
    def __init__(self, model):
        import bpy
        deps = bpy.context.evaluated_depsgraph_get()
        evaluated = model.evaluated_get(deps)
        mesh = evaluated.to_mesh()
        bm = bmesh.new()
        try:
            bm.from_mesh(mesh)
            bm.transform(evaluated.matrix_world)
            bm.normal_update()
            if not bm.faces or any(not e.is_manifold or not e.is_contiguous for e in bm.edges):
                raise RuntimeError('Tree collision validation requires a closed MINI with consistent face winding.')
            bmesh.ops.triangulate(bm, faces=list(bm.faces))
            bm.verts.index_update()
            bm.faces.index_update()
            pending = set(bm.faces)
            self.shells = []
            self.shell_geometry = []
            # Preserve original triangle ordering for nearest-face tie breaks.
            # Set/BFS iteration order must not change contact normals per run.
            all_vertices = [v.co.copy() for v in bm.verts]
            all_faces = [tuple(v.index for v in face.verts) for face in bm.faces]
            while pending:
                todo = [pending.pop()]
                faces = []
                while todo:
                    face = todo.pop()
                    faces.append(face)
                    for edge in face.edges:
                        for neighbor in edge.link_faces:
                            if neighbor in pending:
                                pending.remove(neighbor)
                                todo.append(neighbor)
                faces.sort(key=lambda face: face.index)
                verts = sorted({v for face in faces for v in face.verts}, key=lambda v: v.index)
                indices = {v: i for i, v in enumerate(verts)}
                xyz = [v.co.copy() for v in verts]
                polys = [tuple(indices[v] for v in face.verts) for face in faces]
                anchor = xyz[0]
                volume = 0.0
                for i, j, k in polys:
                    a, b, c = xyz[i]-anchor, xyz[j]-anchor, xyz[k]-anchor
                    if (b-a).cross(c-a).length_squared <= 1e-20:
                        raise RuntimeError('Tree collision validation found a degenerate MINI triangle.')
                    volume += a.dot(b.cross(c))/6.0
                if volume <= 1e-9:
                    raise RuntimeError('Tree collision validation requires outward positive-volume MINI shells.')
                low = Vector(tuple(min(v[i] for v in xyz) for i in range(3)))
                high = Vector(tuple(max(v[i] for v in xyz) for i in range(3)))
                self.shells.append((BVHTree.FromPolygons(xyz, polys, all_triangles=True), low, high))
                self.shell_geometry.append((xyz, polys))
            self.bvh = BVHTree.FromPolygons(all_vertices, all_faces, all_triangles=True)
            self._shell_index = ShellBoundsIndex(self.shells)
            self.rejections = Counter()
            # The collider owns an immutable, evaluated world-space snapshot.
            # Exact point keys only: no rounding or spatial approximation.
            self._nearest_cache = {}
            self.nearest_queries = self.nearest_cache_hits = 0
            self._segment_certificates = {}
            self.segment_certificate_hits = 0
            self.ray_rejections = 0
            self._winding_cache = {}
            self._solid_angle_geometry = {}
            self._air_balls = {}
            self._air_ball_hits = 0
            self._full_winding_calls = 0
            magnitude=max(abs(c) for _,lo,hi in self.shells for p in (lo,hi) for c in p)
            self._air_guard=roundoff_guard(magnitude,EPS_MM)
        finally:
            bm.free()
            evaluated.to_mesh_clear()

    def find_nearest(self, point):
        budget = getattr(self, '_active_search_budget', None)
        if budget is not None: budget.check()
        key = tuple(float(c) for c in point)
        self.nearest_queries += 1
        cache = self._nearest_cache
        if key in cache:
            self.nearest_cache_hits += 1
            hit = cache[key]
        else:
            result = self.bvh.find_nearest(point)
            # Never expose cache-owned mutable mathutils vectors to callers.
            hit = (tuple(result[0]) if result[0] is not None else None,
                   tuple(result[1]) if result[1] is not None else None,
                   result[2], result[3])
            if all(math.isfinite(c) for c in key):
                if len(cache) >= NEAREST_CACHE_LIMIT:
                    cache.clear()
                cache[key] = hit
        return (Vector(hit[0]) if hit[0] is not None else None,
                Vector(hit[1]) if hit[1] is not None else None, hit[2], hit[3])

    def ray_cast(self, *args):
        return self.bvh.ray_cast(*args)

    def outside(self, point, nearest=None):
        if not all(math.isfinite(c) for c in point):
            return False
        for shell_index in self._shell_index.candidates(point):
            shell, low, high = self.shells[shell_index]
            hit = nearest if len(self.shells) == 1 and nearest is not None else shell.find_nearest(point)
            if not hit or hit[0] is None or hit[1] is None:
                return False
            if (point-hit[0]).dot(hit[1]) <= 0:
                # A single nearest face is ambiguous at corners and folded
                # shells. Require independent winding evidence before calling
                # this point interior; distance/radius bounds stay unchanged.
                return self.outside_winding(point)
        return True

    def outside_winding(self, point):
        """Independent classifier and fallback for ambiguous nearest normals.

        An oriented nearest face at an edge/complex shell is not sufficient
        evidence of containment. Require zero oriented winding in two rays
        against EACH shell, rejecting disagreement/numeric ambiguity.
        """
        key=tuple(float(x) for x in point)
        if key in self._winding_cache:return self._winding_cache[key]
        if not all(math.isfinite(c) for c in key):return False
        in_bounds=bool(self._shell_index.candidates(point))
        if not in_bounds:result=True
        elif self._certified_air(key):
            self._air_ball_hits+=1;result=True
        else:
            self._full_winding_calls+=1
            result=self._outside_winding_uncached(point)
            if result:
                hit=self.bvh.find_nearest(point)
                if hit and hit[0] is not None and hit[3] is not None and math.isfinite(hit[3]):
                    radius=min(1.,float(hit[3])-self._air_guard)
                    if radius>0:
                        cell=tuple(math.floor(c) for c in key)
                        if cell not in self._air_balls and len(self._air_balls)>=4096:self._air_balls.clear()
                        balls=self._air_balls.setdefault(cell,[])
                        balls.append((key,radius))
                        if len(balls)>8:del balls[0]
        if len(self._winding_cache)>=8192:self._winding_cache.clear()
        self._winding_cache[key]=result
        return result

    def _certified_air(self,point):
        # A ball smaller than the unsigned distance to EVERY model surface
        # cannot cross any shell. Only independently certified OUTSIDE balls
        # are stored; false/ambiguous classifications are never propagated.
        x,y,z=(math.floor(c) for c in point)
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                for dz in (-1,0,1):
                    for center,radius in self._air_balls.get((x+dx,y+dy,z+dz),()):
                        if math.dist(point,center)<radius:return True
        return False

    def _outside_winding_uncached(self, point):
        for shell_index in self._shell_index.candidates(point):
            shell, low, high = self.shells[shell_index]
            counts = [ray_winding(shell, point, direction) for direction in
                      (Vector((1,.371,.529)).normalized(), Vector((-.217,1,.413)).normalized())]
            if counts == [1,1]:return False
            if counts != [0,0]:
                # Thin, close surfaces can produce duplicate/missed float32
                # ray hits. Resolve these cases with float64 solid angles.
                vertices, triangles = self.shell_geometry[shell_index]
                if shell_index not in self._solid_angle_geometry:
                    self._solid_angle_geometry[shell_index]=prepare_solid_angles(vertices,triangles)
                winding = solid_angle_winding(point,vertices,triangles,
                    prepared=self._solid_angle_geometry[shell_index])
                if not math.isfinite(winding) or abs(winding) > .0001:
                    return False
        return True


def prepare_solid_angles(vertices,triangles):
    import numpy as np
    xyz=np.asarray(vertices,dtype=np.float64)
    faces=np.asarray(triangles,dtype=np.intp).reshape((-1,3))
    return xyz,faces


def solid_angle_winding(point,vertices,triangles,prepared=None):
    """Same float64 solid-angle formula, evaluated in bounded NumPy chunks.

    No triangles are sampled or omitted. Keep compensated summation and the
    original scalar implementation at the containment decision boundary.
    """
    import numpy as np
    xyz,faces=prepared if prepared is not None else prepare_solid_angles(vertices,triangles)
    if not len(faces):return 0.0
    vectors=xyz-np.asarray(point,dtype=np.float64)
    squared=vectors*vectors
    lengths=np.sqrt((squared[:,0]+squared[:,1])+squared[:,2])
    totals=[]
    def dot(a,b):return (a[:,0]*b[:,0]+a[:,1]*b[:,1])+a[:,2]*b[:,2]
    for start in range(0,len(faces),16384):
        ids=faces[start:start+16384]
        a,b,c=vectors[ids[:,0]],vectors[ids[:,1]],vectors[ids[:,2]]
        la,lb,lc=lengths[ids[:,0]],lengths[ids[:,1]],lengths[ids[:,2]]
        if np.any(np.minimum(np.minimum(la,lb),lc)<=.0000001):return float('nan')
        determinant=a[:,0]*(b[:,1]*c[:,2]-b[:,2]*c[:,1])-a[:,1]*(b[:,0]*c[:,2]-b[:,2]*c[:,0])+a[:,2]*(b[:,0]*c[:,1]-b[:,1]*c[:,0])
        denominator=la*lb*lc+dot(a,b)*lc+dot(b,c)*la+dot(c,a)*lb
        totals.append(math.fsum(2*np.arctan2(determinant,denominator)))
    winding=math.fsum(totals)/(4*math.pi)
    if math.isfinite(winding) and abs(abs(winding)-.0001)<1e-10:
        return _solid_angle_winding_reference(point,vertices,triangles)
    return winding


def _solid_angle_winding_reference(point, vertices, triangles):
    vectors = [tuple(float(v[i])-float(point[i]) for i in range(3)) for v in vertices]
    lengths = [math.sqrt(sum(c*c for c in v)) for v in vectors]
    angles = []
    def dot(a,b):
        return sum(a[i]*b[i] for i in range(3))
    for i,j,k in triangles:
        a,b,c = vectors[i],vectors[j],vectors[k]
        la,lb,lc = lengths[i],lengths[j],lengths[k]
        if min(la,lb,lc) <= .0000001:
            return float('nan')
        determinant = a[0]*(b[1]*c[2]-b[2]*c[1])-a[1]*(b[0]*c[2]-b[2]*c[0])+a[2]*(b[0]*c[1]-b[1]*c[0])
        denominator = la*lb*lc+dot(a,b)*lc+dot(b,c)*la+dot(c,a)*lb
        angles.append(2*math.atan2(determinant, denominator))
    return math.fsum(angles)/(4*math.pi)


def ray_winding(bvh, point, direction):
    origin = point.copy()
    winding = 0
    # Advance beyond several float32 ULPs, otherwise the same triangle can
    # be hit again at distance zero at normal MINI world coordinates.
    magnitude = max(1., *(abs(c) for c in point))
    step = max(.00001, 8*2**(math.floor(math.log2(magnitude))-23))
    if step >= EPS_MM:
        return None
    for _ in range(4096):
        hit = bvh.ray_cast(origin, direction)
        if not hit or hit[0] is None:
            return winding
        dot = hit[1].dot(direction)
        if abs(dot) < .000001 or hit[3] < .000001:
            return None
        winding += 1 if dot > 0 else -1
        origin = hit[0]+direction*step
    return None


def outside(bvh, point, nearest):
    if hasattr(bvh, 'outside'):
        return bvh.outside(point, nearest)
    # For standalone closed outward fixture BVHs; production uses ModelCollider.
    return bool(nearest and nearest[0] is not None and nearest[1] is not None
                and (point-nearest[0]).dot(nearest[1]) > 0)


def segment_clear(bvh, a, b, radius_a, radius_b, gap=0.0, max_depth=18, max_queries=4096):
    """Reuse only successful, exact certificates against this collider snapshot."""
    cache=getattr(bvh,'_segment_certificates',None)
    key=(*a,*b,radius_a,radius_b,gap,max_depth,max_queries)
    if cache is not None and key in cache:
        bvh.segment_certificate_hits+=1
        return True
    result=_segment_clear_uncached(bvh,a,b,radius_a,radius_b,gap,max_depth,max_queries)
    if result and cache is not None:
        if len(cache)>=SEGMENT_CACHE_LIMIT:cache.clear()
        cache[key]=True
    return result


def _segment_clear_uncached(bvh, a, b, radius_a, radius_b, gap=0.0, max_depth=18, max_queries=4096):
    """Certify a linearly tapered capsule. False includes numeric uncertainty.

Capsules conservatively contain the emitted flat-capped polygonal tubes.
This deliberately trades some valid routes for absence of sample gaps.
"""
    def reject(reason):
        if hasattr(bvh, 'rejections'):
            bvh.rejections[reason] += 1
        return False

    values = [*a, *b, radius_a, radius_b, gap]
    if not all(math.isfinite(v) for v in values) or min(radius_a, radius_b, gap) < 0:
        return reject('invalid_segment')
    length = (b-a).length
    if length < 0.0001:
        return reject('degenerate_segment')
    queries = 0
    # A hit can reject a blocked centerline cheaply. A miss NEVER certifies
    # the finite-radius branch; retain all continuous radius/gap checks.
    if length >= 2. and hasattr(bvh,'ray_cast'):
        budget=getattr(bvh,'_active_search_budget',None)
        if budget is not None:budget.check()
        hit=bvh.ray_cast(a,(b-a).normalized(),length)
        if hit and hit[0] is not None and hit[3] is not None and EPS_MM < hit[3] < length-EPS_MM:
            if hasattr(bvh,'ray_rejections'):bvh.ray_rejections+=1
            return reject('centerline_collision')

    def probe(t):
        nonlocal queries
        queries += 1
        point = a.lerp(b, t)
        hit = bvh.find_nearest(point)
        if not hit or hit[0] is None or hit[3] is None or not math.isfinite(hit[3]):
            return None, 'missing_surface_query'
        radius = radius_a*(1-t)+radius_b*t
        if hit[3] <= radius+gap+EPS_MM:
            return None, 'radius_or_gap_collision'
        # The cheap distance rejection already proves this capsule invalid.
        # Only classify points which can still satisfy the radius/gap bound.
        if not outside(bvh, point, hit):
            return None, 'inside_or_on_mini'
        return hit[3], None

    for t in (0.0, 1.0):
        _, reason = probe(t)
        if reason:
            return reject(reason)
    pending = [(0.0, 1.0, 0)]
    while pending:
        lo, hi, depth = pending.pop()
        distance, reason = probe((lo+hi)*0.5)
        if reason:
            return reject(reason)
        r0 = radius_a*(1-lo)+radius_b*lo
        r1 = radius_a*(1-hi)+radius_b*hi
        half_length = length*(hi-lo)*0.5
        if distance-half_length > max(r0, r1)+gap+EPS_MM:
            continue
        if depth >= max_depth or queries >= max_queries or half_length <= EPS_MM:
            return reject('uncertified_clearance')
        mid = (lo+hi)*0.5
        pending.extend(((lo, mid, depth+1), (mid, hi, depth+1)))
    return True
