"""Experimental geometric slenderness rule; not a mechanical/print certificate.

Free length follows the entire rooted path, including bends and split edges.
Only certified diagonal frames between distinct roots introduce lateral anchors.
Compact contact assemblies remain unchanged. Every added/widened full radius is
certified against the MINI before an alternative is committed.
"""
import math
from mathutils import Vector
from . import tree_collision as tc

STRUCTURAL={'TRUNK','BRANCH','NETWORK_BRANCH','STABILITY_POST'}
def key(p):return tuple(round(float(v),4) for v in p)
def volume(e):return math.pi*(e.b-e.a).length*(e.radius_a**2+e.radius_a*e.radius_b+e.radius_b**2)/3
def paths(edges,roots):
    outgoing={};incoming=set();sinks={key(p) for p in roots}
    for i,e in enumerate(edges):
        if e.kind in STRUCTURAL:
            outgoing.setdefault(key(e.a),[]).append(i);incoming.add(key(e.b))
    result=[]
    for i,e in enumerate(edges):
        if e.kind not in STRUCTURAL or key(e.a) in incoming:continue
        indices=[];seen=set();index=i;reached=False
        while index not in seen:
            seen.add(index);indices.append(index);end=edges[index].b
            if key(end) in sinks:
                result.append(dict(indices=indices,top=list(e.a),root=list(end)));reached=True;break
            nxt=outgoing.get(key(end),[])
            if len(nxt)!=1:break
            index=nxt[0]
        if not reached:raise RuntimeError('Stem stability graph has no unique certified root')
    return result

def _sample(edges,path,q):
    q=max(0.,q)
    for index in path['indices']:
        e=edges[index];length=(e.b-e.a).length
        if q<=length+1e-6:
            t=min(1.,q/max(length,1e-9));return e.a.lerp(e.b,t),e.radius_a+(e.radius_b-e.radius_a)*t
        q-=length
    e=edges[path['indices'][-1]];return e.b.copy(),e.radius_b

def _at_z(edges,path,z):
    for index in path['indices']:
        e=edges[index]
        if e.b.z-.0001<=z<=e.a.z+.0001:
            return e.a.lerp(e.b,max(0.,min(1.,(e.a.z-z)/max(1e-9,e.a.z-e.b.z))))
    return None

def _cuts(edges,path,anchors):
    total=sum((edges[i].b-edges[i].a).length for i in path['indices']);cuts={0.,total};offset=0.
    for i in path['indices']:
        e=edges[i];d=e.b-e.a
        for point in anchors:
            p=Vector(point);t=(p-e.a).dot(d)/max(d.length_squared,1e-20)
            if 0<=t<=1 and (p-e.a.lerp(e.b,t)).length<.0002:cuts.add(offset+t*d.length)
        offset+=d.length
    return sorted(cuts)

def _slenderness(edges,path,lo,hi):
    # Cantilever compliance proxy: integral(moment_arm^2 / radius^4).
    # Integrate separately on every geometric segment; subdividing one straight
    # stem or inserting an unbraced junction cannot reset or shorten its length.
    compliance=0.;offset=0.
    for i in path['indices']:
        e=edges[i];length=(e.b-e.a).length;a=max(lo,offset);b=min(hi,offset+length)
        if b>a:
            step=(b-a)/16
            for n in range(17):
                q=a+n*step;t=(q-offset)/max(length,1e-20)
                r=e.radius_a+(e.radius_b-e.radius_a)*t
                compliance+=(1 if n in (0,16) else 4 if n%2 else 2)*(q-lo)**2/max(r,1e-6)**4*step/3
        offset+=length
    length=hi-lo;radius=(length**3/(3*max(compliance,1e-30)))**.25
    return length/(2*radius),2*radius

def inspect(edges,roots,cfg,anchors=()):
    limit=float(cfg.get('tree_stem_slenderness',18.));minimum=float(cfg.get('tree_stem_min_length',12.))
    risky=[];all_paths=paths(edges,roots)
    for path in all_paths:
        cuts=_cuts(edges,path,anchors)
        for lo,hi in zip(cuts,cuts[1:]):
            if hi-lo<minimum:continue
            slender,diameter=_slenderness(edges,path,lo,hi)
            if slender>limit+.001:
                risky.append(dict(path=path,lo=lo,hi=hi,length_mm=hi-lo,equivalent_diameter_mm=diameter,
                    slenderness=slender,top=list(_sample(edges,path,lo)[0]),bottom=list(_sample(edges,path,hi)[0])))
    risky.sort(key=lambda r:(-r['slenderness'],r['path']['top']))
    return risky,all_paths

