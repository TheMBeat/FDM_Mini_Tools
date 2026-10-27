"""Experimental descending search to certified graph anchors.

The heuristic points at actual reachable-height host anchors, not just the bed.
Every prefix, connector and widened downstream host is independently certified.
"""
import heapq,math
from mathutils import Vector
from . import tree_network as network,tree_collision as tc

def find(node,cfg,collider,edges,roots,budget=1800):
    result=_search(node,cfg,collider,edges,roots,budget,False)
    remaining=max(0,int(budget)-result.expanded)
    if not result.points and remaining and result.reason=='no_guided_descending_route':
        fine=_search(node,cfg,collider,edges,roots,remaining,True)
        fine.expanded+=result.expanded
        return fine
    return result


def _search(node,cfg,collider,edges,roots,budget,fine):
    from . import tree_support as ts
    method='NETWORK_GUIDED_EXPERIMENTAL'
    direct=network.find(node,cfg,collider,edges,roots)
    if direct.points:return direct
    if not roots:return network.NetworkRoute(reason='no_certified_network',method=method)
    start=node.pos.copy();angle=max(10.,min(55.,float(cfg.get('tree_max_branch_angle',32))))
    branch=max(.1,float(cfg.get('tree_branch_diameter',1))*.5)
    radius=ts._branch_radius(node.load,branch,max(branch,float(cfg.get('tree_trunk_diameter',1.8))*.5))
    gap=max(0.,float(cfg.get('tree_model_clearance',.45)));limit=max(0.,float(cfg.get('tree_ground_search_radius',16)))
    tan=math.tan(math.radians(angle-.03));anchors=[]
    graph=network._network_index(edges,roots)
    for index,edge in enumerate(edges):
        if edge.kind not in network.STRUCTURAL or edge.b.z>=start.z-.1:continue
        path=network._downstream(edges,index,roots,graph)
        if not path:continue
        for t in network._parameters(edge.a,edge.b,start,angle,.65):
            point=edge.a.lerp(edge.b,t)
            if (point-start).xy.length>limit or not ts._segment_printable_down(start,point,angle):continue
            anchors.append(((point-start).length,index,t,point,path))
    anchors.sort(key=lambda a:(a[0],a[1],a[2]));anchors=anchors[:192]
    if not anchors:return network.NetworkRoute(reason='no_anchor_in_descending_envelope',method=method)
    def heuristic(point):return min((a[3]-point).length for a in anchors if a[3].z<point.z-.04) if any(a[3].z<point.z-.04 for a in anchors) else 1e8
    nodes=[(start,-1,0.)];queue=[(heuristic(start),0)];seen={};expanded=0;plans={}
    while queue and expanded<max(0,int(budget)):
        _,idx=heapq.heappop(queue);point,parent,cost=nodes[idx];expanded+=1
        candidates=[a for a in anchors if a[3].z<point.z-.04 and ts._segment_printable_down(point,a[3],angle)]
        candidates.sort(key=lambda a:((a[3]-point).length,a[1],a[2]))
        for _,host,t,anchor,downstream in candidates[:24]:
            if not tc.segment_clear(collider,point,anchor,radius,radius,gap=gap):continue
            key=(host,t)
            if key not in plans:plans[key]=network._reinforcement(edges,host,t,node.load,cfg,collider,downstream)
            if plans[key] is None:continue
            prefix=[point];previous=parent
            while previous>=0:
                p,previous,_=nodes[previous];prefix.append(p)
            prefix.reverse();prefix.append(anchor)
            return network.NetworkRoute(points=prefix,reason='rooted',expanded=expanded,method=method,
                attachment=dict(host_edge=host,t=t,root=list(edges[downstream[-1]].b),downstream_edges=downstream,
                    replacements=plans[key],expected_edges=len(edges)))
        # Fine steps near the contact; regular steps below the first millimetre.
        drop=.10 if fine and start.z-point.z<.35 else .25 if start.z-point.z<1. else .55
        floor=min(a[3].z for a in anchors);drop=min(drop,point.z-floor-.05)
        if drop<.08:continue
        closest=min(anchors,key=lambda a:(a[3]-point).length)[3]-point
        az=math.atan2(closest.y,closest.x);lateral=drop*tan*.96
        directions=[(0.,0.)]
        for fraction in (1.,.5):
            directions += [(lateral*fraction*math.cos(az+i*math.pi/8),lateral*fraction*math.sin(az+i*math.pi/8)) for i in range(16)]
        nearest=collider.find_nearest(point)
        if nearest and nearest[1] is not None:
            normal_az=math.atan2(nearest[1].y,nearest[1].x)
            directions.append((lateral*math.cos(normal_az),lateral*math.sin(normal_az)))
        for dx,dy in directions:
            candidate=point+Vector((dx,dy,-drop))
            if (candidate-start).xy.length>limit:continue
            key=(round((candidate.x-start.x)/.10),round((candidate.y-start.y)/.10),round((start.z-candidate.z)/.05))
            g=cost+(candidate-point).length
            if seen.get(key,float('inf'))<=g:continue
            if not ts._segment_printable_down(point,candidate,angle) or not tc.segment_clear(collider,point,candidate,radius,radius,gap=gap):continue
            seen[key]=g;nodes.append((candidate,idx,g))
            # A bounded best-first search: no claim of global shortest paths.
            h=heuristic(candidate)
            heapq.heappush(queue,(g+1.15*h,len(nodes)-1))
    return network.NetworkRoute(reason='guided_budget_exhausted' if queue else 'no_guided_descending_route',expanded=expanded,method=method)
