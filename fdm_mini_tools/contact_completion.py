"""Deterministic local contact recovery, independent of model names/poses.

Explore compact exits before asking the existing certified router. No new
surface exemptions, collision predicates, bridge assumptions or angle limits.
"""
import math
from mathutils import Vector
from . import tree_support as ts,required_minima as rm


from .support_budget import contact_budget

@contact_budget
def choose(point,collider,cfg,route_finder,record=None,tip_route_finder=None):
    failures={};seen=set();calls=0;trials=0
    points=list(record['candidate_points']) if record else [list(point)]
    if record:
        # Explore the actual adjacent surface inside the contact-tip footprint.
        # Every accepted candidate must STILL contain the original birth in
        # its real cone, then in the final closed rooted support mesh.
        birth=Vector(record['point']);limit=max(.06,float(cfg.get('touch_diameter',.3))*.5)*.8
        for original in list(points)[1:]:
            delta=Vector(original)-birth
            if delta.length<.0001:continue
            for distance in (limit*.5,limit):
                candidate=birth+delta.normalized()*distance
                hit=collider.find_nearest(candidate)
                if (hit[0] is not None and hit[3]<.0001
                        and candidate.z-birth.z<=float(cfg.get('tree_layer_height',.08))
                        and all((hit[0]-Vector(p)).length>.0001 for p in points)):
                    points.append(list(hit[0]))
    def fail(reason):failures[reason]=failures.get(reason,0)+1
    lengths=list(dict.fromkeys([float(cfg.get('tree_tip_cone_length',.32)),.5,.65,.8]))
    for length in lengths:
        for p in points:
            local_calls=0
            nearest=collider.find_nearest(Vector(p))
            if not nearest or nearest[1] is None:continue
            normal=nearest[1];az0=math.atan2(normal.y,normal.x)
            directions=[None,Vector((0,0,-1))]
            limit=max(5.,min(45.,float(cfg.get('max_neck_angle',25))))
            for angle in (limit*.5,limit-.02):
                for offset in range(0,360,30):
                    az=az0+math.radians(offset);a=math.radians(angle)
                    directions.append(Vector((math.cos(az)*math.sin(a),math.sin(az)*math.sin(a),-math.cos(a))))
            for direction in directions:
                if local_calls>=int(cfg.get('_completion_local_routes',4)):break
                local=dict(cfg,tree_tip_cone_length=length,_contact_full_azimuth=True)
                if direction is not None:
                    local.update(_contact_exit_direction=list(direction),_contact_axis_penetration=True)
                # Alternative adapters matter only after a viable compact neck.
                schedules=cfg.get('_completion_adapter_schedules',[(0.,0),(.6,0),(1.1,0),(1.8,0),(2.2,0),(1.8,1),(2.2,1)])
                for adapter_length,choice in schedules:
                    if local_calls>=int(cfg.get('_completion_local_routes',4)):break
                    trials+=1
                    local.update(_required_adapter_min_length=adapter_length,_required_adapter_choice=choice)
                    reasons=[];contact=ts._contact_from_point(collider,Vector(p),local,reasons)
                    if not contact:
                        reason=reasons[-1] if reasons else 'invalid_contact';fail(reason)
                        if reason=='adapter_no_clear_exit' and adapter_length==0. and tip_route_finder:
                            neck=ts._contact_from_point(collider,Vector(p),dict(local,_contact_neck_only=True))
                            if neck:
                                neck_node,neck_edges=neck
                                valid_birth=not record or rm.covered_by_edges(record,neck_edges)
                                valid_angle=ts._segment_printable_down(neck_edges[0].a,neck_edges[0].b,limit,min_drop=.02)
                                valid_penetration=direction is None or not collider.outside_winding(neck_edges[0].a)
                                if valid_birth and valid_angle and valid_penetration:
                                    route=tip_route_finder(ts.TreeNode(neck_node))
                                    if route is not None and route.points:
                                        return ts.TreeComponent(ts.TreeNode(neck_node),neck_edges,1,route),dict(
                                            point=list(p),cone_length_mm=length,method=route.method,
                                            trials=trials,route_calls=calls,direct_tip_attachment=True)
                        if reason!='adapter_no_clear_exit':break
                        # Choice zero with no minimum already searched EVERY
                        # adapter distance/direction. Later schedules only take
                        # subsets of those same exits, so cannot find one.
                        if adapter_length <= 0. and choice == 0:break
                        continue
                    node,edges=contact
                    if record and not rm.covered_by_edges(record,edges):fail('cone_misses_birth');break
                    if not ts._segment_printable_down(edges[0].a,edges[0].b,limit,min_drop=.02):
                        fail('actual_cone_angle');break
                    key=tuple(round(float(x),4) for x in node)
                    if key in seen:continue
                    seen.add(key);calls+=1;local_calls+=1
                    route=route_finder(ts.TreeNode(node))
                    if route.points:
                        if direction is not None and collider.outside_winding(edges[0].a):
                            fail('tip_penetration_outside');continue
                        return ts.TreeComponent(ts.TreeNode(node),edges,1,route),dict(point=list(p),
                            cone_length_mm=length,direction=list(direction) if direction is not None else None,
                            adapter_min_length=adapter_length,adapter_choice=choice,method=route.method,
                            trials=trials,route_calls=calls)
                    fail(route.reason)
    return None,dict(reasons=failures,trials=trials,route_calls=calls)
