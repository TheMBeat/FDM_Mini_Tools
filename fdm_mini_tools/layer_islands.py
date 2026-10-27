"""Closed layer contours and conservative island/overhang diagnostics.

No raster dilation, guessed bridge span, or automatic support removal. A layer
connection is evidence about the section, not a mechanical cantilever proof.
"""
import math
import numpy as np

EPS=1e-7

def ring_inside(ring,point):
    p=np.asarray(point,float);a=np.asarray(ring,float);b=np.roll(a,-1,axis=0)
    d=b-a;length=np.sum(d*d,axis=1)
    t=np.clip(np.sum((p-a)*d,axis=1)/np.maximum(length,1e-30),0,1)
    if np.min(np.linalg.norm(a+t[:,None]*d-p,axis=1))<=EPS:return 0
    cross=(a[:,1]>p[1])!=(b[:,1]>p[1])
    left=a[cross];right=b[cross]
    hits=left[:,0]+(p[1]-left[:,1])*(right[:,0]-left[:,0])/(right[:,1]-left[:,1])
    return 1 if np.count_nonzero(hits>p[0])%2 else -1

def inside(poly,point):
    outer=ring_inside(poly['outer'],point)
    if outer<=0:return outer
    for hole in poly['holes']:
        value=ring_inside(hole,point)
        if value==0:return 0
        if value==1:return -1
    return 1


