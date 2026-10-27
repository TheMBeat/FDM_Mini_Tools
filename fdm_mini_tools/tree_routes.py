"""Bounded, deterministic, strictly descending waypoint search.

Geometry predicates are callbacks: every emitted edge is certified by the same
continuous swept-radius check as the direct planner. No relaxed collision or
contact exemptions. A budget limit is an unresolved result, never success.
"""
from dataclasses import dataclass,field
import heapq
import math
from mathutils import Vector

@dataclass
class RouteResult:
    points: list = field(default_factory=list)
    reason: str = 'no_clear_route'
    expanded: int = 0
    method: str = 'WAYPOINT_EXPERIMENTAL'


def search(start, goal, clear, printable, *, floor, max_angle=32., radius=16.,
           step=1.5, budget=240):
    start=Vector(start)
    if start.z <= floor+.1:
        return RouteResult(reason='insufficient_height_above_raft')
    if budget <= 0:
        return RouteResult(reason='search_budget_exhausted')
    step=max(.5,float(step))
    lateral=step*math.tan(math.radians(max_angle-.05))*.85
    quantum=max(.1,lateral*.5)
    nodes=[(start,-1,0.)]
    queue=[(0.,0)]
    seen={}
    expanded=0
    while queue and expanded<budget:
        _,idx=heapq.heappop(queue)
        pos,parent,cost=nodes[idx]
        expanded+=1
        target=goal(pos)
        if target is not None:
            path=[Vector(target),pos]
            while parent>=0:
                pos,parent,_=nodes[parent]
                path.append(pos)
            path.reverse()
            return RouteResult(path,'rooted',expanded)
        drop=min(step,pos.z-floor-.11)
        if drop<.10:
            continue
        offsets=[(0.,0.)]+[(lateral*drop/step*math.cos(i*math.pi/4),
                           lateral*drop/step*math.sin(i*math.pi/4)) for i in range(8)]
        for dx,dy in offsets:
            candidate=pos+Vector((dx,dy,-drop))
            if math.hypot(candidate.x-start.x,candidate.y-start.y)>radius:
                continue
            key=(round((candidate.x-start.x)/quantum),round((candidate.y-start.y)/quantum),round((start.z-candidate.z)/step,3))
            g=cost+(candidate-pos).length
            if seen.get(key,float('inf'))<=g:
                continue
            if not printable(pos,candidate) or not clear(pos,candidate):
                continue
            seen[key]=g
            nodes.append((candidate,idx,g))
            # Remaining vertical drop is an admissible path-length bound.
            heapq.heappush(queue,(g+candidate.z-floor,len(nodes)-1))
    return RouteResult(reason='search_budget_exhausted' if queue else 'no_clear_descending_route',expanded=expanded)
