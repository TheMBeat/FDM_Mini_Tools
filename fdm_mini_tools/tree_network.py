"""Attach descending branches to a certified rooted graph, with load growth.

No model names, contact coordinates, or surface exceptions. Reuse is committed
only after the entire downstream path has been found and its new radii checked.
The existing configured maximum radius is a geometric cap, not a strength test.
"""
from dataclasses import dataclass,field
import math
from mathutils import Vector
from . import tree_collision as tc,tree_routes

STRUCTURAL={'TRUNK','BRANCH','NETWORK_BRANCH'}

@dataclass
class NetworkRoute(tree_routes.RouteResult):
    attachment: dict = field(default_factory=dict)

def _key(p):return tuple(round(float(x),4) for x in p)

def _network_index(edges,roots):
    """One immutable adjacency/root index per search; never reuse after commit."""
    outgoing={}
    for i,e in enumerate(edges):
        if e.kind in STRUCTURAL and e.b.z < e.a.z-.001:
            outgoing.setdefault(_key(e.a),[]).append(i)
    return outgoing,{_key(p) for p in roots}


def _downstream(edges,index,roots,graph=None):
    """Follow the same unique descending path, sharing only its lookup tables."""
    outgoing,sinks=_network_index(edges,roots) if graph is None else graph
    path=[index];seen={index}
    while _key(edges[path[-1]].b) not in sinks:
        next_edges=outgoing.get(_key(edges[path[-1]].b),[])
        if len(next_edges)!=1 or next_edges[0] in seen:return None
        index=next_edges[0];seen.add(index);path.append(index)
    return path

def _parameters(a,b,start,angle,step):
    """Include cone-boundary intersections, not just a coarse segment grid."""
    d=b-a;offset=a-start;k=math.tan(math.radians(angle-.005))**2
    A=d.x*d.x+d.y*d.y-k*d.z*d.z
    B=2*(offset.x*d.x+offset.y*d.y-k*offset.z*d.z)
    C=offset.x*offset.x+offset.y*offset.y-k*offset.z*offset.z
    values={.02,.5,.98}
    count=max(1,math.ceil(d.length/max(.5,step)))
    values.update(i/count for i in range(1,count))
    if d.length_squared:values.add(max(.02,min(.98,-offset.dot(d)/d.length_squared)))
    if abs(A)<1e-12:
        if abs(B)>1e-12:values.add(-C/B)
    elif B*B-4*A*C>=0:
        disc=math.sqrt(B*B-4*A*C)
        for t in ((-B-disc)/(2*A),(-B+disc)/(2*A)):
            values.update((t-.0001,t+.0001))
    return sorted(t for t in values if .001<t<.999)

def _reinforcement(edges,index,t,load,cfg,collider,path):
    from .tree_support import SupportEdge
    branch=max(.1,float(cfg.get('tree_branch_diameter',1))*.5)
    cap=max(branch,float(cfg.get('tree_trunk_diameter',1.8))*.5)
    gap=max(0.,float(cfg.get('tree_model_clearance',.45)))
    grow=lambda r:max(r,min(cap,math.sqrt(r*r+branch*branch*max(1,load))))
    host=edges[index];anchor=host.a.lerp(host.b,t)
    radius=host.radius_a+(host.radius_b-host.radius_a)*t
    replacements={index:[SupportEdge(host.a,anchor,host.radius_a,radius,host.kind),
        SupportEdge(anchor,host.b,grow(radius),grow(host.radius_b),host.kind)]}
    for i in path[1:]:
        e=edges[i];replacements[i]=[SupportEdge(e.a,e.b,grow(e.radius_a),grow(e.radius_b),e.kind)]
    # Includes the split host and every downstream widened segment. Existing
    # cones/necks are never anchors and are never widened by this operation.
    for parts in replacements.values():
        for e in parts:
            if not tc.segment_clear(collider,e.a,e.b,e.radius_a,e.radius_b,gap=gap):return None
    return replacements