def _same_path(a,b):return key(a['top'])==key(b['top']) and key(a['root'])==key(b['root'])
def _resolved(target,edges,roots,cfg,anchors):
    risky,all_paths=inspect(edges,roots,cfg,anchors)
    return any(_same_path(target['path'],p) for p in all_paths) and not any(_same_path(target['path'],r['path']) for r in risky)

def _braced(target,edges,roots,cfg,collider,anchors):
    from .tree_support import SupportEdge,_segment_printable_down
    all_paths=paths(edges,roots);source=target['path'];angle=float(cfg.get('tree_max_branch_angle',32.))
    radius=max(.2,min(float(cfg.get('tree_branch_diameter',1.))*.35,float(cfg.get('truss_diameter',1.1))*.5))
    gap=max(0.,float(cfg.get('tree_model_clearance',.45)));tan=math.tan(math.radians(angle-.01))
    neighbours=[p for p in all_paths if not _same_path(p,source) and (Vector(p['root'])-Vector(source['root'])).length>=2.]
    neighbours.sort(key=lambda p:(Vector(p['top'])-Vector(source['top'])).length)
    # Dense contact completion can put many blocked leaves ahead of a usable
    # host. Keep nearest-first ordering, but do not discard the ninth host.
    for other in neighbours:
        high=min(source['top'][2],other['top'][2])-.3
        floor=max(source['root'][2],other['root'][2])+.3
        diam=min(min(edges[i].radius_a for i in source['indices']),min(edges[i].radius_a for i in other['indices']))*2
        spacing=max(2.,float(cfg.get('tree_stem_slenderness',18.))*diam*.60)
        extra=[];marks=[]
        while high>floor+.5 and len(extra)<32:
            p=_at_z(edges,source,high);s=_at_z(edges,other,high)
            low=high-.5
            for _ in range(8):
                q=_at_z(edges,other,low);r=_at_z(edges,source,low)
                if any(v is None for v in (p,s,q,r)):break
                drop=max(math.hypot(p.x-q.x,p.y-q.y),math.hypot(s.x-r.x,s.y-r.y))/max(tan,.01)*1.01+.05
                if high-drop>=low-.001:break
                low=high-drop
            q=_at_z(edges,other,low);r=_at_z(edges,source,low)
            if low>floor and all(v is not None for v in (p,s,q,r)):
                diagonals=[SupportEdge(p,q,radius,radius,'STABILITY_BRACE'),SupportEdge(s,r,radius,radius,'STABILITY_BRACE')]
                if all(_segment_printable_down(e.a,e.b,angle) and tc.segment_clear(collider,e.a,e.b,radius,radius,gap=gap) for e in diagonals):
                    extra.extend(diagonals);marks.extend(list(v) for v in (p,q,s,r))
            high-=spacing
        if extra and _resolved(target,edges+extra,roots,cfg,list(anchors)+marks):
            return dict(edges=edges+extra,roots=list(roots),anchors=list(anchors)+marks,
                raft=[],cost=sum(volume(e) for e in extra),kind='diagonal_frame',added=len(extra))
    return None

def _thickened(target,edges,roots,cfg,collider,anchors):
    from .tree_support import SupportEdge
    path=target['path'];maximum=float(cfg.get('tree_stem_max_diameter',3.2))*.5
    limit=float(cfg.get('tree_stem_slenderness',18.));gap=max(0.,float(cfg.get('tree_model_clearance',.45)))
    length=sum((edges[i].b-edges[i].a).length for i in path['indices'])
    start=max(target['length_mm']/(2*limit)*1.03,.25)
    attempts=sorted({min(maximum,start*f) for f in (1,1.15,1.4,1.8,2.4)}|{maximum})
    for radius in attempts:
        replacement={};offset=0.;valid=True
        for index in path['indices']:
            e=edges[index];distance=(e.b-e.a).length
            fractions={0.,1.}
            for q in (.3,.6,.9,1.2,1.5):
                if offset<q<offset+distance:fractions.add((q-offset)/distance)
            fractions=sorted(fractions);parts=[]
            for a,b in zip(fractions,fractions[1:]):
                ra=max(e.radius_a+(e.radius_b-e.radius_a)*a,radius*min(1.,(offset+distance*a)/1.5))
                rb=max(e.radius_a+(e.radius_b-e.radius_a)*b,radius*min(1.,(offset+distance*b)/1.5))
                part=SupportEdge(e.a.lerp(e.b,a),e.a.lerp(e.b,b),ra,rb,e.kind)
                if not tc.segment_clear(collider,part.a,part.b,ra,rb,gap=gap):valid=False;break
                parts.append(part)
            if not valid:break
            replacement[index]=parts;offset+=distance
        if not valid:continue
        # The stem/flare connection must grow together; the raft remains a
        # separately certified unified solid built from all ground roots.
        for i,e in enumerate(edges):
            if e.kind=='BASE_FLARE' and key(e.b)==key(path['root']):
                rb=max(e.radius_b,radius);ra=max(e.radius_a,rb)
                part=SupportEdge(e.a,e.b,ra,rb,e.kind)
                if not tc.segment_clear(collider,e.a,e.b,ra,rb,gap=gap):valid=False;break
                replacement[i]=[part]
        if not valid:continue
        candidate=[part for i,e in enumerate(edges) for part in replacement.get(i,[e])]
        if _resolved(target,candidate,roots,cfg,anchors):
            return dict(edges=candidate,roots=list(roots),anchors=list(anchors),raft=[],
                cost=sum(volume(e) for e in candidate)-sum(volume(e) for e in edges),kind='tapered_thickening',added=0)
    return None

