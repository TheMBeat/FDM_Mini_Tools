"""Experimental FDM tree support generator.

The first implementation intentionally keeps the planning logic in Python:
SLASG VertexScatter supplies model-contact candidates, while this module builds
an independent grounded tree graph and converts it to support geometry.

Hard invariants for FDM_TREE_V0:
- only the explicitly bounded short contact cone may touch the MINI;
- structural branches never terminate on the MINI;
- every emitted support component has a verified route to Z=0/base;
- structural branch/trunk checks use OUTER-SURFACE clearance, not center-line clearance;
- unresolved components are omitted instead of producing floating geometry.
"""

from dataclasses import dataclass, field
import math
import json
import time

import bpy
from mathutils import Vector
from . import tree_collision, tree_routes, i18n


TREE_OBJECT_NAME = "SUPPORTS"
TREE_ROLE = "FDM_TREE_SUPPORTS"
POINT_SOURCE_ROLE = "FDM_TREE_SCATTER_POINTS"


@dataclass
class SupportEdge:
    a: Vector
    b: Vector
    radius_a: float
    radius_b: float
    kind: str
    # Only TIP_CONE may carry an explicit local contact-zone bound.
    contact_zone: object = None


@dataclass
class TreeNode:
    pos: Vector
    load: int = 1


@dataclass
class TreeComponent:
    node: TreeNode
    edges: list = field(default_factory=list)
    leaf_count: int = 1
    certified_route: object = None


@dataclass
class TreeStats:
    raw_points: int = 0
    bed_supported_points: int = 0
    contacts: int = 0
    rejected_points: int = 0
    merge_count: int = 0
    rooted_components: int = 0
    rooted_tips: int = 0
    unresolved_components: int = 0
    unresolved_tips: int = 0
    segment_count: int = 0
    rejection_reasons: dict = field(default_factory=dict)
    rejected_contacts: list = field(default_factory=list)
    unresolved_routes: list = field(default_factory=list)
    collision_rejections: dict = field(default_factory=dict)
    mesh_qa: dict = field(default_factory=dict)
    raft_qa: dict = field(default_factory=dict)
    routes: list = field(default_factory=list)
    contact_audit: dict = field(default_factory=dict)
    required_minima: dict = field(default_factory=dict)
    stability: dict = field(default_factory=dict)
    completion: dict = field(default_factory=dict)
    phase_seconds: dict = field(default_factory=dict)

    def as_dict(self):
        return {
            "raw_points": self.raw_points,
            "bed_supported_points": self.bed_supported_points,
            "contacts": self.contacts,
            "rejected_points": self.rejected_points,
            "merges": self.merge_count,
            "rooted_components": self.rooted_components,
            "rooted_tips": self.rooted_tips,
            "unresolved_components": self.unresolved_components,
            "unresolved_tips": self.unresolved_tips,
            "segments": self.segment_count,
            "rejection_reasons": self.rejection_reasons,
            "rejected_contacts": self.rejected_contacts,
            "unresolved_routes": self.unresolved_routes,
            "collision_rejections": self.collision_rejections,
            "mesh_qa": self.mesh_qa,
            "raft_qa": self.raft_qa,
            "routes": self.routes,
            "contact_audit": self.contact_audit,
            "required_minima": self.required_minima,
            "stability": self.stability,
            "completion": self.completion,
            "phase_seconds": self.phase_seconds,
        }


def _log(msg):
    print(i18n.format_iface('[FDM Tree] {v0}', v0=msg))


def _progress(callback, percent, step):
    if callback:
        callback(percent, step)


def _safe_normal(normal):
    if normal is None or normal.length < 1e-8:
        return Vector((0.0, 0.0, -1.0))
    return normal.normalized()


def _branch_radius(load, branch_radius, trunk_radius):
    # Cross-sectional area grows approximately with supported leaf count.
    return min(trunk_radius, branch_radius * math.sqrt(max(1, int(load))))

def _structural_clearance(cfg, *radii):
    """Required CENTER-LINE clearance for structural support geometry.

    ``tree_model_clearance`` is a requested SURFACE-to-MINI gap.  The v0.1
    prototype compared only the center line with the MINI, so a 1.0 mm branch
    with a nominal 0.25 mm clearance could still overlap the model by roughly
    0.25 mm.  Structural checks now add the largest local support radius.
    """
    surface_gap = max(0.0, float(cfg.get("tree_model_clearance", 0.45)))
    radius = max([0.0] + [max(0.0, float(r)) for r in radii])
    return surface_gap + radius


def _point_clear(bvh, point, centerline_clearance):
    nearest = bvh.find_nearest(point)
    if not nearest or nearest[0] is None or nearest[3] is None:
        return False
    _location, _normal, _face, distance = nearest
    return (distance > max(0.0, float(centerline_clearance)) + tree_collision.EPS_MM
            and tree_collision.outside(bvh, point, nearest))


def _dedupe_points(points, tolerance):
    tolerance = max(0.05, float(tolerance))
    inv = 1.0 / tolerance
    found = {}
    for p in points:
        key = (
            int(round(p.x * inv)),
            int(round(p.y * inv)),
            int(round(p.z * inv)),
        )
        if key not in found:
            found[key] = p
    return list(found.values())


def _segment_angle_from_vertical(a, b):
    d = b - a
    vertical = abs(d.z)
    horizontal = math.hypot(d.x, d.y)
    return math.degrees(math.atan2(horizontal, max(vertical, 1e-8)))


def _segment_printable_down(a, b, max_angle, min_drop=0.04):
    """Return True only for a genuinely downward, FDM-printable segment.

    The previous prototype used ``abs(d.z)`` for angle checks. That was fine
    for measuring orientation, but it did not make horizontal/near-horizontal
    contact geometry impossible. Tree Alpha 4 treats downward progress as a
    hard invariant: every support segment below the MINI must lose Z and stay
    within ``max_angle`` from vertical.
    """
    d = b - a
    drop = -d.z
    if drop < max(0.001, float(min_drop)):
        return False
    horizontal = math.hypot(d.x, d.y)
    angle = math.degrees(math.atan2(horizontal, max(drop, 1e-8)))
    return angle <= float(max_angle) + 1e-6