def inside_many(poly,points):
    """Same boundary/hole rules as inside(), with bounded point/edge batches."""
    points=np.asarray(points,float).reshape((-1,2))
    def classify(ring,queries):
        a=np.asarray(ring,float);b=np.roll(a,-1,axis=0);d=b-a
        length=np.sum(d*d,axis=1);rows=[]
        size=max(1,65536//max(1,len(a)))
        for start in range(0,len(queries),size):
            p=queries[start:start+size,None,:]
            t=np.clip(np.sum((p-a)*d,axis=2)/np.maximum(length,1e-30),0,1)
            boundary=np.min(np.linalg.norm(a+t[:,:,None]*d-p,axis=2),axis=1)<=EPS
            cross=(a[None,:,1]>p[:,:,1])!=(b[None,:,1]>p[:,:,1])
            # Division occurs only on crossing edges, just as in ring_inside.
            r,c=np.nonzero(cross)
            hits=a[c,0]+(p[r,0,1]-a[c,1])*(b[c,0]-a[c,0])/(b[c,1]-a[c,1])
            counts=np.bincount(r,weights=(hits>p[r,0,0]),minlength=len(p))
            rows.extend(np.where(boundary,0,np.where(counts%2,1,-1)).tolist())
        return np.asarray(rows,dtype=np.int8)
    result=classify(poly['outer'],points)
    for hole in poly['holes']:
        active=np.flatnonzero(result>0)
        if not len(active):break
        values=classify(hole,points[active])
        result[active[values==0]]=0;result[active[values==1]]=-1
    return result

def distance(poly,point):
    p=np.asarray(point,float);best=float('inf')
    for ring in [poly['outer']]+poly['holes']:
        a=np.asarray(ring,float);b=np.roll(a,-1,axis=0);d=b-a
        t=np.clip(np.sum((p-a)*d,axis=1)/np.maximum(np.sum(d*d,axis=1),1e-30),0,1)
        best=min(best,float(np.min(np.linalg.norm(a+t[:,None]*d-p,axis=1))))
    return best

def interior(poly):
    ring=np.asarray(poly['outer']);rings=[np.asarray(r) for r in [poly['outer']]+poly['holes']]
    a=np.concatenate(rings);b=np.concatenate([np.roll(r,-1,axis=0) for r in rings])
    levels=[float((ring[:,1].min()+ring[:,1].max())*.5)]
    levels.extend(float((p[1]+q[1])*.5) for p,q in zip(a,b) if abs(p[1]-q[1])>EPS)
    for y in levels:
        take=(a[:,1]>y)!=(b[:,1]>y);p=a[take];q=b[take]
        hits=np.sort(p[:,0]+(y-p[:,1])*(q[:,0]-p[:,0])/(q[:,1]-p[:,1]))
        for lo,hi in zip(hits[::2],hits[1::2]):
            point=[float((lo+hi)*.5),y]
            if hi-lo>2*EPS and inside(poly,point)==1:return point
    raise ValueError('No unambiguous section interior')

def _cross(a,b):return a[...,0]*b[...,1]-a[...,1]*b[...,0]

def overlap(first,second):
    a=np.asarray(first['outer']);b=np.asarray(second['outer'])
    if np.any(a.max(axis=0)<=b.min(axis=0)+EPS) or np.any(b.max(axis=0)<=a.min(axis=0)+EPS):return False
    # A strictly interior witness already proves positive filled overlap.
    # Adjacent layers normally share material: avoid an all-edge Cartesian
    # product merely to reach these same existing containment predicates.
    for poly,other in ((first,second),(second,first)):
        if inside(other,poly['outer'][0])==1:return True
        try: witness=interior(poly)
        except ValueError: continue  # Preserve the original crossing fallback.
        if inside(other,witness)==1:return True
    # A proper boundary crossing gives positive filled overlap, except holes;
    # hole boundaries also delimit material, so test all contour pairs.
    for ar in [first['outer']]+first['holes']:
        ar=np.asarray(ar);aq=np.roll(ar,-1,axis=0)
        for br in [second['outer']]+second['holes']:
            br=np.asarray(br);bq=np.roll(br,-1,axis=0)
            blo=np.minimum(br,bq);bhi=np.maximum(br,bq)
            for k in range(0,len(ar),64):
                p=ar[k:k+64,None,:];q=aq[k:k+64,None,:]
                lo=np.minimum(p,q).min(axis=(0,1))-EPS
                hi=np.maximum(p,q).max(axis=(0,1))+EPS
                nearby=np.all(bhi>=lo,axis=1)&np.all(blo<=hi,axis=1)
                if not np.any(nearby):continue
                r=br[nearby][None,:,:];s=bq[nearby][None,:,:]
                c1=_cross(q-p,r-p);c2=_cross(q-p,s-p)
                c3=_cross(s-r,p-r);c4=_cross(s-r,q-r)
                if np.any((c1*c2 < -EPS**2)&(c3*c4 < -EPS**2)):return True
    for poly,other in [(first,second),(second,first)]:
        # The first vertex often proves overlap immediately. Batch only the
        # remaining ambiguous/absent projections, preserving boundary rules.
        if inside(other,poly['outer'][0])==1:return True
        if np.any(inside_many(other,poly['outer'][1:])==1):return True
        if inside(other,interior(poly))==1:return True
    return False

def prepare_sections(shells):
    """Freeze exact coordinates and per-face height bounds once per diagnosis."""
    prepared=[]
    for vertices,faces in shells:
        xyz=np.asarray(vertices,float);tris=np.asarray(faces,int).reshape((-1,3))
        heights=xyz[tris,2]
        prepared.append((xyz,tris,heights.min(axis=1),heights.max(axis=1)))
    return prepared


def section(shells,z,prepared=None):
    polygons=[]
    if prepared is None:prepared=prepare_sections(shells)
    for shell_id,(xyz,faces,zmin,zmax) in enumerate(prepared):
        ids=np.flatnonzero((zmin<=z)&(zmax>z));tri=xyz[faces[ids]]
        # Preserve the old face/edge order while evaluating all independent
        # intersections, normals and orientations in float64 NumPy batches.
        hits=np.empty((len(tri),2,2),dtype=float);counts=np.zeros(len(tri),dtype=np.intp)
        for a,b in [(0,1),(1,2),(2,0)]:
            p=tri[:,a];q=tri[:,b];cross=(p[:,2]<=z)!=(q[:,2]<=z)
            take=np.flatnonzero(cross)
            if np.any(counts[take]>=2):raise ValueError('Ambiguous triangle/plane intersection')
            hits[take,counts[take]]= (p[cross]+((z-p[cross,2])/(q[cross,2]-p[cross,2]))[:,None]*(q[cross]-p[cross]))[:,:2]
            counts[take]+=1
        if np.any(counts!=2):raise ValueError('Ambiguous triangle/plane intersection')
        delta=hits[:,1]-hits[:,0]
        valid=~(np.linalg.norm(delta,axis=1)<1e-8)
        normal=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0])
        flip=np.sum(delta*np.stack((-normal[:,1],normal[:,0]),axis=1),axis=1)<0
        hits[flip]=hits[flip,::-1]
        keys=np.round(hits,6)
        outgoing={};incoming={};coordinates={}
        for index in np.flatnonzero(valid):
            points=hits[index]
            a,b=points
            ka=tuple(keys[index,0]);kb=tuple(keys[index,1])
            if ka==kb:raise ValueError('Section detail below contour joining precision')
            if ka in outgoing or kb in incoming:raise ValueError('Non-simple or ambiguous section junction')
            outgoing[ka]=(kb,int(ids[index]));incoming[kb]=ka
            coordinates[ka]=a.tolist();coordinates[kb]=b.tolist()
        if set(outgoing)!=set(incoming):raise ValueError('Open section contour')
        unseen=set(outgoing);loops=[]
        while unseen:
            start=min(unseen);key=start;points=[];source=[]
            while key in unseen:
                unseen.remove(key);points.append(coordinates[key]);key,face=outgoing[key];source.append(face)
            if key!=start:raise ValueError('Branched contour walk')
            a=np.asarray(points);b=np.roll(a,-1,axis=0);area=float(np.sum(_cross(a,b))*.5)
            if abs(area)<1e-12:raise ValueError('Zero-area section')
            loops.append(dict(points=points,area=area,faces=source))
        positive=[r for r in loops if r['area']>0];negative=[r for r in loops if r['area']<0]
        parts=[dict(outer=r['points'],holes=[],shell=shell_id,source_faces=r['faces']) for r in positive]
        for hole in negative:
            containers=[i for i,p in enumerate(parts) if ring_inside(p['outer'],hole['points'][0])==1]
            if not containers:raise ValueError('Unowned section hole')
            owner=min(containers,key=lambda i:positive[i]['area']);parts[owner]['holes'].append(hole['points'])
            parts[owner]['source_faces']+=hole['faces']
        polygons.extend(parts)
    return polygons