def _parallel(target,edges,roots,cfg,collider,anchors):
    from .tree_support import SupportEdge
    source=target['path'];seed,_=_sample(edges,source,min(1.5,target['length_mm']*.1))
    r=max(.1,float(cfg.get('tree_branch_diameter',1.))*.5);gap=max(0.,float(cfg.get('tree_model_clearance',.45)))
    separation=max(2.2,4.4*r)
    for az in range(0,360,45):
        offset=Vector((math.cos(math.radians(az))*separation,math.sin(math.radians(az))*separation,0))
        points=[seed+offset]
        points.extend(edges[i].b+offset for i in source['indices'] if edges[i].b.z<seed.z-.001)
        posts=[SupportEdge(a,b,r,r,'STABILITY_POST') for a,b in zip(points,points[1:])]
        if not posts or not all(tc.segment_clear(collider,e.a,e.b,r,r,gap=gap) for e in posts):continue
        root=points[-1];extra=list(posts);newraft=[]
        if cfg.get('use_raft',True):
            bottom=Vector((root.x,root.y,max(0.,float(cfg.get('raft_floor_thickness',.6)))))
            base=max(r,float(cfg.get('base_diameter',4.6))*.5)
            if root.z-bottom.z>.05:
                flare=SupportEdge(bottom,root,base,r,'BASE_FLARE')
                if not tc.segment_clear(collider,bottom,root,base,r,gap=gap):continue
                extra.append(flare)
            newraft.append(bottom)
        candidate=edges+extra;newroots=list(roots)+[root]
        frame=_braced(target,candidate,newroots,cfg,collider,anchors)
        if frame is None:continue
        # Do not trade the original risk for an unbraced newly added post.
        post_top=key(posts[0].a)
        if any(key(row['path']['top'])==post_top for row in inspect(frame['edges'],newroots,cfg,frame['anchors'])[0]):continue
        frame.update(kind='parallel_post_frame',raft=newraft,
            cost=frame['cost']+sum(volume(e) for e in extra),added=frame['added']+len(extra))
        return frame
    return None

def apply(edges,roots,raft_roots,cfg,collider):
    limit=float(cfg.get('tree_stem_slenderness',18.));maximum=float(cfg.get('tree_stem_max_diameter',3.2))
    if not math.isfinite(limit) or not 5<=limit<=50 or not math.isfinite(maximum) or not .5<=maximum<=8:
        raise ValueError('Invalid experimental stem stability limits')
    anchors=[];before,_=inspect(edges,roots,cfg);operations=[];failed=set()
    if cfg.get('tree_stabilize_stems',False):
        for _ in range(96):
            risky,_=inspect(edges,roots,cfg,anchors)
            target=next((row for row in risky if (key(row['path']['top']),key(row['top']),key(row['bottom'])) not in failed),None)
            if target is None:break
            generators=(_thickened,) if cfg.get('_stability_style')=='THICKEN' else (_braced,_thickened)
            options=[f(target,edges,roots,cfg,collider,anchors) for f in generators]
            options=[o for o in options if o is not None]
            if not options:
                option=_parallel(target,edges,roots,cfg,collider,anchors)
                if option:options=[option]
            if not options:
                failed.add((key(target['path']['top']),key(target['top']),key(target['bottom'])));continue
            best=min(options,key=lambda o:(o['cost'],o['kind']))
            edges[:]=best['edges'];roots[:]=best['roots'];anchors=best['anchors'];raft_roots.extend(best['raft'])
            operations.append(dict(kind=best['kind'],top=target['top'],root=target['path']['root'],
                added_segments=best['added'],estimated_extra_mm3=best['cost']))
    after,all_paths=inspect(edges,roots,cfg,anchors)
    def public(row):return {k:v for k,v in row.items() if k not in ('path','lo','hi')}
    return dict(enabled=bool(cfg.get('tree_stabilize_stems',False)),style=cfg.get('_stability_style','AUTO'),policy='Experimental free-span compliance/slenderness proxy; no mechanical print validation',
        max_slenderness=limit,min_free_length_mm=float(cfg.get('tree_stem_min_length',12.)),max_diameter_mm=maximum,
        paths=len(all_paths),before=len(before),unresolved=len(after),operations=operations,
        anchors=anchors,risky_spans=[public(row) for row in after],print_validated=False)