def _printable_tip_direction(normal, max_angle):
    """Clamp the outward MINI normal to a printable downward direction.

    The XY heading follows the surface normal, while Z is forced downward.
    This preserves an outward component for side/underside contacts but never
    creates a horizontal SLA tip. Upward-facing contacts that cannot be exited
    without travelling into the MINI are rejected.
    """
    n = _safe_normal(normal)
    max_angle = max(5.0, min(50.0, float(max_angle)))
    xy = Vector((n.x, n.y, 0.0))
    xy_len = xy.length

    if xy_len < 1e-8:
        if n.z >= -0.05:
            return None
        return Vector((0.0, 0.0, -1.0))

    xy.normalize()
    natural_angle = math.degrees(math.atan2(xy_len, max(-n.z, 1e-8))) if n.z < 0.0 else 90.0
    # mathutils stores world endpoints as float32. Construct slightly INSIDE
    # the angular limit: subtracting nearby endpoints can otherwise turn an
    # exactly 25-degree direction into 25.00011 degrees and discard valid tips.
    # Keep the final strict segment check; do not loosen the printable limit.
    angle = math.radians(min(max_angle - 0.01, natural_angle))
    direction = Vector((xy.x * math.sin(angle), xy.y * math.sin(angle), -math.cos(angle)))
    direction.normalize()

    # Must still move out of the surface, not back into it.
    if direction.dot(n) <= 0.05:
        return None
    return direction


def _segment_clear(bvh, a, b, clearance=0.25, sample_step=0.55):
    """Compatibility wrapper: certify constant centerline clearance.

    sample_step is retained for callers but cannot relax the continuous bound.
    """
    return tree_collision.segment_clear(bvh, a, b, clearance, clearance)


def _contact_from_point(bvh, p, cfg, diagnostics=None):
    def reject(reason):
        if diagnostics is not None:
            diagnostics.append(reason)
        return None
    nearest = bvh.find_nearest(p)
    if not nearest:
        return reject('missing_surface')
    surface, normal, _face, distance = nearest
    if surface is None or normal is None or distance is None:
        return reject('missing_surface')

    # VertexScatter points should sit on the target. Keep a generous guard to
    # ignore any helper/intermediate vertices should the library change.
    max_distance = max(0.75, float(cfg.get("safe_distance", 0.55)) + 0.50)
    if distance > max_distance:
        return reject('point_off_surface')

    normal = _safe_normal(normal)
    touch_depth = max(0.0, float(cfg.get("touch_depth", 0.18)))
    touch_r = max(0.06, float(cfg.get("touch_diameter", 0.30)) * 0.5)
    neck_r = max(touch_r, float(cfg.get("neck_diameter", 0.50)) * 0.5)
    branch_r = max(neck_r, float(cfg.get("tree_branch_diameter", 1.00)) * 0.5)

    # Tree tips are intentionally NOT the classic 2 mm neck. For FDM that
    # produced long fragile needles. We keep the classic Touch Ø / Touch Depth /
    # Neck Ø, but use a compact Tree-specific cone and neck run.
    cone_len = max(0.18, min(0.80, float(cfg.get("tree_tip_cone_length", 0.32))))
    neck_len = max(0.12, min(1.20, float(cfg.get("tree_tip_neck_length", 0.35))))
    tip_max_angle = max(5.0, min(45.0, float(cfg.get("max_neck_angle", 25.0))))
    tree_max_angle = max(10.0, min(55.0, float(cfg.get("tree_max_branch_angle", 32.0))))

    direction = _printable_tip_direction(normal, tip_max_angle)
    if '_contact_exit_direction' in cfg:
        direction = Vector(cfg['_contact_exit_direction'])
        if (not all(math.isfinite(x) for x in direction) or direction.length < .99
                or direction.dot(normal) <= .05):
            return reject('tip_direction')
        direction.normalize()
    if direction is None:
        return reject('tip_direction')

    # The preferred cone can end too close to a sloping surface for the neck
    # radius plus its existing 0.02 mm gap. Allow at most 0.04 mm extra cone,
    # derived from the local tangent plane, then certify the entire neck below.
    # This is not an obstacle bypass or a relaxation of the clearance gate.
    exit_dot = direction.dot(normal)
    required_exit = (neck_r + 0.025) / exit_dot
    cone_len = max(cone_len, min(required_exit, cone_len + 0.04, 0.80))

    # Small intentional penetration is still measured along the actual model
    # normal. Everything OUTSIDE the MINI then travels downwards in a printable
    # direction. This makes horizontal tips geometrically impossible.
    contact = surface - normal * touch_depth
    if cfg.get('_contact_axis_penetration',False):
        contact = surface - direction * touch_depth
    cone_end = surface + direction * cone_len
    neck_end = cone_end + direction * neck_len

    if not _segment_printable_down(surface, cone_end, tip_max_angle, min_drop=0.02):
        return reject('tip_angle')
    if not _segment_printable_down(cone_end, neck_end, tip_max_angle, min_drop=0.02):
        return reject('neck_angle')

    # Only the short cone has an approved contact-zone exemption. The neck
    # must be outside the MINI for its ENTIRE radius, including both ends.
    if not tree_collision.segment_clear(bvh, cone_end, neck_end, neck_r, neck_r, gap=0.02):
        return reject('neck_collision')
    if cfg.get('_contact_axis_penetration',False) and bvh.outside(contact):
        return reject('tip_penetration_outside')
    zone_radius = max((contact-surface).length+touch_r,
                      (cone_end-surface).length+neck_r)

    edges = [
        SupportEdge(contact, cone_end, touch_r, neck_r, "TIP_CONE",
                    (tuple(surface), zone_radius)),
        SupportEdge(cone_end, neck_end, neck_r, neck_r, "TIP_NECK"),
    ]
    if cfg.get('_contact_neck_only',False):
        # Planning candidate only. The caller must certify a bounded adapter
        # into an existing rooted graph before this can enter the mesh.
        return neck_end,edges

    # Move from the compact tip assembly to the first structural branch point.
    # We continue in downward-printable directions until the full branch body
    # (radius + requested model gap) is clear of the MINI. The adapter may be
    # close to the contact, but it may not geometrically cut through the MINI.
    structural_clearance = _structural_clearance(cfg, branch_r)
    preferred_az = math.atan2(direction.y, direction.x)
    preferred_angle = math.degrees(math.acos(max(-1.0, min(1.0, -direction.z))))

    directions = []
    for angle_deg in (
        min(preferred_angle, tree_max_angle),
        min(tree_max_angle, max(8.0, preferred_angle * 0.65)),
        0.0,
        tree_max_angle,
    ):
        offsets=(0.0,30.0,-30.0,60.0,-60.0,90.0,-90.0)
        if cfg.get('_contact_full_azimuth',False):offsets=offsets+(120.,-120.,150.,-150.,180.)
        for az_offset_deg in offsets:
            if angle_deg <= 0.1:
                cand_dir = Vector((0.0, 0.0, -1.0))
            else:
                az = preferred_az + math.radians(az_offset_deg)
                ang = math.radians(angle_deg)
                cand_dir = Vector((math.cos(az) * math.sin(ang),
                                   math.sin(az) * math.sin(ang),
                                   -math.cos(ang)))
            cand_dir.normalize()
            if all((cand_dir - existing).length > 1e-4 for existing in directions):
                directions.append(cand_dir)

    branch = None
    valid_exit = 0
    adapter_choice = max(0,int(cfg.get('_required_adapter_choice',0)))
    adapter_min_length = max(0.,float(cfg.get('_required_adapter_min_length',0.)))
    for dist in (0.25, 0.40, 0.60, 0.85, 1.10, 1.40, 1.80, 2.20):
        if dist < adapter_min_length:continue
        for cand_dir in directions:
            candidate = neck_end + cand_dir * dist
            # A descending rooted route cannot start below its Z=0 target.
            # Try the other certified exits instead of routing an impossible start.
            if candidate.z <= 0.:
                continue
            if not _segment_printable_down(neck_end, candidate, tree_max_angle, min_drop=0.04):
                continue
            if not _point_clear(bvh, candidate, structural_clearance):
                continue
            if not tree_collision.segment_clear(bvh, neck_end, candidate, neck_r, branch_r, gap=0.02):
                continue
            if valid_exit < adapter_choice:
                valid_exit += 1
                continue
            branch = candidate
            break
        if branch is not None:
            break

    if branch is None:
        return reject('adapter_no_clear_exit')

    edges.append(SupportEdge(neck_end, branch, neck_r, branch_r, "TIP_ADAPTER"))
    return branch, edges

