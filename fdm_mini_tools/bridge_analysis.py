"""Conservative layer-grid screening, not a substitute for slicer/print QA.

Unsupported cells require two continuous previous-layer anchors to be bridge
candidates. Cantilevers and detached islands must never become bridges merely
because a nearby surface is closer than the profile span.
"""
import math
import numpy as np


def _dilate(mask):
    padded = np.pad(mask, 1)
    return np.logical_or.reduce([padded[y:y+mask.shape[0], x:x+mask.shape[1]]
                                for y in range(3) for x in range(3)])


def classify_layer(current, previous, cell_mm, span_limit_mm, anchor_mm=.4):
    current, previous = np.asarray(current, bool), np.asarray(previous, bool)
    if current.shape != previous.shape or current.ndim != 2:
        raise ValueError('Layer masks must have matching 2-D shapes')
    if cell_mm <= 0 or not math.isfinite(cell_mm) or span_limit_mm < 0:
        raise ValueError('Invalid bridge grid/span')
    unsupported = current & ~previous
    candidate = np.zeros_like(current)
    spans = np.zeros(current.shape, dtype=float)
    anchor_cells = max(1, math.ceil(anchor_mm/cell_mm))
    for transpose in (False, True):
        gaps = unsupported.T if transpose else unsupported
        solid = previous.T if transpose else previous
        target = candidate.T if transpose else candidate
        lengths = spans.T if transpose else spans
        for row in range(gaps.shape[0]):
            indices = np.flatnonzero(gaps[row])
            if not len(indices):
                continue
            for run in np.split(indices, np.flatnonzero(np.diff(indices) > 1)+1):
                start, end = int(run[0]), int(run[-1])+1
                length = len(run)*cell_mm
                if start < anchor_cells or end+anchor_cells > gaps.shape[1]:
                    continue
                if (length <= span_limit_mm+1e-9 and
                    solid[row, start-anchor_cells:start].all() and
                    solid[row, end:end+anchor_cells].all()):
                    target[row, start:end] = True
                    old = lengths[row, start:end]
                    lengths[row, start:end] = np.where(old > 0, np.minimum(old,length),length)
    unseen = set(map(tuple, np.argwhere(unsupported)))
    connected_previous = _dilate(previous)
    regions = []
    while unseen:
        seed = min(unseen)
        unseen.remove(seed)
        todo, cells = [seed], []
        while todo:
            y,x = todo.pop()
            cells.append((y,x))
            for neighbor in ((y-1,x),(y+1,x),(y,x-1),(y,x+1)):
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    todo.append(neighbor)
        ys, xs = np.array(cells).T
        two_anchors = bool(candidate[ys,xs].all())
        kind = ('BRIDGE_CANDIDATE' if two_anchors else
                'CANTILEVER' if connected_previous[ys,xs].any() else 'ISLAND')
        regions.append(dict(kind=kind, cells=len(cells), area_mm2=len(cells)*cell_mm**2,
            span_mm=float(spans[ys,xs].max()) if two_anchors else None,
            center_cell=[float(xs.mean()),float(ys.mean())], verified=False))
    return regions