def find(node,cfg,collider,edges,roots):
    from . import tree_support as ts
    if not roots:return NetworkRoute(reason='no_certified_network',method='NETWORK')
    angle=max(10.,min(55.,float(cfg.get('tree_max_branch_angle',32))))
    branch=max(.1,float(cfg.get('tree_branch_diameter',1))*.5)
    cap=max(branch,float(cfg.get('tree_trunk_diameter',1.8))*.5)
    radius=ts._branch_radius(node.load,branch,cap)
    gap=max(0.,float(cfg.get('tree_model_clearance',.45)))
    limit=max(0.,float(cfg.get('tree_ground_search_radius',16)))
    candidates=[]
    graph=_network_index(edges,roots)
    for i,e in enumerate(edges):
        if e.kind not in STRUCTURAL or e.b.z>=e.a.z-.001 or e.b.z>=node.pos.z-.04:continue
        path=_downstream(edges,i,roots,graph)
        if not path:continue
        for t in _parameters(e.a,e.b,node.pos,angle,float(cfg.get('tree_ground_search_step',1.5))):
            anchor=e.a.lerp(e.b,t)
            if math.hypot(anchor.x-node.pos.x,anchor.y-node.pos.y)>limit:continue
            if not ts._segment_printable_down(node.pos,anchor,angle):continue
            candidates.append(((anchor-node.pos).length,i,t,anchor,path))
    candidates.sort(key=lambda row:(row[0],row[1],row[2]))
    # Cheap direct connections first. The host radius changes are transactional:
    # rejected candidates cannot alter the already certified support graph.
    for _,i,t,anchor,path in candidates:
        if not tc.segment_clear(collider,node.pos,anchor,radius,radius,gap=gap):continue
        replacements=_reinforcement(edges,i,t,node.load,cfg,collider,path)
        if replacements is None:continue
        return NetworkRoute(points=[node.pos.copy(),anchor],reason='rooted',method='NETWORK_DIRECT',
            attachment=dict(host_edge=i,t=t,root=list(edges[path[-1]].b),
                downstream_edges=path,replacements=replacements,expected_edges=len(edges)))
    return NetworkRoute(reason='no_certified_network_connection',method='NETWORK')

def commit(edges,route):
    plan=route.attachment
    if len(edges)!=plan['expected_edges']:raise RuntimeError('Support graph changed after attachment certification')
    replacements=plan['replacements']
    edges[:]=[part for i,e in enumerate(edges) for part in replacements.get(i,[e])]


def find_tip(node,cfg,collider,edges,roots):
    """Join a certified compact neck directly to an existing carrying branch.

    This is the existing <=2.2-mm tip adapter, targeted at real graph anchors
    instead of the angle/distance sampling grid. No longer near-model branches.
    """
    from . import tree_support as ts
    if not roots:return NetworkRoute(reason='no_certified_network',method='NETWORK_TIP_ADAPTER')
    angle=max(10.,min(55.,float(cfg.get('tree_max_branch_angle',32))))
    neck=max(.06,float(cfg.get('touch_diameter',.3))*.5,float(cfg.get('neck_diameter',.5))*.5)
    branch=max(neck,float(cfg.get('tree_branch_diameter',1))*.5)
    candidates=[]
    graph=_network_index(edges,roots)
    for i,e in enumerate(edges):
        if e.kind not in STRUCTURAL or e.b.z>=e.a.z-.001:continue
        if e.b.z>=node.pos.z-.04:continue
        if sum(max(min(e.a[k],e.b[k])-node.pos[k],0.,node.pos[k]-max(e.a[k],e.b[k]))**2 for k in range(3))>2.2**2:continue
        path=_downstream(edges,i,roots,graph)
        if not path:continue
        for t in _parameters(e.a,e.b,node.pos,angle,.5):
            anchor=e.a.lerp(e.b,t)
            distance=(anchor-node.pos).length
            if distance>2.2 or not ts._segment_printable_down(node.pos,anchor,angle):continue
            candidates.append((distance,i,t,anchor,path))
    for _,i,t,anchor,path in sorted(candidates,key=lambda x:(x[0],x[1],x[2])):
        if not tc.segment_clear(collider,node.pos,anchor,neck,branch,gap=.02):continue
        replacements=_reinforcement(edges,i,t,node.load,cfg,collider,path)
        if replacements is None:continue
        route=NetworkRoute(points=[node.pos.copy(),anchor],reason='rooted',method='NETWORK_TIP_ADAPTER',
            attachment=dict(host_edge=i,t=t,root=list(edges[path[-1]].b),downstream_edges=path,
                replacements=replacements,expected_edges=len(edges)))
        route.connector_edges=[ts.SupportEdge(node.pos.copy(),anchor,neck,branch,'TIP_ADAPTER')]
        return route
    return NetworkRoute(reason='no_certified_tip_attachment',method='NETWORK_TIP_ADAPTER')

def provenance(route):
    if not getattr(route,'attachment',None):return None
    return {key:value for key,value in route.attachment.items() if key!='replacements'}