def _merge_candidate(a, b, cfg, bvh):
    pa = a.node.pos
    pb = b.node.pos
    merge_distance = max(0.5, float(cfg.get("tree_merge_distance", 4.0)))
    xy_distance = math.hypot(pa.x - pb.x, pa.y - pb.y)
    if xy_distance > merge_distance:
        return None

    # Don't merge supports that are vertically far apart; that creates long
    # sideways branches and poor FDM mechanics.
    descent = max(0.8, float(cfg.get("branch_descent", 4.5)))
    if abs(pa.z - pb.z) > descent * 1.75:
        return None

    max_angle = max(10.0, min(55.0, float(cfg.get("tree_max_branch_angle", 32.0))))
    tan_angle = math.tan(math.radians(max_angle))
    wx_a = max(1, a.node.load)
    wx_b = max(1, b.node.load)
    x = (pa.x * wx_a + pb.x * wx_b) / (wx_a + wx_b)
    y = (pa.y * wx_a + pb.y * wx_b) / (wx_a + wx_b)

    z = min(pa.z, pb.z) - descent
    for child in (pa, pb):
        horizontal = math.hypot(child.x - x, child.y - y)
        required_drop = horizontal / max(0.05, tan_angle)
        z = min(z, child.z - required_drop)

    base_height = max(0.0, float(cfg.get("base_height", 1.8)))
    if z <= base_height + 0.45:
        return None

    center = Vector((x, y, z))

    branch_r = max(0.10, float(cfg.get("tree_branch_diameter", 1.00)) * 0.5)
    trunk_r = max(branch_r, float(cfg.get("tree_trunk_diameter", 1.80)) * 0.5)
    parent_load = max(1, a.node.load + b.node.load)
    parent_r = _branch_radius(parent_load, branch_r, trunk_r)
    a_r = _branch_radius(a.node.load, branch_r, trunk_r)
    b_r = _branch_radius(b.node.load, branch_r, trunk_r)
    gap = max(0.0, float(cfg.get('tree_model_clearance', 0.45)))

    # Try the direct weighted midpoint, then a few small offsets. This handles
    # cases where the mathematically ideal merge point would clip a leg/weapon.
    candidates = [center]
    for radius in (0.60, 1.20):
        for deg in range(0, 360, 45):
            rad = math.radians(deg)
            candidates.append(
                Vector((x + math.cos(rad) * radius, y + math.sin(rad) * radius, z))
            )

    for candidate in candidates:
        if not _segment_printable_down(pa, candidate, max_angle):
            continue
        if not _segment_printable_down(pb, candidate, max_angle):
            continue
        if not tree_collision.segment_clear(bvh, pa, candidate, a_r, parent_r, gap=gap):
            continue
        if not tree_collision.segment_clear(bvh, pb, candidate, b_r, parent_r, gap=gap):
            continue
        return candidate
    return None


def _merge_round(components, cfg, bvh):
    if len(components) < 2:
        return components, 0

    max_dist = max(0.5, float(cfg.get("tree_merge_distance", 4.0)))
    candidates = []
    for i in range(len(components)):
        pi = components[i].node.pos
        for j in range(i + 1, len(components)):
            pj = components[j].node.pos
            dx = pi.x - pj.x
            dy = pi.y - pj.y
            dxy = math.hypot(dx, dy)
            if dxy <= max_dist:
                candidates.append((dxy, i, j))
    candidates.sort(key=lambda item: item[0])

    used = set()
    merged_components = []
    merge_count = 0
    branch_r = max(0.10, float(cfg.get("tree_branch_diameter", 1.00)) * 0.5)
    trunk_r = max(branch_r, float(cfg.get("tree_trunk_diameter", 1.80)) * 0.5)

    for _distance, i, j in candidates:
        if i in used or j in used:
            continue
        a = components[i]
        b = components[j]
        target = _merge_candidate(a, b, cfg, bvh)
        if target is None:
            continue

        load = a.node.load + b.node.load
        parent_r = _branch_radius(load, branch_r, trunk_r)
        a_r = _branch_radius(a.node.load, branch_r, trunk_r)
        b_r = _branch_radius(b.node.load, branch_r, trunk_r)
        parent = TreeNode(target, load=load)
        edges = list(a.edges) + list(b.edges)
        edges.append(SupportEdge(a.node.pos, target, a_r, parent_r, "BRANCH"))
        edges.append(SupportEdge(b.node.pos, target, b_r, parent_r, "BRANCH"))
        merged_components.append(
            TreeComponent(parent, edges, a.leaf_count + b.leaf_count)
        )
        used.add(i)
        used.add(j)
        merge_count += 1

    for idx, component in enumerate(components):
        if idx not in used:
            merged_components.append(component)

    return merged_components, merge_count