def fill_tiny_enclosed_voids(model,support,cfg,collider):
    """Add material to certified internal air pockets created by dense frames.

    Never discard positive solid fragments or relax topology tolerances. Only
    closed, reversed inner shells completely enclosed by the one grounded outer
    shell can be filled. The added material is volume-bounded and its entire
    boundary must preserve the MINI gap; a MINI enclosed in the pocket rejects.
    """
    import bmesh
    from mathutils.bvhtree import BVHTree
    from . import tree_mesh as tm
    report=tm.topology(support,require_single=True)
    result=dict(filled=0,added_material_mm3=0.,pockets=[])
    if report['components']<=1:return result
    if any(report[k] for k in ('nonmanifold_edges','inconsistent_edges','degenerate_faces','nonfinite_vertices')):return result
    verts,tris=tm.world_mesh(support);adj=[set() for _ in verts]
    for a,b,c in tris:
        for i,j in ((a,b),(b,c),(c,a)):adj[i].add(j);adj[j].add(i)
    unseen=set(range(len(verts)));groups=[]
    while unseen:
        first=min(unseen);unseen.remove(first);ids={first};todo=[first]
        while todo:
            i=todo.pop()
            for j in adj[i]:
                if j in unseen:unseen.remove(j);ids.add(j);todo.append(j)
        faces=[t for t in tris if t[0] in ids];origin=verts[first]
        signed=math.fsum((verts[a]-origin).dot((verts[b]-origin).cross(verts[c]-origin))/6 for a,b,c in faces)
        groups.append(dict(ids=ids,tris=faces,volume=signed))
    outer=[g for g in groups if g['volume']>1e-12];voids=[g for g in groups if g['volume']<-1e-12]
    if len(outer)!=1 or len(outer)+len(voids)!=len(groups):return result
    if min(verts[i].z for i in outer[0]['ids'])!=0.:return result
    if any(-g['volume']>.01 for g in voids) or sum(-g['volume'] for g in voids)>.05:return result
    shell=BVHTree.FromPolygons(verts,outer[0]['tris'],all_triangles=True)
    directions=(Vector((1,.371,.529)).normalized(),Vector((-.217,1,.413)).normalized())
    mini_verts,_=tm.world_mesh(model);gap=max(0.,float(cfg.get('tree_model_clearance',.45)))
    for group in voids:
        void=BVHTree.FromPolygons(verts,group['tris'],all_triangles=True)
        if shell.overlap(void):return result
        for i in group['ids']:
            counts=[tc.ray_winding(shell,verts[i],d) for d in directions]
            if counts!=[1,1]:return result
        clear,_,_=tm._surface_clear(verts,group['tris'],collider,gap)
        if not clear:return result
        low=Vector(tuple(min(verts[i][j] for i in group['ids']) for j in range(3)))
        high=Vector(tuple(max(verts[i][j] for i in group['ids']) for j in range(3)))
        for point in mini_verts:
            if all(low[j]<=point[j]<=high[j] for j in range(3)):
                counts=[tc.ray_winding(void,point,d) for d in directions]
                if counts!=[0,0]:return result
    # Removing the enclosed negatively oriented BOUNDARY fills its air volume.
    # No positive outer boundary or contact vertex is removed or displaced.
    doomed=set().union(*(g['ids'] for g in voids));bm=bmesh.new()
    try:
        bm.from_mesh(support.data);bm.verts.ensure_lookup_table()
        bmesh.ops.delete(bm,geom=[bm.verts[i] for i in doomed],context='VERTS')
        bm.to_mesh(support.data)
    finally:bm.free()
    support.data.update()
    return dict(filled=len(voids),added_material_mm3=sum(-g['volume'] for g in voids),
        pockets=[dict(volume_mm3=-g['volume'],vertices=len(g['ids'])) for g in voids])