def components(polygons):
    parent=list(range(len(polygons)))
    def root(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    for i in range(len(polygons)):
        for j in range(i):
            if root(i)!=root(j) and overlap(polygons[i],polygons[j]):parent[root(i)]=root(j)
    groups={}
    for i in range(len(polygons)):groups.setdefault(root(i),[]).append(i)
    return list(groups.values())


def _connected_parts(polygons,seeds,bounds,cache):
    """Find only components incident to this contact, with exact overlap tests.

    Distant polygon pairs cannot affect this component. Reachability still
    expands transitively through every potentially overlapping neighbor.
    """
    reached=set(seeds);pending=list(seeds)
    while pending:
        i=pending.pop();lo,hi=bounds[i]
        for j,(other_lo,other_hi) in enumerate(bounds):
            if j in reached:continue
            if np.any(hi<=other_lo+EPS) or np.any(other_hi<=lo+EPS):continue
            pair=(max(i,j),min(i,j))
            if pair not in cache:cache[pair]=overlap(polygons[pair[0]],polygons[pair[1]])
            if cache[pair]:reached.add(j);pending.append(j)
    return sorted(reached)


def layer_center(index,first,layer):return first*.5 if index==0 else first+(index-.5)*layer

def diagnose(shells,records,layer=.08,first=.2,line_width=.22,support_shells=None,workers=None,
             _prepared=None,_prepared_support=None,classification_only=False):
    if min(layer,first,line_width)<=0:raise ValueError('Invalid layer/line profile')
    records=list(records)
    cache={};bounds_cache={};connections={};overlap_cache={};results=[]
    prepared=prepare_sections(shells) if _prepared is None else _prepared
    prepared_support=(_prepared_support if _prepared_support is not None else
        prepare_sections(support_shells) if support_shells is not None else None)
    # Avoid process and array-transfer overhead for small models/jobs.
    count=workers if workers is not None else (2 if len(records)>=8 and sum(len(p[1]) for p in prepared)>=250000 else 0)
    parallel_points=None
    if count>=2:
        from .layer_parallel import diagnose as parallel_diagnose
        parallel_points=parallel_diagnose(prepared,records,dict(layer=layer,first=first,line_width=line_width,classification_only=classification_only),count,prepared_support)
    def get(z):
        key=round(z,9)
        if key not in cache:
            cache[key]=section(shells,z,prepared)
        return cache[key]
    if parallel_points is not None:records=[];results=parallel_points
    for record in records:
        point=record['point'];birth=float(point[2])
        index=0 if birth<first*.5-1e-6 else max(1,math.floor((birth-first)/layer+.5+1e-7)+1)
        z=layer_center(index,first,layer);previous_z=layer_center(index-1,first,layer) if index else None
        row=dict(id=record['id'],point=point,layer_index=index,z_mm=z,previous_z_mm=previous_z,
            layer_mm=layer,line_width_mm=line_width,support_removal_allowed=False)
        try:
            current=get(z);previous=get(previous_z) if index else []
            key=round(z,9)
            if key not in bounds_cache:
                bounds_cache[key]=[(np.asarray(p['outer']).min(axis=0),np.asarray(p['outer']).max(axis=0)) for p in current]
                connections[key]={}
            bounds=bounds_cache[key];xy=np.asarray(point[:2])
            seeds=[i for i,(lo,hi) in enumerate(bounds) if np.all(xy>=lo-EPS) and np.all(xy<=hi+EPS) and inside(current[i],point[:2])==1]
            correspondence='vertical_birth_projection'
            if not seeds:
                incident={}
                for shell_id,(xyz,tris,_zmin,_zmax) in enumerate(prepared):
                    matches=np.linalg.norm(xyz-np.asarray(point),axis=1)<1e-5
                    incident[shell_id]=set(np.flatnonzero(matches[tris].any(axis=1)))
                seeds=[i for i,p in enumerate(current) if incident[p['shell']].intersection(p['source_faces'])]
                correspondence='incident_surface_faces'
            if not seeds:
                # Keep absent/thin/cross-section-correspondence cases explicit.
                row.update(kind='NO_LOCAL_SECTION',certain=False)
            else:
                indices=_connected_parts(current,seeds,bounds,connections[key])
                def anchored(i,j):
                    pair=(key,i,j)
                    if pair not in overlap_cache:overlap_cache[pair]=overlap(current[i],previous[j])
                    return overlap_cache[pair]
                if classification_only:
                    # Prioritization needs existence, not every anchor or a
                    # detailed footprint/contour report. A single positive
                    # overlap proves anchored; an island still checks ALL.
                    has_anchor=any(anchored(i,j) for j in range(len(previous)) for i in indices)
                    row.update(kind='ANCHORED_OVERHANG' if has_anchor else 'NEW_ISLAND',certain=True)
                    results.append(row)
                    continue
                anchor_parts=[j for j in range(len(previous)) if any(anchored(i,j) for i in indices)]
                local=[j for j,p in enumerate(previous) if inside(p,point[:2])==1 and distance(p,point[:2])>=line_width*.5+EPS]
                row.update(kind='ANCHORED_OVERHANG' if anchor_parts else 'NEW_ISLAND',certain=True,
                    correspondence=correspondence,
                    current_parts=indices,previous_anchor_parts=anchor_parts,local_previous_model_footprint=bool(local),
                    local_previous_material_rooting_verified=False)
                if prepared_support is not None and previous_z is not None:
                    support=section(support_shells,previous_z,prepared_support)
                    row['local_previous_rooted_support_footprint']=any(inside(p,point[:2])==1 and distance(p,point[:2])>=line_width*.5+EPS for p in support)
            if not classification_only:row.update(current_contours=current,previous_contours=previous)
        except (ValueError,FloatingPointError) as error:row.update(kind='UNCERTAIN_SECTION',certain=False,reason=str(error))
        results.append(row)
    return dict(points=results,layer_mm=layer,first_layer_mm=first,line_width_mm=line_width,
        counts={kind:sum(r['kind']==kind for r in results) for kind in ['NEW_ISLAND','ANCHORED_OVERHANG','NO_LOCAL_SECTION','UNCERTAIN_SECTION']},
        policy='Section overlap classifies island vs anchored overhang. It does not prove cantilever/bridge printability or remove mandatory contacts.')