def _find_ground_target(node, cfg, bvh):
    pos = node.pos
    use_raft = bool(cfg.get("use_raft", True))
    raft_thickness = max(0.0, float(cfg.get("raft_floor_thickness", 0.60))) if use_raft else 0.0
    base_height = max(0.0, float(cfg.get("base_height", 1.8))) if use_raft else 0.0
    target_z = raft_thickness + base_height
    max_angle = max(10.0, min(55.0, float(cfg.get("tree_max_branch_angle", 32.0))))
    branch_r = max(0.10, float(cfg.get("tree_branch_diameter", 1.00)) * 0.5)
    trunk_r = max(branch_r, float(cfg.get("tree_trunk_diameter", 1.80)) * 0.5)
    node_r = _branch_radius(node.load, branch_r, trunk_r)
    base_r = max(trunk_r, float(cfg.get("base_diameter", 4.6)) * 0.5) if use_raft else node_r
    if '_ground_base_radius' in cfg:
        base_r = max(node_r,min(base_r,float(cfg['_ground_base_radius'])))
    trunk_clearance = _structural_clearance(cfg, node_r)
    target_clearance = _structural_clearance(cfg, node_r)
    base_clearance = _structural_clearance(cfg, base_r)
    search_radius = max(0.0, float(cfg.get("tree_ground_search_radius", 16.0)))
    step = max(0.5, float(cfg.get("tree_ground_search_step", 1.5)))

    candidates = [Vector((pos.x, pos.y, target_z))]
    radius = step
    while radius <= search_radius + 1e-6:
        phase = 15.0 if int(round(radius / step)) % 2 else 0.0
        for deg in range(0, 360, 30):
            rad = math.radians(deg + phase)
            candidates.append(
                Vector((pos.x + math.cos(rad) * radius,
                        pos.y + math.sin(rad) * radius,
                        target_z))
            )
        radius += step

    candidates.sort(key=lambda p: (p - pos).length)
    for target in candidates:
        if not _segment_printable_down(pos, target, max_angle, min_drop=0.10):
            continue
        # The trunk reaches the TOP of the flare at node radius. The wider
        # base radius exists down at raft-top Z, so validate both locations
        # with their actual local radii instead of applying Base Ø at the top.
        if not _point_clear(bvh, target, target_clearance):
            continue
        base_center = Vector((target.x, target.y, raft_thickness))
        if use_raft and not _point_clear(bvh, base_center, base_clearance):
            continue
        if (use_raft and base_height > 0.05
                and not tree_collision.segment_clear(bvh, base_center, target, base_r, node_r,
                    gap=max(0.0, float(cfg.get('tree_model_clearance', 0.45))))):
            continue
        if _segment_clear(bvh, pos, target, clearance=trunk_clearance):
            return target
    return None

def _find_ground_route(node,cfg,bvh):
    target=_find_ground_target(node,cfg,bvh)
    if target is not None:
        return tree_routes.RouteResult([node.pos,target],'rooted',0,'DIRECT')
    if cfg.get('tree_complete_contacts',False) and cfg.get('use_raft',True):
        raft=float(cfg.get('raft_floor_thickness',.6))
        height=float(cfg.get('base_height',1.8))
        # Short contacts do not need the full configured wide/tall foot.
        # The same continuous taper and model-gap predicate certifies it.
        if raft+.25 < node.pos.z < raft+height+1.5:
            branch_radius=max(.1,float(cfg.get('tree_branch_diameter',1))*.5)
            radius=_branch_radius(node.load,branch_radius,
                max(branch_radius,float(cfg.get('tree_trunk_diameter',1.8))*.5))
            foot=max(.1,min(height,node.pos.z-raft-.15))
            preferred=max(radius,float(cfg.get('base_diameter',4.6))*.5)
            for base_radius in (max(radius,preferred*.75),max(radius,preferred*.5),radius):
                local=dict(cfg,base_height=foot,_ground_base_radius=base_radius)
                target=_find_ground_target(node,local,bvh)
                if target is not None:
                    route=tree_routes.RouteResult([node.pos,target],'rooted',0,'COMPACT_FOOT')
                    route.ground_base_radius=base_radius
                    return route
    if cfg.get('tree_route_mode','DIRECT') != 'WAYPOINT_EXPERIMENTAL':
        return tree_routes.RouteResult(reason='no_clear_ground_target',method='DIRECT')
    raft=max(0.,float(cfg.get('raft_floor_thickness',.6))) if cfg.get('use_raft',True) else 0.
    branch=max(.1,float(cfg.get('tree_branch_diameter',1.))*.5)
    radius=_branch_radius(node.load,branch,max(branch,float(cfg.get('tree_trunk_diameter',1.8))*.5))
    gap=max(0.,float(cfg.get('tree_model_clearance',.45)))
    angle=max(10.,min(55.,float(cfg.get('tree_max_branch_angle',32.))))
    def goal(pos):
        # A shortened foot is useful for contacts below the configured flare
        # top. Validate its full actual taper; never route upwards to that top.
        foot=max(.10,min(float(cfg.get('base_height',1.8)),pos.z-raft-.15))
        local=dict(cfg,base_height=foot,tree_ground_search_radius=min(1.5,float(cfg.get('tree_ground_search_radius',16.))))
        target=_find_ground_target(TreeNode(pos,node.load),local,bvh)
        if target is not None and math.hypot(target.x-node.pos.x,target.y-node.pos.y)>float(cfg.get('tree_ground_search_radius',16.)):
            return None
        return target
    return tree_routes.search(node.pos,goal,
        lambda a,b:tree_collision.segment_clear(bvh,a,b,radius,radius,gap=gap),
        lambda a,b:_segment_printable_down(a,b,angle,min_drop=.1),
        floor=raft,max_angle=angle,radius=float(cfg.get('tree_ground_search_radius',16.)),
        step=float(cfg.get('tree_ground_search_step',1.5)),budget=int(cfg.get('tree_route_budget',64)))