def slice_mask(triangles, z, origin_xy, shape, cell_mm):
    """Rasterize closed-shell sections. Union shells rather than XOR overlaps.

    triangles is one shell. Callers OR the masks of disconnected/overlapping
    solids, preserving the model's union semantics.
    """
    triangles = np.asarray(triangles, dtype=float)
    mask = np.zeros(shape, dtype=bool)
    if not len(triangles):
        return mask
    tri = triangles[(triangles[:,:,2].min(axis=1) <= z) &
                    (triangles[:,:,2].max(axis=1) > z)]
    segments = []
    for a,b in ((0,1),(1,2),(2,0)):
        p,q = tri[:,a],tri[:,b]
        cross = (p[:,2] <= z) != (q[:,2] <= z)
        p,q = p[cross],q[cross]
        if len(p):
            hits = p + ((z-p[:,2])/(q[:,2]-p[:,2]))[:,None]*(q-p)
            segments.append((cross, hits[:,:2]))
    # A generic plane crosses exactly two edges; vertices use a half-open rule.
    points = [[] for _ in range(len(tri))]
    for cross, hits in segments:
        for index, hit in zip(np.flatnonzero(cross),hits):
            points[index].append(hit)
    pairs = np.array([p for p in points if len(p)==2])
    if not len(pairs):
        return mask
    # Adjacent triangles compute the same section vertex through different
    # arithmetic paths. Normalize sub-nanometre roundoff before the half-open
    # scanline rule so a shared endpoint cannot be counted only once.
    pairs=np.round(pairs,8)
    for row in range(shape[0]):
        y = origin_xy[1]+(row+.5)*cell_mm
        a,b = pairs[:,0],pairs[:,1]
        cross = (a[:,1] <= y) != (b[:,1] <= y)
        a,b = a[cross],b[cross]
        hits = np.sort(a[:,0]+(y-a[:,1])/(b[:,1]-a[:,1])*(b[:,0]-a[:,0]))
        if len(hits)%2:
            raise RuntimeError('Ambiguous layer contour; bridge screen fails closed')
        for lo, hi in zip(hits[::2],hits[1::2]):
            start = max(0,math.ceil((lo-origin_xy[0])/cell_mm-.5))
            end = min(shape[1],math.ceil((hi-origin_xy[0])/cell_mm-.5))
            mask[row,start:end] = True
    return mask


def analyze(model, profile, max_cells=4000000):
    from .tree_collision import ModelCollider
    collider = ModelCollider(model)
    cell = max(.1,profile['summary']['nozzle_mm'])
    layer = profile['summary']['layer_mm']
    low = np.min([np.min(np.array(xyz,dtype=float),axis=0) for xyz,_ in collider.shell_geometry],axis=0)
    high = np.max([np.max(np.array(xyz,dtype=float),axis=0) for xyz,_ in collider.shell_geometry],axis=0)
    shape = tuple(int(math.ceil((high[i]-low[i])/cell))+2 for i in (1,0))
    if math.prod(shape)>max_cells:
        raise RuntimeError('Bridge analysis grid exceeds bounded memory budget')
    origin = low[:2]-cell
    shells = [np.array(xyz,dtype=float)[np.array(tris)] for xyz,tris in collider.shell_geometry]
    previous = np.zeros(shape,dtype=bool)
    counts = dict(BRIDGE_CANDIDATE=0, CANTILEVER=0, ISLAND=0)
    areas = dict.fromkeys(counts,0.)
    examples = []
    first=profile['summary']['first_layer_mm']
    layers = 1+max(0,math.ceil((high[2]-first)/layer))
    uncertain=[]
    for index in range(layers):
        z = float(first*.5 if index==0 else first+(index-.5)*layer)
        mask = np.zeros(shape,dtype=bool)
        try:
            for shell in shells:
                mask |= slice_mask(shell,z,origin,shape,cell)
        except RuntimeError as exc:
            uncertain.append(dict(z_mm=z,reason=str(exc)))
            # Fail closed for support removal, while retaining the candidate's
            # independently verified full Tree pipeline for comparison.
            previous=np.zeros(shape,dtype=bool)
            continue
        # The first occupied layer rests on the candidate's intended support or
        # bed. Its elevation is checked by the existing Tree/export pipeline.
        regions = classify_layer(mask,previous,cell,
            profile['summary']['profile_bridge_limit_mm'],max(.4,2*cell)) if index else []
        for region in regions:
            counts[region['kind']] += 1
            areas[region['kind']] += region['area_mm2']
            if len(examples)<120:
                x,y=region.pop('center_cell')
                examples.append(dict(region,z_mm=z,xy_mm=[float(origin[0]+(x+.5)*cell),float(origin[1]+(y+.5)*cell)]))
        previous=mask
    return dict(counts=counts, layer_area_sum_mm2=areas, examples=examples,
        complete=not uncertain,uncertain_layers=uncertain,
        layers=layers,cell_mm=cell,layer_mm=layer,support_removal_enabled=False,
        note='Grid screening only; regions repeat across layers. Not complete island or bridge certification.')