def _build_curve_mesh(edges, cfg, name=TREE_OBJECT_NAME):
    """Compatibility entry point: closed solids and connected junctions."""
    from . import tree_mesh
    obj = tree_mesh.build_edges(edges, cfg, name)
    obj["fdm_mini_tools_role"] = TREE_ROLE
    obj["fdm_tree_strategy"] = "FDM_TREE_V0"
    return obj


def _convex_hull_2d(points):
    pts = sorted(set((round(float(x), 6), round(float(y), 6)) for x, y in points))
    if len(pts) <= 1:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0.0:
            lower.pop()
        lower.append(p)

    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0.0:
            upper.pop()
        upper.append(p)

    return lower[:-1] + upper[:-1]


def _build_unified_raft(root_points, cfg, name="FDM_TREE_RAFT"):
    """Create a simple closed unified raft below all rooted tree trunks.

    Alpha 4 deliberately uses a robust convex footprint instead of the old
    individual base pads. Perforation/concave footprint optimisation can come
    after routing and printability are validated.
    """
    if not root_points:
        return None

    thickness = max(0.20, float(cfg.get("raft_floor_thickness", 0.60)))
    expand = max(0.0, float(cfg.get("raft_expand_width", 1.50)))
    base_radius = max(0.50, float(cfg.get("base_diameter", 4.60)) * 0.5)
    footprint_radius = base_radius + expand

    cloud = []
    samples = 16
    for p in root_points:
        for i in range(samples):
            a = 2.0 * math.pi * i / samples
            cloud.append((p.x + math.cos(a) * footprint_radius,
                          p.y + math.sin(a) * footprint_radius))

    hull = _convex_hull_2d(cloud)
    if len(hull) < 3:
        return None

    n = len(hull)
    verts = [(x, y, 0.0) for x, y in hull] + [(x, y, thickness) for x, y in hull]
    faces = []
    faces.append(tuple(reversed(range(n))))
    faces.append(tuple(range(n, 2 * n)))
    for i in range(n):
        j = (i + 1) % n
        faces.append((i, j, n + j, n + i))

    mesh = bpy.data.meshes.new(name + "_MESH")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj["fdm_mini_tools_role"] = "FDM_TREE_RAFT"
    obj["fdm_tree_raft_style"] = "UNIFIED_CONVEX_V0"
    return obj


def _join_into_support(support, extra_objects):
    from . import tree_mesh
    extras = [o for o in extra_objects if o is not None and o.name in bpy.data.objects]
    support = tree_mesh.union([support] + extras, TREE_OBJECT_NAME)
    support["fdm_mini_tools_role"] = TREE_ROLE
    support["fdm_tree_strategy"] = "FDM_TREE_V0"
    return support


def collect_scatter_points(point_source, cfg):
    if point_source is None or point_source.type != "MESH":
        raise RuntimeError("FDM Tree needs a mesh of contact-point vertices (native or SLASG).")

    world = point_source.matrix_world
    raw = [world @ v.co for v in point_source.data.vertices]
    tolerance = max(0.10, float(cfg.get("touch_diameter", 0.30)) * 0.55)
    return raw, _dedupe_points(raw, tolerance)


def _supported_by_bed(bvh,point,cfg):
    # Only exact, certified model contact with the bed. A first-layer-height
    # proximity rule could hide a genuinely floating island and is not used.
    if not cfg.get('_direct_bed',False) or abs(point.z)>1e-5:
        return False
    surface,normal,_,distance=bvh.find_nearest(point)
    return bool(surface is not None and normal is not None and distance is not None
                and distance<=1e-5 and abs(surface.z)<=1e-5 and normal.z<-.9999)


def generate_tree_supports(model, point_source, cfg, progress=None):
    """Build the first experimental grounded FDM tree support object."""
    from . import core  # local import avoids an import cycle during add-on load

    if model is None:
        raise RuntimeError("FDM Tree requires a MINI object.")
    from . import contact_audit
    contact_audit.clear_markers()

    _progress(progress, 5, "Read SLASG contact points")
    raw_points, points = collect_scatter_points(point_source, cfg)
    stats = TreeStats(raw_points=len(raw_points))
    if not points and not cfg.get('tree_required_minima',False):
        raise RuntimeError("SLASG VertexScatter produced no support contact points.")

    phase_started=time.perf_counter()
    bvh = tree_collision.ModelCollider(model)
    stats.phase_seconds["collider"]=time.perf_counter()-phase_started
    from .support_budget import RecoveryBudget, prioritize
    if cfg.get('tree_budget_enabled', True):
        bvh.recovery_budget = RecoveryBudget(cfg)
    components = []

    phase_started=time.perf_counter()
    _progress(progress, 15, "Build SLA tips")
    for p in points:
        if _supported_by_bed(bvh,p,cfg):
            stats.bed_supported_points+=1
            continue
        reasons = []
        contact = _contact_from_point(bvh, p, cfg, diagnostics=reasons)
        if contact is None:
            stats.rejected_points += 1
            reason = reasons[-1] if reasons else 'contact_validation'
            stats.rejection_reasons[reason] = stats.rejection_reasons.get(reason, 0) + 1
            stats.rejected_contacts.append({'point': list(p), 'reason': reason})
            continue
        branch_pos, tip_edges = contact
        components.append(
            TreeComponent(TreeNode(branch_pos, load=1), list(tip_edges), leaf_count=1)
        )
        stats.contacts += 1

    if (not components and cfg.get('_direct_bed',False)
            and stats.bed_supported_points==len(points) and not stats.rejected_points):
        from . import required_minima
        births=required_minima.find(model,float(cfg.get('tree_layer_height',.08)),bvh)
        audit=contact_audit.audit(model,[],float(cfg.get('spacing',1.45)),
                                  float(cfg.get('overhang_angle',45.)),direct_bed=True)
        if not births and not audit['missing_count'] and audit['bed_supported_triangles']>0:
            stats.contact_audit=audit
            stats.required_minima=dict(missing=0,points=[],enforced=True)
            result=stats.as_dict();result['no_support_required']=True
            _progress(progress,100,"Bed contact verified; no additional supports required")
            return None,result
    if not components and not cfg.get('tree_required_minima',False):
        raise RuntimeError(i18n.format_iface('No usable FDM Tree contacts remained after surface validation: {v0}', v0=stats.rejection_reasons))

    stats.phase_seconds["contact_adapters"]=time.perf_counter()-phase_started
    phase_started=time.perf_counter()
    _progress(progress, 32, "Merge nearby branches")
    max_rounds = max(1, min(12, int(cfg.get("tree_merge_rounds", 6))))
    for round_index in range(max_rounds):
        components, merged = _merge_round(components, cfg, bvh)
        stats.merge_count += merged
        _log(
            i18n.format_iface('merge round {v0}: {v1} merges, {v2} active components', v0=round_index + 1, v1=merged, v2=len(components))
        )
        if merged == 0:
            break

    stats.phase_seconds["merge"]=time.perf_counter()-phase_started
    _progress(progress, 58, "Find required low points")
    rooted_edges = []
    branch_r = max(0.10, float(cfg.get("tree_branch_diameter", 1.00)) * 0.5)
    trunk_r = max(branch_r, float(cfg.get("tree_trunk_diameter", 1.80)) * 0.5)
    base_r = max(trunk_r, float(cfg.get("base_diameter", 4.6)) * 0.5)
    base_height = max(0.0, float(cfg.get("base_height", 1.8)))
    use_base = bool(cfg.get("use_raft", True))
    raft_thickness = max(0.0, float(cfg.get("raft_floor_thickness", 0.60))) if use_base else 0.0
    raft_roots = []
    certified_roots=[]
    pending_components=[]
    reuse=bool(cfg.get('tree_reuse_branches',False))
    from . import tree_network
    def reuse_or_ground(node):
        if reuse:
            route=tree_network.find(node,cfg,bvh,rooted_edges,certified_roots)
            if route.points:return route
        return _find_ground_route(node,cfg,bvh)

    from . import required_minima
    phase_started=time.perf_counter()
    births=required_minima.find(model,float(cfg.get('tree_layer_height',.08)),bvh)
    stats.phase_seconds["required_minima"]=time.perf_counter()-phase_started
    phase_started=time.perf_counter()
    if cfg.get('tree_prioritize_contacts', True) and births:
        _progress(progress,59,"Analyze layers to prioritize contacts")
        births,priority=prioritize(bvh,births,float(cfg.get('tree_layer_height',.08)))
        if hasattr(bvh,'recovery_budget'): bvh.recovery_budget.priority=priority
    stats.phase_seconds["layer_priority"]=time.perf_counter()-phase_started
    phase_started=time.perf_counter()
    _progress(progress,60,"Route trunks to buildplate")
    def already_supported(point):
        covered=required_minima.covered_by_edges(dict(point=list(point),flat_triangles=[]),rooted_edges)
        if covered and hasattr(bvh,'recovery_budget'): bvh.recovery_budget.redundant+=1
        return covered
    required_plan=[]
    def component_stream():
        yield from components
        if reuse:
            # First build the ordinary grounded forest, then retry failures
            # against that certified graph, independent of input seed order.
            retry=list(pending_components);pending_components.clear()
            for component,old_route in retry:
                route=tree_network.find(component.node,cfg,bvh,rooted_edges,certified_roots)
                if route.points:
                    yield TreeComponent(component.node,component.edges,component.leaf_count,route)
                else:pending_components.append((component,old_route))
        if not cfg.get('tree_required_minima',False):return
        for index,record in enumerate(births):
            _progress(progress,60+15*index/max(1,len(births)),i18n.format_iface('Required low point {v0}/{v1} check', v0=index + 1, v1=len(births)))
            if required_minima.covered_by_edges(record,rooted_edges):
                required_plan.append(dict(id=record['id'],status='existing_rooted_cone'))
                continue
            component,detail=required_minima.choose_contact(record,bvh,cfg,reuse_or_ground if reuse else None)
            required_plan.append(dict(id=record['id'],status='added' if component else 'no_certified_route',**detail))
            if component is not None:
                stats.contacts+=1
                yield component
        if not cfg.get('tree_complete_contacts',False):return
        from . import contact_completion
        recovery=[]
        # Preserve the established forest first. Supplements can only add
        # certified grounded contacts or transactionally widen carrying paths.
        for record in births:
            if required_minima.covered_by_edges(record,rooted_edges):continue
            _progress(progress,75,i18n.format_iface('Contact exit for low point {v0}/{v1} check', v0=record['id'] + 1, v1=len(births)))
            component,detail=contact_completion.choose(record['point'],bvh,cfg,reuse_or_ground,record,
                tip_route_finder=lambda node:tree_network.find_tip(node,cfg,bvh,rooted_edges,certified_roots) if reuse else None)
            recovery.append(dict(kind='minimum',id=record['id'],recovered=bool(component),**detail))
            if component:
                stats.contacts+=1
                row=next(p for p in required_plan if p['id']==record['id'])
                row.update(status='added',recovery=detail)
                yield component
        retry=list(pending_components);pending_components.clear()
        for old,old_route in retry:
            cones=[e for e in old.edges if e.kind=='TIP_CONE']
            for cone in cones:
                p=cone.contact_zone[0]
                if already_supported(p):continue
                _progress(progress,76,"Retry unresolved branch contact")
                component,detail=contact_completion.choose(p,bvh,dict(cfg,_completion_local_routes=24),reuse_or_ground,
                    tip_route_finder=lambda node:tree_network.find_tip(node,cfg,bvh,rooted_edges,certified_roots) if reuse else None)
                recovery.append(dict(detail,kind='unresolved',point=list(p),recovered=bool(component)))
                if component:yield component
                else:
                    # Retain one explicit failed leaf; do not count a merged
                    # sibling as unresolved after that sibling was recovered.
                    pending_components.append((TreeComponent(old.node,[cone],1),old_route))
        remaining=[]
        for rejected in stats.rejected_contacts:
            p=rejected['point']
            # Off-surface scatter helpers remain rejected, never snapped over
            # the existing distance guard or counted as recovered contacts.
            if rejected['reason']=='point_off_surface':remaining.append(rejected);continue
            if already_supported(p):
                stats.rejected_points-=1
                stats.rejection_reasons[rejected['reason']]-=1
                continue
            _progress(progress,77,"Retry rejected surface contact")
            component,detail=contact_completion.choose(p,bvh,cfg,reuse_or_ground,
                tip_route_finder=lambda node:tree_network.find_tip(node,cfg,bvh,rooted_edges,certified_roots) if reuse else None)
            recovery.append(dict(detail,kind='rejected',point=list(p),recovered=bool(component)))
            if component:
                stats.contacts+=1;stats.rejected_points-=1
                reason=rejected['reason'];stats.rejection_reasons[reason]-=1
                yield component
            else:remaining.append(rejected)
        stats.rejected_contacts=remaining
        stats.completion=dict(enabled=True,attempts=recovery,
            recovered=sum(r['recovered'] for r in recovery),
            unresolved_local=sum(not r['recovered'] for r in recovery))


        if reuse and cfg.get('tree_guided_recovery',False):
            from . import tree_guided
            guided=[]
            local=dict(cfg,_completion_local_routes=1)
            def guided_route(node):
                return tree_guided.find(node,cfg,bvh,rooted_edges,certified_roots,budget=1800)
            for record in births:
                if required_minima.covered_by_edges(record,rooted_edges):continue
                _progress(progress,78,i18n.format_iface('Route to rooted branch: low point {v0}', v0=record['id'] + 1))
                component,detail=contact_completion.choose(record['point'],bvh,local,guided_route,record)
                guided.append(dict(kind='minimum',id=record['id'],recovered=bool(component),**detail))
                if component:
                    stats.contacts+=1
                    next(p for p in required_plan if p['id']==record['id']).update(status='added',guided=detail)
                    yield component
            retry=list(pending_components);pending_components.clear()
            for old,old_route in retry:
                for cone in [e for e in old.edges if e.kind=='TIP_CONE']:
                    p=cone.contact_zone[0]
                    if already_supported(p):continue
                    component,detail=contact_completion.choose(p,bvh,local,guided_route)
                    guided.append(dict(detail,kind='unresolved',point=list(p),recovered=bool(component)))
                    if component:yield component
                    else:pending_components.append((TreeComponent(old.node,[cone],1),old_route))
            stats.completion['guided']=dict(attempts=guided,recovered=sum(r['recovered'] for r in guided))

        # Recover large, spatially separated downward patches missed by
        # scatter. These are heuristic candidates, never mandatory islands;
        # existing required contacts keep priority and share the same budget.
        from . import contact_audit
        _progress(progress,78,"Check underside contact gaps")
        audit=contact_audit.audit(model,[e.contact_zone[0] for e in rooted_edges if e.kind=='TIP_CONE'],
            float(cfg.get('spacing',1.45)),float(cfg.get('overhang_angle',45.)),
            direct_bed=bool(cfg.get('_direct_bed',False)))
        supplements=[]
        for region in sorted(audit['regions'],key=lambda r:(-r['area_mm2'],tuple(r['point'])))[:16]:
            point=Vector(region['point'])
            spacing=max(.3,float(cfg.get('spacing',1.45)))
            if any((point-Vector(e.contact_zone[0])).length<spacing for e in rooted_edges if e.kind=='TIP_CONE'):
                continue
            component,detail=contact_completion.choose(point,bvh,cfg,reuse_or_ground,
                tip_route_finder=lambda node:tree_network.find_tip(node,cfg,bvh,rooted_edges,certified_roots) if reuse else None)
            supplements.append(dict(detail,point=list(point),area_mm2=region['area_mm2'],recovered=bool(component)))
            if component:
                stats.contacts+=1
                yield component
        stats.completion['surface_patches']=dict(heuristic=True,candidate_regions=audit['missing_count'],
            attempted=supplements,recovered=sum(r['recovered'] for r in supplements),limit=16)

    for component in component_stream():
        route = component.certified_route or _find_ground_route(component.node, cfg, bvh)
        stats.routes.append(dict(node=list(component.node.pos),leaf_count=component.leaf_count,
            method=route.method,reason=route.reason,expanded=route.expanded,
            points=[list(p) for p in route.points],attachment=tree_network.provenance(route)))
        if not route.points:
            pending_components.append((component,route))
            continue

        attached=bool(getattr(route,'attachment',None))
        if attached:tree_network.commit(rooted_edges,route)
        comp_edges = list(component.edges)
        target=route.points[-1]
        node_r = _branch_radius(component.node.load, branch_r, trunk_r)
        if getattr(route,'connector_edges',None):comp_edges.extend(route.connector_edges)
        else:
            for a,b in zip(route.points,route.points[1:]):
                comp_edges.append(SupportEdge(a,b,node_r,node_r,'NETWORK_BRANCH' if attached else 'TRUNK'))

        if not attached:certified_roots.append(target.copy())
        if use_base and not attached:
            raft_top = Vector((target.x, target.y, raft_thickness))
            raft_roots.append(raft_top)
            if base_height > 0.05 and (target - raft_top).length > 0.05:
                comp_edges.append(
                    SupportEdge(raft_top, target, getattr(route,'ground_base_radius',base_r), node_r, "BASE_FLARE")
                )

        rooted_edges.extend(comp_edges)
        stats.rooted_components += 1
        stats.rooted_tips += component.leaf_count

    for component,route in pending_components:
        stats.unresolved_components+=1;stats.unresolved_tips+=component.leaf_count
        reason=route.reason
        stats.rejection_reasons[reason]=stats.rejection_reasons.get(reason,0)+component.leaf_count
        stats.unresolved_routes.append(dict(node=list(component.node.pos),leaf_count=component.leaf_count,
            reason=reason,contacts=[list(e.contact_zone[0]) for e in component.edges if e.kind=='TIP_CONE']))

    if not rooted_edges:
        raise RuntimeError(
            i18n.format_iface('FDM Tree could not route any support component safely to the buildplate: {v0}', v0=stats.rejection_reasons)
        )

    stats.phase_seconds["routing"]=time.perf_counter()-phase_started
    from . import tree_stability
    from . import tree_mesh
    original_edges=list(rooted_edges);original_roots=list(certified_roots);original_raft=list(raft_roots)
    variants=[cfg]
    if cfg.get('tree_stabilize_stems',False):variants.append(dict(cfg,_stability_style='THICKEN'))
    attempts=[]
    for variant_index,variant in enumerate(variants):
        rooted_edges[:]=original_edges;certified_roots[:]=original_roots;raft_roots[:]=original_raft
        raft=None;support=None
        try:
            _progress(progress,76,"Check and stabilize free stems")
            stats.stability=tree_stability.apply(rooted_edges,certified_roots,raft_roots,variant,bvh)
            _progress(progress,78,'Create tree support mesh')
            support=_build_curve_mesh(rooted_edges,cfg,TREE_OBJECT_NAME)
            if use_base and raft_roots:
                _progress(progress,86,'Create and validate unified tree raft')
                raft=_build_unified_raft(raft_roots,cfg)
                stats.raft_qa=tree_mesh.validate_raft(raft,model,bvh,max(0.,float(cfg.get('tree_model_clearance',.45))))
                support=_join_into_support(support,[raft]);raft=None
            ctx=tree_mesh.context(rooted_edges,cfg)
            tree_mesh.triangulate(support)
            if cfg.get('tree_stabilize_stems',False):
                stats.stability['enclosed_void_fill']=tree_stability.fill_tiny_enclosed_voids(model,support,cfg,bvh)
            _progress(progress,90,"Final collision check")
            stats.mesh_qa=tree_mesh.validate_support(model,support,ctx,collider=bvh)
            stats.mesh_qa.update(cap_endpoint_welds=support.get('fdm_tree_cap_endpoint_welds',0),
                cap_max_displacement_mm=support.get('fdm_tree_cap_max_displacement_mm',0.),
                precision_collapses=support.get('fdm_tree_precision_collapses',0),
                zero_surface_fragments=support.get('fdm_tree_zero_surface_fragments',0),
                precision_max_displacement_mm=support.get('fdm_tree_precision_max_displacement_mm',0.),
                cancelled_opposite_triangles=support.get('fdm_tree_cancelled_opposite_triangles',0))
            support[tree_mesh.CONTEXT_KEY]=json.dumps(ctx)
            support['fdm_tree_mesh_qa']=json.dumps(stats.mesh_qa)
            attempts.append(dict(style=variant.get('_stability_style','AUTO'),pass_gate=True))
            stats.stability['geometry_attempts']=attempts
            break
        except Exception as error:
            for owned in (raft,support):
                try:tree_mesh.remove(owned)
                except ReferenceError:pass
            attempts.append(dict(style=variant.get('_stability_style','AUTO'),pass_gate=False,reason=str(error)))
            if variant_index==len(variants)-1:raise
            _log('Stability frame rejected by geometry gate; retrying with certified thickening/partner-post alternative')

    stats.segment_count = len(rooted_edges)
    stats.collision_rejections = dict(bvh.rejections)
    from . import contact_audit
    rooted_contacts=[e.contact_zone[0] for e in rooted_edges if e.kind=='TIP_CONE']
    _progress(progress,92,"Check contact coverage")
    try:
        stats.contact_audit=contact_audit.audit(model,rooted_contacts,float(cfg.get('spacing',1.45)),float(cfg.get('overhang_angle',45.)),direct_bed=bool(cfg.get('_direct_bed',False)))
        stats.required_minima=required_minima.audit(model,support,births,rooted_edges)
    except Exception:
        tree_mesh.remove(support)
        raise
    stats.required_minima.update(enforced=bool(cfg.get('tree_required_minima',False)),planning=required_plan,
        added=sum(p['status']=='added' for p in required_plan))
    if cfg.get('tree_guided_recovery',False):
        from . import layer_islands
        missing={p['id'] for p in stats.required_minima['points'] if not p['covered']}
        records=[p for p in births if p['id'] in missing]
        records += [dict(id=100000+i,point=p) for i,r in enumerate(stats.unresolved_routes) for p in r['contacts']]
        _progress(progress,94,"Check layer islands")
        layer_report=layer_islands.diagnose(bvh.shell_geometry,records,
            layer=float(cfg.get('tree_layer_height',.08)),first=float(cfg.get('tree_first_layer_height',.2)),
            line_width=float(cfg.get('tree_line_width',.22)))
        # Detailed contours belong in diagnostic artifacts, not scene UI data.
        for row in layer_report['points']:
            row.pop('current_contours',None);row.pop('previous_contours',None)
        stats.contact_audit['layer_islands']=layer_report
    stats.contact_audit['required_minima']=stats.required_minima
    stats.stability['support_signature']=required_minima.geometry_signature(support)
    stats.contact_audit['stability']=stats.stability
    support['fdm_tree_contact_audit']=json.dumps(stats.contact_audit)
    support['fdm_tree_route_mode']=cfg.get('tree_route_mode','DIRECT')
    if cfg.get('tree_show_missing',True):
        contact_audit.markers(model,stats.contact_audit,stats.unresolved_routes,stats.rejected_contacts)
    support["fdm_tree_raw_points"] = stats.raw_points
    support["fdm_tree_contacts"] = stats.contacts
    support["fdm_tree_merges"] = stats.merge_count
    support["fdm_tree_rooted_tips"] = stats.rooted_tips
    support["fdm_tree_unresolved_tips"] = stats.unresolved_tips
    support["fdm_tree_rooted_components"] = stats.rooted_components
    support["fdm_tree_segments"] = stats.segment_count
    support["fdm_tree_surface_gap_mm"] = float(cfg.get("tree_model_clearance", 0.45))
    support["fdm_tree_clearance_mode"] = "ADAPTIVE_RADIUS_BOUND_V1"
    support["fdm_tree_collision_rejections"] = str(dict(bvh.rejections))
    support["fdm_tree_tip_profile"] = "COMPACT_CONE_PRINTABLE_DOWN"
    support["fdm_tree_tip_cone_length_mm"] = float(cfg.get("tree_tip_cone_length", 0.32))
    support["fdm_tree_tip_neck_length_mm"] = float(cfg.get("tree_tip_neck_length", 0.35))
    support["fdm_tree_tip_max_angle_deg"] = float(cfg.get("max_neck_angle", 25.0))
    support["fdm_tree_raft_style"] = "UNIFIED_CONVEX_V0" if use_base else "NONE"

    _progress(progress, 96, "Tree support mesh ready")
    _log(
        i18n.format_iface('{v0} contacts, {v1} merges, {v2} rooted tips, {v3} unresolved, {v4} segments', v0=stats.contacts, v1=stats.merge_count, v2=stats.rooted_tips, v3=stats.unresolved_tips, v4=stats.segment_count)
    )
    if hasattr(bvh,'recovery_budget'):
        stats.completion['search_budget']=bvh.recovery_budget.summary()
    return support, stats.as_dict()


def remove_point_source(point_source):
    if point_source is None or point_source.name not in bpy.data.objects:
        return
    data = point_source.data if point_source.type == "MESH" else None
    bpy.data.objects.remove(point_source, do_unlink=True)
    if data is not None and data.users == 0:
        try:
            bpy.data.meshes.remove(data)
        except Exception:
            pass
