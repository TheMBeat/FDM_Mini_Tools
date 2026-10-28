
import bpy
import bmesh
import math
import os
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree
from .presets import PRESETS
from . import tree_support, native_scatter, contacts, orientation


def log(msg):
    print(f"[FDM Mini Tools] {msg}")


def bundled_slasg_path():
    """Return the bundled, tuned single-pass SLASG library path.

    Experimental rooted SLASG variants were removed. The bundled library is
    used only for stable VertexScatter / classic SLASG generation.
    """
    resources = Path(__file__).resolve().parent / "resources"
    return resources / "SLASG_FDM_Mini.blend"


def resolve_slasg_path(configured_path=None):
    """
    Resolve SLASG in this order:
      1. valid user-selected override
      2. bundled tested SLASG resource
      3. None

    A stale custom path does not block the bundled fallback.
    """
    if configured_path:
        try:
            raw = bpy.path.abspath(str(configured_path)).strip()
        except Exception:
            raw = str(configured_path).strip()

        if raw:
            custom = Path(raw).expanduser()
            if custom.is_file():
                return str(custom.resolve())
            log(f"WARN: configured SLASG path not found: {custom}; using bundled library.")

    bundled = bundled_slasg_path()
    if bundled.is_file():
        return str(bundled)

    return None


def frame_object_in_viewports(obj, margin=1.18, additional=()):
    """
    Frame the object and optional comparison pieces in every open 3D viewport.

    Safe no-op in Blender background/headless mode.
    """
    if obj is None or bpy.app.background:
        return False

    try:
        activate(obj)
        for extra in additional:
            if extra is not None:
                extra.select_set(True)
    except Exception:
        return False

    framed = False
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return False

    for window in list(getattr(wm, "windows", [])):
        screen = getattr(window, "screen", None)
        if screen is None:
            continue

        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue

            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            space = area.spaces.active
            if region is None or space is None or space.type != "VIEW_3D":
                continue

            try:
                # VIEW_3D operators need an actual window/area/window-region
                # override. Keeping the override minimal is more robust across
                # Blender point releases.
                with bpy.context.temp_override(
                    window=window,
                    area=area,
                    region=region,
                ):
                    try:
                        bpy.ops.view3d.view_selected(use_all_regions=False)
                    except TypeError:
                        bpy.ops.view3d.view_selected()

                region_3d = getattr(space, "region_3d", None)
                if region_3d is not None:
                    region_3d.view_distance *= max(1.0, float(margin))

                area.tag_redraw()
                framed = True
            except Exception as exc:
                log(f"WARN: could not frame MINI in a 3D viewport: {exc}")

    return framed


def _progress(progress, percent, step):
    if progress is None:
        return
    try:
        progress(float(percent), str(step))
    except Exception:
        pass


def clear_scene(purge=False):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    if purge:
        try:
            for _ in range(3):
                bpy.ops.outliner.orphans_purge(
                    do_local_ids=True, do_linked_ids=True, do_recursive=True
                )
        except Exception:
            pass


def configure_mm_units():
    s = bpy.context.scene
    s.unit_settings.system = "METRIC"
    s.unit_settings.length_unit = "MILLIMETERS"
    s.unit_settings.scale_length = 0.001


def deselect_all():
    for obj in bpy.context.scene.objects:
        obj.select_set(False)


def activate(obj):
    deselect_all()
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def import_stl(filepath):
    filepath = str(filepath)
    before = set(bpy.data.objects.keys())

    if hasattr(bpy.ops.wm, "stl_import"):
        bpy.ops.wm.stl_import(filepath=filepath)
    elif hasattr(bpy.ops.import_mesh, "stl"):
        bpy.ops.import_mesh.stl(filepath=filepath)
    else:
        raise RuntimeError("Blender STL importer not available.")

    objects = [
        o for o in bpy.context.scene.objects
        if o.name not in before and o.type == "MESH"
    ]
    if not objects:
        raise RuntimeError("STL import created no mesh.")

    deselect_all()
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    if len(objects) > 1:
        bpy.ops.object.join()

    obj = bpy.context.view_layer.objects.active
    obj.name = "MINI"
    apply_transforms(obj)
    frame_object_in_viewports(obj)
    return obj


def apply_transforms(obj):
    activate(obj)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)


def cleanup_mesh(obj, merge=0.002):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    # A proximity weld can collapse a thin closed feature or join separate
    # shells. The source mesh stays untouched until this transaction commits.
    was_closed = bool(bm.faces) and all(e.is_manifold and e.is_contiguous for e in bm.edges)
    if bm.verts and merge > 0:
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=merge)
        if was_closed and (not bm.faces or any(
            not e.is_manifold or not e.is_contiguous for e in bm.edges
        )):
            bm.free()
            bm = bmesh.new()
            bm.from_mesh(obj.data)
            log("Cleanup: proximity weld rejected; preserving closed source topology")
    loose = [v for v in bm.verts if not v.link_edges]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bm.normal_update()
    if bm.faces:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


# ----------------------------------------------------------------------
# FDM detail enhancement
# ----------------------------------------------------------------------

OPT = {
    "SAFE": dict(
        cleanup=True,
        detail=True,
        smooth=False,
        remesh=False,
        retriangulate=True,
        merge=0.002,
        gmin=0.018,
        gmax=0.22,
        gdepth=0.10,
        rmin=0.018,
        rmax=0.22,
        rheight=0.05,
        widen=1,
        smooth_factor=0.0,
        smooth_iterations=0,
        voxel_size=None,
        quad_method="BEAUTY",
        ngon_method="BEAUTY",
    ),
    "BALANCED": dict(
        cleanup=True,
        detail=True,
        smooth=True,
        remesh=True,
        retriangulate=True,
        merge=0.002,
        gmin=0.015,
        gmax=0.28,
        gdepth=0.16,
        rmin=0.015,
        rmax=0.28,
        rheight=0.09,
        widen=1,
        smooth_factor=0.02,
        smooth_iterations=1,
        voxel_size=0.06,
        quad_method="BEAUTY",
        ngon_method="BEAUTY",
    ),
    "STRONG": dict(
        cleanup=True,
        detail=True,
        smooth=True,
        remesh=True,
        retriangulate=True,
        merge=0.003,
        gmin=0.012,
        gmax=0.32,
        gdepth=0.22,
        rmin=0.012,
        rmax=0.32,
        rheight=0.13,
        widen=2,
        smooth_factor=0.03,
        smooth_iterations=1,
        voxel_size=0.05,
        quad_method="BEAUTY",
        ngon_method="BEAUTY",
    ),
}


def _neighbors(bm):
    return {
        v.index: [e.other_vert(v).index for e in v.link_edges]
        for v in bm.verts
    }


def _signals(bm, neigh):
    pos = [v.co.copy() for v in bm.verts]
    nor = [v.normal.normalized() if v.normal.length else Vector((0, 0, 1)) for v in bm.verts]
    out = [0.0] * len(bm.verts)
    for v in bm.verts:
        ns = neigh[v.index]
        if not ns:
            continue
        avg = Vector((0.0, 0.0, 0.0))
        for i in ns:
            avg += pos[i]
        avg /= len(ns)
        out[v.index] = (pos[v.index] - avg).dot(nor[v.index])
    return out


def _grow(weights, neigh, rings, decay=0.55):
    result = list(weights)
    frontier = {i for i, w in enumerate(weights) if w > 0}
    for ring in range(rings):
        nxt = set()
        scale = decay ** (ring + 1)
        for idx in frontier:
            for n in neigh[idx]:
                candidate = result[idx] * scale
                if candidate > result[n]:
                    result[n] = candidate
                    nxt.add(n)
        frontier = nxt
        if not frontier:
            break
    return result


def enhance_details(
    obj,
    strength="BALANCED",
    *,
    groove_depth=None,
    ridge_height=None,
    detection_min=None,
    detection_max=None,
    widen_rings=None,
):
    cfg = dict(OPT.get(strength, OPT["BALANCED"]))
    if groove_depth is not None:
        cfg["gdepth"] = groove_depth
    if ridge_height is not None:
        cfg["rheight"] = ridge_height
    if detection_min is not None:
        cfg["gmin"] = cfg["rmin"] = detection_min
    if detection_max is not None:
        cfg["gmax"] = cfg["rmax"] = detection_max
    if widen_rings is not None:
        cfg["widen"] = widen_rings

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.normal_update()
    neigh = _neighbors(bm)
    sig = _signals(bm, neigh)

    groove = [0.0] * len(bm.verts)
    ridge = [0.0] * len(bm.verts)

    for i, s in enumerate(sig):
        mag = abs(s)
        if s < -cfg["gmin"] and mag <= cfg["gmax"]:
            groove[i] = max(
                0.15,
                min(
                    1.0,
                    (mag - cfg["gmin"]) /
                    max(cfg["gmax"] - cfg["gmin"], 1e-6),
                ),
            )
        elif s > cfg["rmin"] and mag <= cfg["rmax"]:
            ridge[i] = max(
                0.15,
                min(
                    1.0,
                    (mag - cfg["rmin"]) /
                    max(cfg["rmax"] - cfg["rmin"], 1e-6),
                ),
            )

    groove = _grow(groove, neigh, cfg["widen"])
    ridge = _grow(ridge, neigh, cfg["widen"], 0.5)

    for v in bm.verts:
        n = v.normal.normalized() if v.normal.length else None
        if n is None:
            continue
        gw, rw = groove[v.index], ridge[v.index]
        if gw > rw and gw > 0:
            v.co -= n * (cfg["gdepth"] * gw)
        elif rw > 0:
            v.co += n * (cfg["rheight"] * rw)

    bm.normal_update()
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def surface_smooth(obj, factor=0.02, iterations=1):
    if factor <= 0 or iterations <= 0:
        return
    activate(obj)
    mod = obj.modifiers.new(name="FDM_Surface_Smooth", type="SMOOTH")
    mod.factor = factor
    mod.iterations = iterations
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.context.view_layer.update()


def _closed_mesh_surface(mesh):
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        return bool(bm.faces) and all(e.is_manifold and e.is_contiguous for e in bm.edges)
    finally:
        bm.free()


def voxel_remesh(obj, voxel_size=0.06):
    if voxel_size is None or voxel_size <= 0:
        return
    # Remeshing is optional preparation, never permission to damage a closed
    # input. Work on a copy so both failure and rejected output are reversible.
    if not _closed_mesh_surface(obj.data):
        return _voxel_remesh_unchecked(obj, voxel_size)
    original = obj.data
    candidate = original.copy()
    obj.data = candidate
    accepted = False
    try:
        _voxel_remesh_unchecked(obj, voxel_size)
        accepted = _closed_mesh_surface(obj.data)
        if not accepted:
            warning = "Voxel Remesh verworfen: offene Geometrie; vorheriges geschlossenes Mesh beibehalten"
            obj['fdm_preparation_warning'] = warning
            log(warning)
    finally:
        if not accepted:
            obj.data = original
            if candidate.users == 0:
                bpy.data.meshes.remove(candidate)
        elif original.users == 0:
            bpy.data.meshes.remove(original)
        bpy.context.view_layer.update()


def _voxel_remesh_unchecked(obj, voxel_size=0.06):
    if voxel_size is None or voxel_size <= 0:
        return

    activate(obj)

    # Blender's Object.voxel_remesh API is preferred in current versions.
    if hasattr(obj.data, "remesh_voxel_size"):
        obj.data.remesh_voxel_size = voxel_size
        if hasattr(obj.data, "remesh_voxel_adaptivity"):
            obj.data.remesh_voxel_adaptivity = 0.0

        for attr, value in (
            ("use_remesh_fix_poles", True),
            ("use_remesh_preserve_volume", True),
            ("use_remesh_preserve_attributes", False),
        ):
            if hasattr(obj.data, attr):
                setattr(obj.data, attr, value)

        bpy.ops.object.voxel_remesh()
        bpy.context.view_layer.update()
        return

    raise RuntimeError("Voxel Remesh is unavailable in this Blender build.")


def retriangulate(
    obj,
    quad_method="BEAUTY",
    ngon_method="BEAUTY",
):
    activate(obj)

    # Use BMesh so this works headless and does not depend on Edit Mode.
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()

    if bm.faces:
        bmesh.ops.triangulate(
            bm,
            faces=list(bm.faces),
            quad_method=quad_method,
            ngon_method=ngon_method,
        )

    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def optimization_config_from_props(props):
    """
    Scene/UI settings are authoritative. The preset is a starting point only.
    """
    return {
        "cleanup": props.do_cleanup,
        "detail": props.do_detail_enhancement,
        "smooth": props.do_surface_smooth,
        "remesh": props.do_voxel_remesh,
        "retriangulate": props.do_retriangulate,
        "merge": props.cleanup_merge_distance,
        "gdepth": props.groove_depth,
        "rheight": props.ridge_height,
        "gmin": props.detail_detection_min,
        "gmax": props.detail_detection_max,
        "widen": props.detail_widen_rings,
        "smooth_factor": props.smooth_factor,
        "smooth_iterations": props.smooth_iterations,
        "voxel_size": props.voxel_size,
        "quad_method": props.triangulate_quad_method,
        "ngon_method": props.triangulate_ngon_method,
    }


def optimization_config_from_preset(
    strength="BALANCED",
    *,
    cleanup=None,
    detail=None,
    smooth=None,
    remesh=None,
    retriangulate=None,
    merge=None,
    groove_depth=None,
    ridge_height=None,
    detection_min=None,
    detection_max=None,
    widen_rings=None,
    smooth_factor=None,
    smooth_iterations=None,
    voxel_size=None,
    quad_method=None,
    ngon_method=None,
):
    cfg = dict(OPT.get(strength, OPT["BALANCED"]))

    overrides = {
        "cleanup": cleanup,
        "detail": detail,
        "smooth": smooth,
        "remesh": remesh,
        "retriangulate": retriangulate,
        "merge": merge,
        "gdepth": groove_depth,
        "rheight": ridge_height,
        "gmin": detection_min,
        "gmax": detection_max,
        "widen": widen_rings,
        "smooth_factor": smooth_factor,
        "smooth_iterations": smooth_iterations,
        "voxel_size": voxel_size,
        "quad_method": quad_method,
        "ngon_method": ngon_method,
    }

    for key, value in overrides.items():
        if value is not None:
            cfg[key] = value

    # Keep ridge thresholds symmetric with groove thresholds when overridden.
    cfg["rmin"] = cfg["gmin"]
    cfg["rmax"] = cfg["gmax"]
    return cfg


def run_optimization_pipeline(obj, cfg, progress=None, start=10.0, end=45.0):
    """
    Fixed pipeline order:
      Cleanup -> Detail Enhancement -> Smooth -> Voxel Remesh -> Retriangulate
    """
    span = max(end - start, 1.0)
    cursor = start

    if cfg.get("cleanup", True):
        _progress(progress, cursor, "Mesh Cleanup")
        log("Optimization: Mesh Cleanup")
        cleanup_mesh(obj, merge=cfg.get("merge", 0.002))
        cursor += span * 0.12

    if cfg.get("detail", True):
        _progress(progress, cursor, "Detail Enhancement")
        log("Optimization: Detail Enhancement")
        enhance_details(
            obj,
            "BALANCED",
            groove_depth=cfg.get("gdepth"),
            ridge_height=cfg.get("rheight"),
            detection_min=cfg.get("gmin"),
            detection_max=cfg.get("gmax"),
            widen_rings=cfg.get("widen"),
        )
        cursor += span * 0.24

    if cfg.get("smooth", False):
        _progress(progress, cursor, "Surface Smooth")
        log("Optimization: Surface Smooth")
        surface_smooth(
            obj,
            factor=cfg.get("smooth_factor", 0.02),
            iterations=cfg.get("smooth_iterations", 1),
        )
        cursor += span * 0.10

    if cfg.get("remesh", False):
        _progress(progress, cursor, "Voxel Remesh")
        log("Optimization: Voxel Remesh")
        voxel_remesh(
            obj,
            voxel_size=cfg.get("voxel_size", 0.06),
        )

        # Remesh can create tiny duplicate/degenerate geometry. A conservative
        # cleanup here is useful but is deliberately not a second user-visible
        # pipeline stage.
        cleanup_mesh(obj, merge=min(cfg.get("merge", 0.002), 0.002))
        cursor += span * 0.42

    if cfg.get("retriangulate", True):
        _progress(progress, cursor, "Retriangulate")
        log("Optimization: Retriangulate")
        retriangulate(
            obj,
            quad_method=cfg.get("quad_method", "BEAUTY"),
            ngon_method=cfg.get("ngon_method", "BEAUTY"),
        )

    _progress(progress, end, "Optimization complete")


# ----------------------------------------------------------------------
# Orientation
# ----------------------------------------------------------------------

def _world_bbox(obj):
    return [obj.matrix_world @ v.co for v in obj.data.vertices]


def bounds(obj):
    pts = _world_bbox(obj)
    return (
        min(p.x for p in pts), max(p.x for p in pts),
        min(p.y for p in pts), max(p.y for p in pts),
        min(p.z for p in pts), max(p.z for p in pts),
    )


def _place_lowest_at(obj, z=3.0):
    xmin, xmax, ymin, ymax, zmin, zmax = bounds(obj)
    obj.location.x -= (xmin + xmax) / 2
    obj.location.y -= (ymin + ymax) / 2
    bpy.context.view_layer.update()
    zmin = bounds(obj)[4]
    obj.location.z += z - zmin
    bpy.context.view_layer.update()


def orient_fixed(obj, x_deg=35.0, y_deg=7.0, lift=3.0):
    activate(obj)
    bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")
    obj.rotation_euler = (math.radians(x_deg), math.radians(y_deg), 0.0)
    rot = obj.rotation_euler.to_matrix()
    _remember_orientation_basis(obj, rot)
    if obj.get(orientation.FRONT_KEY) is not None:
        obj[orientation.FRONT_KEY] = list((rot @ Vector(obj[orientation.FRONT_KEY])).normalized())
    apply_transforms(obj)
    _place_lowest_at(obj, lift)
    frame_object_in_viewports(obj)
    return x_deg, y_deg, 0.0


def _orientation_score(obj, x_deg, y_deg, overhang_deg=45.0):
    # Score downward-facing unsupported surface area and the height at which
    # that area occurs. Lower is better. This is deliberately geometry-only.
    rx, ry = math.radians(x_deg), math.radians(y_deg)
    from mathutils import Matrix
    rot = Matrix.Rotation(ry, 4, "Y") @ Matrix.Rotation(rx, 4, "X")
    threshold = -math.cos(math.radians(overhang_deg))
    score = 0.0
    total_down = 0.0
    for poly in obj.data.polygons:
        n = rot.to_3x3() @ poly.normal
        if n.z < threshold:
            area = poly.area
            center = rot @ poly.center
            height_weight = 1.0 + max(center.z, 0.0) * 0.01
            score += area * height_weight * (1.0 + abs(n.z))
            total_down += area
    # Gentle penalty for very steep poses.
    score *= 1.0 + (abs(x_deg) + abs(y_deg)) * 0.0015
    return score, total_down


def _remember_orientation_basis(obj, rot):
    stored = obj.get('fdm_orientation_source_basis')
    old = Matrix([stored[i:i+3] for i in (0,3,6)]) if stored else Matrix.Identity(3)
    basis = rot @ old
    obj['fdm_orientation_source_basis'] = [v for row in basis for v in row]


def orient_scored(obj, lift=3.0, overhang_deg=45.0, front_mode='AUTO'):
    import json
    activate(obj)
    stored = obj.get(orientation.FRONT_KEY)
    if stored is not None:
        obj[orientation.FRONT_KEY] = list((obj.matrix_world.to_3x3() @ Vector(stored)).normalized())
    _remember_orientation_basis(obj, obj.rotation_euler.to_matrix())
    apply_transforms(obj)
    # Search from the asset frame on repeated clicks, rather than accumulating
    # another back tilt on an already baked pose. Keep the captured front in
    # the same frame so manual and automatic modes remain interchangeable.
    basis = obj['fdm_orientation_source_basis']
    inverse = Matrix([basis[i:i+3] for i in (0,3,6)]).inverted_safe()
    obj.data.transform(inverse.to_4x4())
    obj.data.update()
    if obj.get(orientation.FRONT_KEY) is not None:
        obj[orientation.FRONT_KEY] = list((inverse @ Vector(obj[orientation.FRONT_KEY])).normalized())
    obj['fdm_orientation_source_basis'] = [v for row in Matrix.Identity(3) for v in row]
    rot, report = orientation.choose(obj, overhang_deg, front_mode)
    bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
    obj.rotation_euler = rot.to_euler('XYZ')
    _remember_orientation_basis(obj, rot)
    if obj.get(orientation.FRONT_KEY) is not None:
        obj[orientation.FRONT_KEY] = list((rot @ Vector(obj[orientation.FRONT_KEY])).normalized())
    apply_transforms(obj)
    _place_lowest_at(obj, lift)
    frame_object_in_viewports(obj)
    obj['fdm_orientation_report'] = json.dumps(report)
    return tuple(math.degrees(a) for a in rot.to_euler('XYZ'))


# ----------------------------------------------------------------------
# SLASG
# ----------------------------------------------------------------------

def _norm(s):
    return "".join(c.lower() for c in str(s) if c.isalnum())


def _panel_name(sock):
    p = getattr(sock, "parent", None)
    return getattr(p, "name", "") if p else ""


def _input_sockets(group):
    interface = getattr(group, "interface", None)
    if not interface:
        return []
    return [
        item for item in getattr(interface, "items_tree", [])
        if getattr(item, "item_type", None) == "SOCKET"
        and getattr(item, "in_out", None) == "INPUT"
    ]


def _find_socket(mod, aliases, panel=None):
    aliases = [_norm(a) for a in aliases]
    panel_n = _norm(panel) if panel else None
    ranked = []
    for sock in _input_sockets(mod.node_group):
        sn = _norm(sock.name)
        pn = _norm(_panel_name(sock))
        score = 0
        if sn in aliases:
            score = 100
        elif any(a and a in sn for a in aliases):
            score = 70
        elif any(sn and sn in a for a in aliases):
            score = 50
        if not score:
            continue
        if panel_n:
            if pn == panel_n:
                score += 40
            elif panel_n in pn or pn in panel_n:
                score += 15
            else:
                score -= 30
        ranked.append((score, sock))
    if not ranked and panel:
        for sock in _input_sockets(mod.node_group):
            if _norm(_panel_name(sock)) == panel_n and _norm(sock.name) == "enable":
                return sock
    return max(ranked, key=lambda x: x[0])[1] if ranked else None


def _modifier_input_property(mod, identifier):
    """
    Blender 5.2+ exposes Geometry Nodes modifier inputs as RNA properties:
        mod.properties.inputs.<identifier>.value
    Blender <= 5.1 used custom ID properties:
        mod[identifier]
    """
    props = getattr(mod, "properties", None)
    inputs = getattr(props, "inputs", None) if props is not None else None

    if inputs is not None:
        try:
            return getattr(inputs, identifier)
        except Exception:
            pass
        try:
            return inputs.path_resolve(identifier)
        except Exception:
            pass

    return None


def _set(mod, aliases, value, panel=None, required=False, angle=False, percent=False):
    sock = _find_socket(mod, aliases, panel)
    if sock is None:
        if required:
            raise RuntimeError(f"SLASG input not found: {panel}/{aliases}")
        return False

    v = value
    if angle:
        v = math.radians(float(v))

    if percent:
        maxv = getattr(sock, "max_value", None)
        if isinstance(maxv, (int, float)) and maxv > 2:
            v = float(v) * 100.0

    identifier = sock.identifier

    # Blender 5.2+ RNA API.
    runtime_prop = _modifier_input_property(mod, identifier)
    if runtime_prop is not None:
        try:
            runtime_prop.value = v
            return True
        except Exception as exc:
            if required:
                raise RuntimeError(
                    f"Could not set SLASG input {panel}/{sock.name} "
                    f"({identifier}) through Blender 5.2 RNA API: {exc}"
                ) from exc
            log(
                f"WARN: failed to set {panel}/{sock.name} "
                f"({identifier}) through Blender 5.2 RNA API: {exc}"
            )
            return False

    # Blender <= 5.1 fallback.
    try:
        mod[identifier] = v
        return True
    except Exception as exc:
        if required:
            raise RuntimeError(
                f"Could not set SLASG input {panel}/{sock.name} "
                f"({identifier}): {exc}"
            ) from exc
        log(f"WARN: failed to set {panel}/{sock.name} ({identifier}): {exc}")
        return False



def _get(mod, aliases, panel=None):
    sock = _find_socket(mod, aliases, panel)
    if sock is None:
        return None

    identifier = sock.identifier
    runtime_prop = _modifier_input_property(mod, identifier)

    if runtime_prop is not None:
        try:
            return runtime_prop.value
        except Exception:
            pass

    try:
        return mod[identifier]
    except Exception:
        return None


def _set_menu_choice(mod, aliases, wanted_name, panel=None, required=False):
    """
    Set a Geometry Nodes menu/enum input by visible label if possible.

    Blender versions/node-socket implementations differ: some expose an enum
    identifier, others an integer menu index. Try enum metadata first, then a
    few safe representations.
    """
    sock = _find_socket(mod, aliases, panel)
    if sock is None:
        if required:
            raise RuntimeError(f"SLASG menu input not found: {panel}/{aliases}")
        return False

    identifier = sock.identifier
    runtime_prop = _modifier_input_property(mod, identifier)

    candidates = []
    wanted_norm = _norm(wanted_name)

    if runtime_prop is not None:
        try:
            value_prop = runtime_prop.bl_rna.properties.get("value")
            enum_items = getattr(value_prop, "enum_items", None)
            if enum_items:
                for item in enum_items:
                    if _norm(item.name) == wanted_norm or _norm(item.identifier) == wanted_norm:
                        candidates.append(item.identifier)
        except Exception:
            pass

    # Common GN menu representations.
    candidates.extend([wanted_name.upper(), wanted_name, 0])

    last_exc = None
    for value in candidates:
        try:
            if runtime_prop is not None:
                runtime_prop.value = value
            else:
                mod[identifier] = value
            return True
        except Exception as exc:
            last_exc = exc

    if required:
        raise RuntimeError(
            f"Could not set SLASG menu {panel}/{sock.name} to {wanted_name}: {last_exc}"
        )
    return False


def _verify_target_object(mod, model, label):
    actual = _get(mod, ["Target Object"], "General")

    same_object = actual is model or actual == model
    if not same_object:
        try:
            same_object = (
                actual is not None
                and actual.as_pointer() == model.as_pointer()
            )
        except Exception:
            same_object = False

    if not same_object:
        actual_name = getattr(actual, "name", repr(actual))
        raise RuntimeError(
            f"{label} Target Object verification failed: "
            f"got {actual_name}, expected {model.name}"
        )

    target_type = _get(mod, ["Target Type", "Taget Type"], "General")

    # Menu sockets may read back as an enum identifier/name or as index 0.
    if target_type is not None:
        valid_type = (
            (isinstance(target_type, str) and _norm(target_type) == "object")
            or target_type == 0
        )
        if not valid_type:
            raise RuntimeError(
                f"{label} Target/Taget Type verification failed: "
                f"got {target_type!r}, expected Object"
            )

    log(
        f"{label}: Target Type={target_type!r}, "
        f"Target Object={model.name}"
    )


def append_slasg(blend_path=None):
    blend_path = resolve_slasg_path(blend_path)
    if not blend_path:
        raise RuntimeError(
            "SLASG_MilliMetreUnit.blend not found. "
            "Reinstall FDM Mini Tools or select a custom SLASG library."
        )
    blend_path = str(Path(blend_path).expanduser().resolve())
    before_objects = set(bpy.data.objects.keys())
    with bpy.data.libraries.load(blend_path, link=False) as (src, dst):
        dst.node_groups = list(src.node_groups)
        dst.objects = list(src.objects)

    appended = [o for n, o in bpy.data.objects.items() if n not in before_objects]
    for obj in appended:
        if obj.name not in bpy.context.scene.objects:
            try:
                bpy.context.collection.objects.link(obj)
            except RuntimeError:
                pass

    support = None
    generator = None
    for obj in appended:
        for mod in obj.modifiers:
            ng = getattr(mod, "node_group", None)
            if ng and "SLASG_SupportGenerator" in ng.name:
                support, generator = obj, mod
                break
        if support:
            break

    support_group = next(
        (ng for ng in bpy.data.node_groups if "SLASG_SupportGenerator" in ng.name),
        None
    )
    scatter_group = next(
        (ng for ng in bpy.data.node_groups if "SLASG_VertexScatter" in ng.name),
        None
    )
    if support_group is None or scatter_group is None:
        raise RuntimeError("SLASG_VertexScatter / SLASG_SupportGenerator not found in library.")

    if support is None:
        mesh = bpy.data.meshes.new("SUPPORT_POINTS")
        support = bpy.data.objects.new("SUPPORTS", mesh)
        bpy.context.collection.objects.link(support)
        generator = support.modifiers.new("SLASG Support Generator", "NODES")
        generator.node_group = support_group

    support.name = "SUPPORTS"

    # Prevent the imported SupportGenerator from evaluating its library
    # defaults (e.g. Suzanne.001) while we replace/configure its inputs.
    generator.show_viewport = False
    generator.show_render = False

    # IMPORTANT:
    # The SLASG library template can contain pre-existing support-point mesh
    # geometry. If kept, SLASG_SupportGenerator generates that demo/template
    # forest in addition to the new points created for the current MINI.
    #
    # Preserve the imported SUPPORTS object, its Geometry Nodes modifier,
    # modifier values and any library-specific object state, but replace ONLY
    # its source mesh with a fresh empty mesh.
    old_mesh = support.data if support.type == "MESH" else None
    clean_mesh = bpy.data.meshes.new("SUPPORT_POINTS")
    support.data = clean_mesh

    if old_mesh is not None and old_mesh.users == 0:
        try:
            bpy.data.meshes.remove(old_mesh)
        except Exception:
            pass

    log(
        "SLASG template SUPPORTS object retained; "
        "pre-existing template point mesh cleared."
    )

    scatter = next(
        (m for m in support.modifiers
         if getattr(m, "node_group", None)
         and "SLASG_VertexScatter" in m.node_group.name),
        None
    )
    if scatter is None:
        scatter = support.modifiers.new("SLASG Auto Scatter", "NODES")
        # Disable BEFORE assigning the node group so Blender cannot evaluate
        # the group's default Target Object (Suzanne.001).
        scatter.show_viewport = False
        scatter.show_render = False
        scatter.node_group = scatter_group
    else:
        scatter.show_viewport = False
        scatter.show_render = False

    # Keep Generator disabled until Scatter has been configured and baked.
    generator.show_viewport = False
    generator.show_render = False

    # Scatter must run before support geometry generation.
    while list(support.modifiers).index(scatter) > list(support.modifiers).index(generator):
        activate(support)
        bpy.ops.object.modifier_move_up(modifier=scatter.name)

    # Hide all other imported helper/template objects.
    for obj in appended:
        if obj != support:
            obj.hide_viewport = True
            obj.hide_render = True

    return support, scatter, generator


def configure_slasg(model, support, scatter, generator, cfg):
    """
    Configure both SLASG node modifiers while they are disabled.

    Critical ordering:
      1. force Target Type = Object
      2. clear imported/default Target Object
      3. set Target Object = MINI
      4. configure remaining inputs
      5. read back and verify target pointers
      6. only then enable VertexScatter
      7. keep SupportGenerator disabled until scatter is baked
    """
    scatter.show_viewport = False
    scatter.show_render = False
    generator.show_viewport = False
    generator.show_render = False

    # ------------------------------------------------------------------
    # Scatter target first. The library default can be Suzanne.001.
    # ------------------------------------------------------------------
    _set_menu_choice(
        scatter,
        ["Target Type", "Taget Type"],
        "Object",
        "General",
        required=True,
    )

    # Explicitly clear any imported/default pointer before assigning MINI.
    _set(scatter, ["Target Object"], None, "General", required=True)
    bpy.context.view_layer.update()

    _set(scatter, ["Target Object"], model, "General", required=True)
    _set(scatter, ["Spacing"], cfg["spacing"], "General", required=True)
    _set(scatter, ["Safe Distance"], cfg["safe_distance"], "General")
    _set(scatter, ["Angle"], cfg["overhang_angle"], "General", angle=True)
    _set(scatter, ["Enable", "Facing Down"], True, "Facing Down")
    _set(
        scatter,
        ["Enable", "Topological Island"],
        cfg["use_islands"],
        "Topological Island",
    )
    _set(scatter, ["Ridge Angle"], 50.0, "Topological Island", angle=True)
    _set(scatter, ["Vertical"], True, "Topological Island")
    _set(scatter, ["Enable", "Auto Tree"], cfg["use_trees"], "Auto Tree")
    _set(
        scatter,
        ["Merge Distance"],
        cfg["tree_merge_distance"],
        "Auto Tree",
    )
    _set(scatter, ["Branch Descent"], cfg["branch_descent"], "Auto Tree")

    # ------------------------------------------------------------------
    # Generator target: configure the same way and leave disabled.
    # ------------------------------------------------------------------
    _set_menu_choice(
        generator,
        ["Target Type", "Taget Type"],
        "Object",
        "General",
        required=True,
    )
    _set(generator, ["Target Object"], None, "General", required=True)
    bpy.context.view_layer.update()

    _set(generator, ["Target Object"], model, "General", required=True)
    _set(generator, ["Auto Snap"], False, "General")
    _set(generator, ["Resolution"], cfg["resolution"], "Support Shape")
    _set(
        generator,
        ["Max Neck Angle"],
        cfg["max_neck_angle"],
        "Support Shape",
        angle=True,
    )
    _set(
        generator,
        ["Touch Diameter"],
        cfg["touch_diameter"],
        "Support Shape",
        required=True,
    )
    _set(generator, ["Touch Depth"], cfg["touch_depth"], "Support Shape")
    _set(
        generator,
        ["Neck Diameter"],
        cfg["neck_diameter"],
        "Support Shape",
        required=True,
    )
    _set(generator, ["Neck Length"], cfg["neck_length"], "Support Shape")
    _set(
        generator,
        ["Pillar Diameter"],
        cfg["pillar_diameter"],
        "Support Shape",
        required=True,
    )
    _set(generator, ["Base Diameter"], cfg["base_diameter"], "Support Shape")
    _set(generator, ["Base Height"], cfg["base_height"], "Support Shape")
    _set(
        generator,
        ["Tree Section Increment"],
        0.30,
        "Support Shape",
        percent=True,
    )

    _set(generator, ["Enable", "Truss"], cfg["use_trusses"], "Truss")
    if cfg["use_trusses"]:
        _set(
            generator,
            ["Distance Limit"],
            cfg["truss_distance_limit"],
            "Truss",
        )
        _set(
            generator,
            ["Minimum Height"],
            cfg["truss_minimum_height"],
            "Truss",
        )
        _set(generator, ["Top Spacing"], cfg["truss_top_spacing"], "Truss")
        _set(
            generator,
            ["Angle"],
            cfg["truss_angle"],
            "Truss",
            angle=True,
        )
        _set(generator, ["Spacing"], cfg["truss_spacing"], "Truss")
        _set(generator, ["Diameter"], cfg["truss_diameter"], "Truss")

    _set(generator, ["Enable", "Raft"], cfg["use_raft"], "Raft")
    if cfg["use_raft"]:
        _set(generator, ["Voxel Resolution"], 128, "Raft")
        _set(
            generator,
            ["Expand Width"],
            cfg["raft_expand_width"],
            "Raft",
        )
        _set(
            generator,
            ["Floor Thickness"],
            cfg["raft_floor_thickness"],
            "Raft",
        )
        _set(
            generator,
            ["Wall Height"],
            cfg["raft_wall_height"],
            "Raft",
        )
        _set(
            generator,
            ["Wall Thickness"],
            cfg["raft_wall_thickness"],
            "Raft",
        )
        _set(generator, ["Wall Angle"], 45.0, "Raft", angle=True)

    # ------------------------------------------------------------------
    # Force a dependency-graph update while both modifiers remain disabled,
    # then verify that Blender actually stored MINI in both target sockets.
    # ------------------------------------------------------------------
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()

    _verify_target_object(scatter, model, "SLASG VertexScatter")
    _verify_target_object(generator, model, "SLASG SupportGenerator")

    # Enable only VertexScatter now. Generator stays OFF until bake_scatter().
    scatter.show_viewport = True
    scatter.show_render = False
    generator.show_viewport = False
    generator.show_render = False

    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()

    # Request an evaluated object once to force Geometry Nodes evaluation with
    # the verified MINI target before modifier_apply is called.
    support.evaluated_get(depsgraph)

    log("SLASG VertexScatter enabled with verified MINI target.")



def bake_scatter(support, scatter, *, enable_generator=True):
    activate(support)

    # Scatter has already been configured and target-verified. Apply it while
    # the SupportGenerator is still disabled so no library default state can
    # participate in this evaluation.
    bpy.ops.object.modifier_apply(modifier=scatter.name)
    bpy.context.view_layer.update()

    generator = next(
        (
            mod for mod in support.modifiers
            if getattr(mod, "node_group", None)
            and "SLASG_SupportGenerator" in mod.node_group.name
        ),
        None,
    )

    if generator is None:
        raise RuntimeError("SLASG SupportGenerator modifier missing after scatter bake.")

    if enable_generator:
        generator.show_viewport = True
        generator.show_render = True
        log("SLASG scatter baked; SupportGenerator enabled.")
    else:
        # FDM Tree mode consumes only the baked contact-point mesh. The SLASG
        # SupportGenerator must stay disabled so its line/tree/root logic never
        # participates in the experimental tree strategy.
        generator.show_viewport = False
        generator.show_render = False
        log("SLASG scatter baked as contact points; SupportGenerator remains disabled.")

    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()


def _world_bvh_from_object(obj):
    deps = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(deps)
    mesh = eval_obj.to_mesh()
    try:
        verts = [eval_obj.matrix_world @ v.co for v in mesh.vertices]
        polys = [tuple(p.vertices) for p in mesh.polygons]
        tree = BVHTree.FromPolygons(verts, polys, all_triangles=False)
    finally:
        eval_obj.to_mesh_clear()
    return tree


def validate_and_fix_support_contacts(
    model,
    support,
    *,
    tolerance=0.04,
    overlap=0.12,
    max_extension=0.30,
    auto_fix=True,
    min_tip_z=1.0,
):
    """
    Validate baked SLASG scatter/tree endpoints against the final MINI surface.

    We work on the baked SUPPORTS point/tree mesh *before* the live
    SLASG_SupportGenerator modifier creates cylinders/tips.

    Candidate vertices are endpoints (degree <= 1) above the build plate.
    If a candidate is within max_extension of the MINI surface, it is treated
    as a potential support tip. Valid contacts are deliberately moved slightly
    into the model by `overlap`; small gaps are closed automatically.

    This keeps SLASG's generated support geometry coherent and avoids adding
    arbitrary post-process cylinders.
    """
    if model is None or support is None:
        return {
            "candidates": 0,
            "valid": 0,
            "gaps": 0,
            "fixed": 0,
            "unresolved": 0,
        }

    bpy.context.view_layer.update()
    bvh = _world_bvh_from_object(model)

    mesh = support.data
    degree = [0] * len(mesh.vertices)
    for e in mesh.edges:
        degree[e.vertices[0]] += 1
        degree[e.vertices[1]] += 1

    # If scatter output is a pure point cloud, every point is a candidate.
    has_edges = len(mesh.edges) > 0

    inv = support.matrix_world.inverted()

    result = {
        "candidates": 0,
        "valid": 0,
        "gaps": 0,
        "fixed": 0,
        "unresolved": 0,
    }

    for v in mesh.vertices:
        if has_edges and degree[v.index] > 1:
            continue

        world = support.matrix_world @ v.co
        if world.z <= min_tip_z:
            # Bottom/base endpoints are not support/model contact tips.
            continue

        nearest = bvh.find_nearest(world)
        if nearest is None:
            continue

        surface_co, surface_normal, face_index, distance = nearest
        if surface_co is None or distance is None:
            continue

        # Only nearby endpoints are plausible model-contact tips.
        # Anything farther away is likely a tree/base endpoint.
        if distance > max_extension:
            continue

        result["candidates"] += 1

        if distance <= tolerance:
            result["valid"] += 1
        else:
            result["gaps"] += 1

        if not auto_fix:
            if distance > tolerance:
                result["unresolved"] += 1
            continue

        normal = surface_normal.normalized() if surface_normal.length else Vector((0, 0, 1))
        # Move intentionally *inside* the final MINI surface to create real
        # volumetric overlap that survives STL quantization and slicer layers.
        target_world = surface_co - normal * overlap
        move = target_world - world

        # A normal valid contact may need overlap in addition to the measured
        # gap. Clamp accidental large moves to a safe limit.
        max_move = max_extension + overlap
        if move.length > max_move:
            if distance > tolerance:
                result["unresolved"] += 1
            continue

        v.co = inv @ target_world
        result["fixed"] += 1

    mesh.update()
    bpy.context.view_layer.update()

    # Re-check unresolved nearby endpoints after fixing.
    if auto_fix and result["candidates"]:
        unresolved = 0
        for v in mesh.vertices:
            if has_edges and degree[v.index] > 1:
                continue
            world = support.matrix_world @ v.co
            if world.z <= min_tip_z:
                continue
            nearest = bvh.find_nearest(world)
            if nearest is None:
                continue
            _, _, _, distance = nearest
            # Corrected endpoints are inside the mesh and nearest-surface
            # distance can equal the intentional overlap. Treat them as okay.
            if distance is not None and tolerance < distance <= max_extension:
                # If it is roughly our requested overlap it is intentional.
                if abs(distance - overlap) > max(tolerance, 0.03):
                    unresolved += 1
        result["unresolved"] = unresolved

    log(
        "Contact validation: "
        f"{result['candidates']} candidates, "
        f"{result['gaps']} gaps, "
        f"{result['fixed']} adjusted, "
        f"{result['unresolved']} unresolved"
    )
    return result



# ----------------------------------------------------------------------
# Cleanup for obsolete support experiments
# ----------------------------------------------------------------------

LEGACY_SUPPORT_OBJECT_NAMES = {
    "FDM_RESCUE_TRUSSES",
    "FDM_ROOT_LINKS",
    "FDM_TWIN_PILLARS",
}
LEGACY_SUPPORT_ROLES = {
    "RESCUE_TRUSSES",
    "ROOT_LINKS",
    "TWIN_PILLARS",
}


def clear_legacy_support_hacks():
    """Remove objects left by retired Rescue/Root/Twin experiments."""
    removed = 0
    for obj in list(bpy.data.objects):
        if (
            obj.name in LEGACY_SUPPORT_OBJECT_NAMES
            or obj.get("fdm_mini_tools_role") in LEGACY_SUPPORT_ROLES
        ):
            data = obj.data if obj.type == "MESH" else None
            bpy.data.objects.remove(obj, do_unlink=True)
            if data is not None and data.users == 0:
                try:
                    bpy.data.meshes.remove(data)
                except Exception:
                    pass
            removed += 1
    if removed:
        log(f"Removed {removed} retired support-experiment object(s).")
    return removed


def get_supplemental_support_objects():
    # The 0.2 tree prototype emits a single SUPPORTS object. Old supplemental
    # Rescue/Root/Twin objects are intentionally no longer part of the pipeline.
    return []


def clear_supplemental_supports():
    from . import contact_audit
    contact_audit.clear_markers()
    return clear_legacy_support_hacks()


def analyze(model, support=None, overhang_angle=45.0):
    threshold = -math.cos(math.radians(overhang_angle))
    count = 0
    area = 0.0
    for p in model.data.polygons:
        n = model.matrix_world.to_3x3() @ p.normal
        if n.z < threshold:
            count += 1
            area += p.area

    result = {
        "overhang_faces": count,
        "overhang_area": area,
        "support_vertices": 0,
        "support_faces": 0,
        "mini_nonmanifold": nonmanifold_edge_count(model, evaluated=True),
        "support_nonmanifold": 0,
    }

    support_objects = ([support] if support else []) + get_supplemental_support_objects()

    for obj in support_objects:
        deps = bpy.context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(deps)
        mesh = eval_obj.to_mesh()
        try:
            result["support_vertices"] += len(mesh.vertices)
            result["support_faces"] += len(mesh.polygons)
        finally:
            eval_obj.to_mesh_clear()

        result["support_nonmanifold"] += nonmanifold_edge_count(
            obj,
            evaluated=True,
        )

    return result


def export_selected_stl(filepath, objects):
    filepath = str(filepath)
    deselect_all()
    for obj in objects:
        obj.hide_set(False)
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]

    if hasattr(bpy.ops.wm, "stl_export"):
        try:
            bpy.ops.wm.stl_export(
                filepath=filepath,
                export_selected_objects=True,
                ascii_format=False,
                apply_modifiers=True,
            )
        except TypeError:
            bpy.ops.wm.stl_export(
                filepath=filepath,
                export_selected_objects=True,
                ascii_format=False,
            )
    else:
        bpy.ops.export_mesh.stl(
            filepath=filepath,
            use_selection=True,
            ascii=False,
            use_mesh_modifiers=True,
        )



def ensure_level_cube(model, support=None, size=1.0, height=0.20, margin=1.0):
    """
    Create/update a tiny build-plate reference object for the MINI export.

    The cube is intentionally placed just outside the combined MINI/SUPPORTS
    footprint. It touches Z=0 and is exported as part of the MINI STL.
    This mirrors Resin2FDM's "level cube" concept: the slicer sees the MINI
    object as build-plate-connected even though the miniature itself is held
    above the plate by a separate SUPPORTS object.
    """
    name = "FDM_LEVEL_CUBE"

    # Determine footprint using MINI and, if available, SUPPORTS.
    xs, ys = [], []

    for obj in [model, support] + get_supplemental_support_objects():
        if obj is None:
            continue

        try:
            if obj == support:
                deps = bpy.context.evaluated_depsgraph_get()
                eval_obj = obj.evaluated_get(deps)
                corners = [
                    eval_obj.matrix_world @ Vector(corner)
                    for corner in eval_obj.bound_box
                ]
            else:
                corners = [
                    obj.matrix_world @ Vector(corner)
                    for corner in obj.bound_box
                ]

            xs.extend(v.x for v in corners)
            ys.extend(v.y for v in corners)
        except Exception:
            pass

    if xs and ys:
        # Put it diagonally outside the support/mini footprint so it does not
        # overlap the raft or support geometry.
        x = min(xs) - margin - (size * 0.5)
        y = min(ys) - margin - (size * 0.5)
    else:
        x = -(margin + size * 0.5)
        y = -(margin + size * 0.5)

    obj = bpy.data.objects.get(name)

    if obj is None:
        bpy.ops.mesh.primitive_cube_add(
            size=1.0,
            location=(x, y, height * 0.5),
        )
        obj = bpy.context.active_object
        obj.name = name
    else:
        obj.hide_set(False)
        obj.hide_render = False
        obj.location = (x, y, height * 0.5)

    obj.dimensions = (size, size, height)
    activate(obj)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    # Exact Z=0 bottom.
    obj.location.z = height * 0.5
    bpy.context.view_layer.update()

    return obj


def remove_level_cube():
    obj = bpy.data.objects.get("FDM_LEVEL_CUBE")
    if obj is not None:
        bpy.data.objects.remove(obj, do_unlink=True)


def nonmanifold_edge_count(obj, evaluated=True):
    deps = bpy.context.evaluated_depsgraph_get()
    eval_obj = None
    try:
        mesh = obj.data
        if evaluated:
            eval_obj = obj.evaluated_get(deps)
            mesh = eval_obj.to_mesh()
        bm = bmesh.new()
        bm.from_mesh(mesh)
        count = sum(1 for e in bm.edges if len(e.link_faces) != 2)
        bm.free()
        return count
    finally:
        if evaluated and eval_obj is not None:
            try:
                eval_obj.to_mesh_clear()
            except Exception:
                pass


def _evaluated_export_copy(obj, name):
    deps = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(deps)
    mesh = bpy.data.meshes.new_from_object(
        eval_obj,
        preserve_all_data_layers=False,
        depsgraph=deps,
    )
    copy_obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(copy_obj)
    copy_obj.matrix_world = obj.matrix_world.copy()
    return copy_obj


def _fill_small_boundary_holes(obj, max_edges=12):
    bm = bmesh.new()
    bm.from_mesh(obj.data)

    if bm.verts:
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.001)

    try:
        bmesh.ops.dissolve_degenerate(bm, edges=list(bm.edges), dist=0.0005)
    except Exception:
        pass

    boundary = [e for e in bm.edges if len(e.link_faces) == 1]
    boundary_set = set(boundary)
    visited = set()

    for edge in boundary:
        if edge in visited:
            continue
        stack = [edge]
        component = []
        visited.add(edge)

        while stack:
            e = stack.pop()
            component.append(e)
            for v in e.verts:
                for ne in v.link_edges:
                    if ne in boundary_set and ne not in visited:
                        visited.add(ne)
                        stack.append(ne)

        if 2 < len(component) <= max_edges:
            try:
                bmesh.ops.holes_fill(bm, edges=component, sides=0)
            except Exception:
                pass

    loose = [v for v in bm.verts if not v.link_edges]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")

    bm.normal_update()
    if bm.faces:
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))

    bm.to_mesh(obj.data)
    bm.free()
    obj.data.validate(verbose=False)
    obj.data.update()


def final_manifold_repair(obj, mode="AUTO", voxel_size=0.08, max_hole_edges=12):
    before = nonmanifold_edge_count(obj, evaluated=False)
    _fill_small_boundary_holes(obj, max_edges=max_hole_edges)
    after_conservative = nonmanifold_edge_count(obj, evaluated=False)

    use_voxel = mode == "VOXEL" or (mode == "AUTO" and after_conservative > 0)

    if use_voxel:
        activate(obj)
        if hasattr(obj.data, "remesh_voxel_size"):
            obj.data.remesh_voxel_size = voxel_size
            if hasattr(obj.data, "remesh_voxel_adaptivity"):
                obj.data.remesh_voxel_adaptivity = 0.0
            if hasattr(obj.data, "use_remesh_fix_poles"):
                obj.data.use_remesh_fix_poles = True
            if hasattr(obj.data, "use_remesh_preserve_volume"):
                obj.data.use_remesh_preserve_volume = True
            bpy.ops.object.voxel_remesh()
            bpy.context.view_layer.update()
            _fill_small_boundary_holes(obj, max_edges=max_hole_edges)

    retriangulate(obj, quad_method="BEAUTY", ngon_method="BEAUTY")
    after = nonmanifold_edge_count(obj, evaluated=False)

    return {
        "before": before,
        "after_conservative": after_conservative,
        "after": after,
        "voxel_used": use_voxel,
    }




def _apply_object_transforms(obj):
    if obj is None:
        return
    activate(obj)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)


def _flatten_bottom_vertices(obj, tolerance=0.08):
    if obj is None or obj.type != "MESH" or not obj.data.vertices:
        return None

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    if not bm.verts:
        bm.free()
        return None

    z_min = min(v.co.z for v in bm.verts)
    limit = z_min + max(0.0, tolerance)
    changed = 0
    for v in bm.verts:
        if v.co.z <= limit:
            if abs(v.co.z - z_min) > 1e-6:
                changed += 1
            v.co.z = z_min

    bm.normal_update()
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.validate(verbose=False)
    obj.data.update()
    return changed


def _world_xy_bounds(obj):
    xs, ys, zs = [], [], []
    for v in obj.data.vertices:
        co = obj.matrix_world @ v.co
        xs.append(co.x)
        ys.append(co.y)
        zs.append(co.z)
    return min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)


def _ray_hits_raft_bottom(bvh, x, y, z_min, tol=0.08, cast_pad=2.0):
    location, _, _, _ = bvh.ray_cast(Vector((x, y, z_min - cast_pad)), Vector((0.0, 0.0, 1.0)), cast_pad * 8.0)
    return (location is not None) and (location.z <= z_min + tol)


def _candidate_inside_raft(bvh, x, y, z_min, clearance=0.0, samples=12, tol=0.08):
    if not _ray_hits_raft_bottom(bvh, x, y, z_min, tol=tol):
        return False
    if clearance <= 0.0:
        return True
    for i in range(samples):
        angle = (math.tau * i) / samples
        sx = x + math.cos(angle) * clearance
        sy = y + math.sin(angle) * clearance
        if not _ray_hits_raft_bottom(bvh, sx, sy, z_min, tol=tol):
            return False
    return True


def _collect_above_raft_xy(obj, z_cut):
    pts = []
    for v in obj.data.vertices:
        w = obj.matrix_world @ v.co
        if w.z > z_cut:
            pts.append((w.x, w.y))
    return pts




def _bottom_coverage_samples(obj, z_tolerance=0.12, step=1.5):
    """Return (hits,total) for a coarse XY sampling of the lowest printable surface."""
    if obj is None or obj.type != "MESH" or not obj.data.vertices:
        return (0, 0)
    bvh = _world_bvh_from_object(obj)
    min_x, max_x, min_y, max_y, z_min, _ = _world_xy_bounds(obj)
    hits = 0
    total = 0
    y = min_y + step * 0.5
    while y <= max_y - step * 0.5 + 1e-6:
        x = min_x + step * 0.5
        while x <= max_x - step * 0.5 + 1e-6:
            total += 1
            if _ray_hits_raft_bottom(bvh, x, y, z_min, tol=z_tolerance):
                hits += 1
            x += step
        y += step
    return hits, total


def _perforate_raft_export_copy(
    obj,
    *,
    raft_floor_thickness=0.60,
    hole_diameter=4.0,
    hole_spacing=6.0,
    edge_keepout=2.0,
    pillar_keepout=2.0,
):
    """Safely perforate an export-only SUPPORTS mesh.

    Important safeguards:
    - only run on a mesh that still has a measurable bottom footprint,
    - keep holes away from the raft outline and geometry above the raft floor,
    - perform the boolean on a backup-protected mesh,
    - rollback if the boolean destroys most of the raft or creates non-manifold output.
    """
    if obj is None or obj.type != "MESH" or not obj.data.vertices:
        return 0
    if hole_diameter <= 0.0 or hole_spacing <= 0.0:
        return 0

    radius = hole_diameter * 0.5
    clearance = radius + max(0.0, edge_keepout)
    step = max(hole_diameter + 0.4, hole_spacing)
    floor_tol = max(0.06, min(0.18, raft_floor_thickness * 0.25))

    _flatten_bottom_vertices(obj, tolerance=floor_tol)

    before_hits, before_total = _bottom_coverage_samples(
        obj,
        z_tolerance=floor_tol,
        step=max(1.0, min(2.0, hole_diameter * 0.5)),
    )
    if before_total == 0 or before_hits == 0:
        log("WARN: Raft perforation skipped: no reliable raft bottom footprint detected.")
        return 0

    bvh = _world_bvh_from_object(obj)
    min_x, max_x, min_y, max_y, z_min, _ = _world_xy_bounds(obj)

    # Anything clearly above the raft floor is treated as pillar/base/wall geometry.
    z_cut = z_min + max(0.12, raft_floor_thickness + 0.02)
    obstacle_points = _collect_above_raft_xy(obj, z_cut)
    obstacle_limit2 = (radius + max(0.0, pillar_keepout)) ** 2

    centers = []
    y = min_y + clearance
    row = 0
    while y <= max_y - clearance + 1e-6:
        x = min_x + clearance + ((0.5 * step) if (row % 2) else 0.0)
        while x <= max_x - clearance + 1e-6:
            if _candidate_inside_raft(
                bvh, x, y, z_min,
                clearance=clearance,
                tol=floor_tol,
            ):
                blocked = False
                for ox, oy in obstacle_points:
                    dx = ox - x
                    dy = oy - y
                    if (dx * dx + dy * dy) < obstacle_limit2:
                        blocked = True
                        break
                if not blocked:
                    centers.append((x, y))
            x += step
        y += step
        row += 1

    if not centers:
        log("Raft perforation: no safe hole centers found.")
        return 0

    # Cut only through the raft floor with a small safety overlap below/above it.
    cut_bottom = z_min - 0.15
    cut_top = z_min + raft_floor_thickness + 0.15
    depth = max(0.4, cut_top - cut_bottom)
    z_center = (cut_bottom + cut_top) * 0.5
    inv = obj.matrix_world.inverted()

    backup_mesh = obj.data.copy()
    cutter_mesh = None
    cutter_obj = None
    old_mesh_after_failure = None

    try:
        cutter_bm = bmesh.new()
        for x, y in centers:
            local_center = inv @ Vector((x, y, z_center))
            bmesh.ops.create_cone(
                cutter_bm,
                cap_ends=True,
                cap_tris=False,
                segments=24,
                radius1=radius,
                radius2=radius,
                depth=depth,
                matrix=Matrix.Translation(local_center),
            )

        cutter_mesh = bpy.data.meshes.new("FDM_RAFT_HOLE_CUTTERS")
        cutter_bm.to_mesh(cutter_mesh)
        cutter_bm.free()
        cutter_obj = bpy.data.objects.new("FDM_RAFT_HOLE_CUTTERS", cutter_mesh)
        bpy.context.collection.objects.link(cutter_obj)
        cutter_obj.matrix_world = Matrix.Identity(4)

        activate(obj)
        mod = obj.modifiers.new(name="FDM_Raft_Perforation", type="BOOLEAN")
        mod.operation = 'DIFFERENCE'
        if hasattr(mod, 'solver'):
            mod.solver = 'EXACT'
        mod.object = cutter_obj
        bpy.ops.object.modifier_apply(modifier=mod.name)
        _flatten_bottom_vertices(obj, tolerance=floor_tol)

        after_hits, _ = _bottom_coverage_samples(
            obj,
            z_tolerance=floor_tol,
            step=max(1.0, min(2.0, hole_diameter * 0.5)),
        )
        nonmanifold = nonmanifold_edge_count(obj, evaluated=False)

        # 4 mm holes on a 6 mm grid normally retain roughly 60-70% of the floor.
        # A result below 35% of the previous footprint is treated as a failed boolean.
        minimum_safe_hits = max(1, int(before_hits * 0.35))
        if after_hits < minimum_safe_hits or nonmanifold > 0:
            log(
                "WARN: Raft perforation rolled back: unsafe boolean result "
                f"(bottom hits {before_hits}->{after_hits}, non-manifold={nonmanifold})."
            )
            old_mesh_after_failure = obj.data
            obj.data = backup_mesh
            backup_mesh = None
            if old_mesh_after_failure is not None:
                try:
                    bpy.data.meshes.remove(old_mesh_after_failure, do_unlink=True)
                except Exception:
                    pass
            return 0

        log(
            f"Raft perforation: created {len(centers)} holes "
            f"(bottom coverage samples {before_hits}->{after_hits})."
        )
        return len(centers)
    except Exception as exc:
        log(f"WARN: Raft perforation failed and was rolled back: {exc}")
        old = obj.data
        obj.data = backup_mesh
        backup_mesh = None
        try:
            bpy.data.meshes.remove(old, do_unlink=True)
        except Exception:
            pass
        return 0
    finally:
        if cutter_obj is not None:
            try:
                bpy.data.objects.remove(cutter_obj, do_unlink=True)
            except Exception:
                pass
        if cutter_mesh is not None and cutter_mesh.users == 0:
            try:
                bpy.data.meshes.remove(cutter_mesh)
            except Exception:
                pass
        if backup_mesh is not None:
            try:
                bpy.data.meshes.remove(backup_mesh)
            except Exception:
                pass


def _mesh_world_data(objects):
    vertices = []
    triangles = []
    deps = bpy.context.evaluated_depsgraph_get()

    for obj in objects:
        eval_obj = obj.evaluated_get(deps)
        mesh = eval_obj.to_mesh()
        try:
            matrix = eval_obj.matrix_world
            base = len(vertices)
            vertices.extend(tuple(matrix @ v.co) for v in mesh.vertices)

            for poly in mesh.polygons:
                ids = list(poly.vertices)
                if len(ids) == 3:
                    triangles.append((base + ids[0], base + ids[1], base + ids[2]))
                elif len(ids) > 3:
                    for i in range(1, len(ids) - 1):
                        triangles.append((base + ids[0], base + ids[i], base + ids[i + 1]))
        finally:
            eval_obj.to_mesh_clear()

    return vertices, triangles


def export_3mf_scene(filepath, mini_objects, support_objects, contact_status_override=None):
    filepath = str(filepath)
    ns = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
    ET.register_namespace("", ns)

    model = ET.Element(
        f"{{{ns}}}model",
        {
            "unit": "millimeter",
            "{http://www.w3.org/XML/1998/namespace}lang": "en-US",
        },
    )
    resources = ET.SubElement(model, f"{{{ns}}}resources")
    # Tree boolean vertices can be closer than 1e-6 mm. Preserve their float32
    # distinctions through serialization; Classic retains its current format.
    precision = 9 if any(o.get('fdm_tree_mesh_context') for o in support_objects) else 6
    if precision == 9:
        from . import contact_audit
        statuses=[contact_audit.export_status(o) for o in support_objects if o.get('fdm_tree_mesh_context')]
        if contact_status_override is not None:
            statuses.append(contact_status_override)
        ET.SubElement(model,f'{{{ns}}}metadata',{'name':'FDMTree:ContactStatus'}).text=(
            'PREVIEW_INCOMPLETE' if any(s['incomplete'] for s in statuses) else 'GEOMETRY_CHECKED_NOT_PRINT_VALIDATED')

    def add_object(object_id, name, objects):
        verts, tris = _mesh_world_data(objects)
        obj_el = ET.SubElement(
            resources,
            f"{{{ns}}}object",
            {"id": str(object_id), "type": "model", "name": name},
        )
        mesh_el = ET.SubElement(obj_el, f"{{{ns}}}mesh")
        verts_el = ET.SubElement(mesh_el, f"{{{ns}}}vertices")
        for x, y, z in verts:
            ET.SubElement(
                verts_el,
                f"{{{ns}}}vertex",
                {"x": f"{x:.{precision}f}", "y": f"{y:.{precision}f}", "z": f"{z:.{precision}f}"},
            )
        tris_el = ET.SubElement(mesh_el, f"{{{ns}}}triangles")
        for a, b, c in tris:
            ET.SubElement(
                tris_el,
                f"{{{ns}}}triangle",
                {"v1": str(a), "v2": str(b), "v3": str(c)},
            )

    add_object(1, "MINI", mini_objects)
    add_object(2, "SUPPORTS", support_objects)

    build = ET.SubElement(model, f"{{{ns}}}build")
    if precision == 9:
        # Generic 3MF importers (including Orca CLI) arrange separate build
        # items independently. One assembly retains the shared coordinate
        # system while keeping MINI/SUPPORTS as individually named parts.
        assembly = ET.SubElement(resources, f"{{{ns}}}object",
            {"id":"3", "type":"model", "name":"FDM_MINI_WITH_SUPPORTS"})
        components = ET.SubElement(assembly, f"{{{ns}}}components")
        ET.SubElement(components, f"{{{ns}}}component", {"objectid":"1"})
        ET.SubElement(components, f"{{{ns}}}component", {"objectid":"2"})
        ET.SubElement(build, f"{{{ns}}}item", {"objectid":"3"})
    else:
        ET.SubElement(build, f"{{{ns}}}item", {"objectid": "1"})
        ET.SubElement(build, f"{{{ns}}}item", {"objectid": "2"})

    model_bytes = ET.tostring(model, encoding="utf-8", xml_declaration=True)

    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
        '</Types>'
    ).encode("utf-8")

    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
        '</Relationships>'
    ).encode("utf-8")

    with zipfile.ZipFile(filepath, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("3D/3dmodel.model", model_bytes)

    log(f"Exported 3MF: {filepath}")


def _remove_temp_object(obj):
    if obj is None:
        return
    mesh = obj.data if obj.type == "MESH" else None
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh and mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def export_outputs(
    model,
    support,
    source_path,
    output_dir=None,
    save_blend=True,
    use_level_cube=True,
    level_cube_size=1.0,
    level_cube_height=0.20,
    level_cube_margin=1.0,
    export_3mf=True,
    use_raft=True,
    raft_floor_thickness=0.60,
    perforate_raft=False,
    raft_hole_diameter=4.0,
    raft_hole_spacing=6.0,
    raft_hole_edge_keepout=2.0,
    raft_hole_pillar_keepout=2.0,
    do_final_manifold_repair=True,
    manifold_repair_mode="AUTO",
    manifold_hole_max_edges=12,
    manifold_mini_voxel_size=0.06,
    manifold_support_voxel_size=0.10,
    allow_incomplete_tree_export=False,
    progress=None,
):
    _progress(progress, 82, "Prepare export")
    tree_context = None
    tree_qa = None
    contact_status = None
    if support is not None and support.get("fdm_tree_strategy"):
        from . import tree_mesh
        from . import contact_audit
        import json
        status=contact_audit.export_status(support,model=model)
        contact_status=status
        if status['incomplete'] and not allow_incomplete_tree_export:
            raise RuntimeError('Tree export blocked: '+status['reason']+'. Explicitly enable preview-only export to proceed.')
        # Validate the construction result; export repair must not disguise
        # disconnected/invalid Tree geometry. Classic binding is untouched.
        tree_mesh.validate_support(model, support)
        tree_context = json.loads(support[tree_mesh.CONTEXT_KEY])
        # Tree Preview owns its own unified raft geometry. Keep the legacy
        # SLASG raft-perforation boolean disabled until the Tree raft gets its
        # own validated perforation/outline pass.
        perforate_raft = False
    source = Path(source_path)
    out = Path(output_dir) if output_dir else source.parent
    out.mkdir(parents=True, exist_ok=True)
    stem = source.stem
    if contact_status and contact_status['incomplete']:
        stem += '_PREVIEW_INCOMPLETE'

    mini_path = out / f"{stem}_mini.stl"
    support_path = out / f"{stem}_supports.stl"
    combined_path = out / f"{stem}_presupported_fdm02.stl"
    three_mf_path = out / f"{stem}_orca.3mf"
    blend_path = out / f"{stem}_fdm_mini_tools.blend"

    level_cube = None
    if use_level_cube:
        level_cube = ensure_level_cube(
            model,
            support,
            size=level_cube_size,
            height=level_cube_height,
            margin=level_cube_margin,
        )
    else:
        remove_level_cube()

    mini_copy = _evaluated_export_copy(model, "EXPORT_MINI")
    support_copy = _evaluated_export_copy(support, "EXPORT_SUPPORTS")
    supplemental_copies = [
        _evaluated_export_copy(obj, f"EXPORT_SUPPORT_EXTRA_{i}")
        for i, obj in enumerate(get_supplemental_support_objects(), start=1)
    ]
    level_copy = (
        _evaluated_export_copy(level_cube, "EXPORT_LEVEL_CUBE")
        if level_cube else None
    )

    repair = {"mini": None, "supports": None}
    raft_hole_count = 0

    try:
        _apply_object_transforms(support_copy)
        if use_raft:
            _flatten_bottom_vertices(
                support_copy,
                tolerance=max(0.05, min(0.18, raft_floor_thickness * 0.25)),
            )

        if do_final_manifold_repair:
            _progress(progress, 85, "Manifold repair: MINI")
            if tree_context is not None and manifold_repair_mode != 'VOXEL':
                repair['mini'] = dict(before=0, after_conservative=0,
                    after=0, voxel_used=False, skipped='VALIDATED_TREE_TARGET')
            else:
                repair["mini"] = final_manifold_repair(
                    mini_copy,
                    mode=manifold_repair_mode,
                    voxel_size=manifold_mini_voxel_size,
                    max_hole_edges=manifold_hole_max_edges,
                )
            _progress(progress, 89, "Manifold repair: SUPPORTS")
            if tree_context is not None and manifold_repair_mode != 'VOXEL':
                # The new Tree solid already passes topology. The legacy
                # cleanup/retriangulation can damage tiny boolean faces.
                repair['supports'] = dict(before=0, after_conservative=0,
                    after=0, voxel_used=False, skipped='VALIDATED_TREE_SOLID')
            else:
                repair["supports"] = final_manifold_repair(
                    support_copy,
                    mode=manifold_repair_mode,
                    voxel_size=manifold_support_voxel_size,
                    max_hole_edges=manifold_hole_max_edges,
                )
            for supplemental_copy in supplemental_copies:
                final_manifold_repair(
                    supplemental_copy,
                    mode=manifold_repair_mode,
                    voxel_size=manifold_support_voxel_size,
                    max_hole_edges=manifold_hole_max_edges,
                )
        else:
            repair["mini"] = {
                "before": nonmanifold_edge_count(mini_copy, evaluated=False),
                "after": nonmanifold_edge_count(mini_copy, evaluated=False),
                "voxel_used": False,
            }
            repair["supports"] = {
                "before": nonmanifold_edge_count(support_copy, evaluated=False),
                "after": nonmanifold_edge_count(support_copy, evaluated=False),
                "voxel_used": False,
            }

        # Perforate only after the SUPPORTS export copy has been repaired.
        # Boolean operations on SLASG's raw overlapping shells can otherwise erase
        # the thin raft while leaving the pillars behind.
        if use_raft and perforate_raft:
            _progress(progress, 91, "Perforate raft")
            raft_hole_count = _perforate_raft_export_copy(
                support_copy,
                raft_floor_thickness=raft_floor_thickness,
                hole_diameter=raft_hole_diameter,
                hole_spacing=raft_hole_spacing,
                edge_keepout=raft_hole_edge_keepout,
                pillar_keepout=raft_hole_pillar_keepout,
            )
            # Update the report after the final support operation.
            if repair.get("supports") is not None:
                repair["supports"]["after"] = nonmanifold_edge_count(
                    support_copy, evaluated=False
                )

        mini_objects = [mini_copy] + ([level_copy] if level_copy else [])
        support_objects = [support_copy] + supplemental_copies
        combined_objects = [mini_copy] + support_objects + ([level_copy] if level_copy else [])

        if tree_context is not None:
            # Recheck against the actual MINI export copy, after every export
            # transformation/repair, before writing any STL or 3MF.
            tree_qa = tree_mesh.validate_support(mini_copy, support_copy, tree_context)
            support_copy[tree_mesh.CONTEXT_KEY] = json.dumps(tree_context)
            support_copy['fdm_tree_contact_audit']=support.get('fdm_tree_contact_audit','')
            support_copy['fdm_tree_unresolved_tips']=int(support.get('fdm_tree_unresolved_tips',0))

        _progress(progress, 93, "Export STL files")
        export_selected_stl(mini_path, mini_objects)
        export_selected_stl(support_path, support_objects)
        export_selected_stl(combined_path, combined_objects)

        if export_3mf:
            _progress(progress, 96, "Export 3MF")
            export_3mf_scene(
                three_mf_path,
                mini_objects=mini_objects,
                support_objects=support_objects,
                contact_status_override=contact_status,
            )

        if save_blend:
            _progress(progress, 98, "Save Blender project")
            bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

        _progress(progress, 100, "Done")
        return {
            "mini": str(mini_path),
            "supports": str(support_path),
            "combined": str(combined_path),
            "3mf": str(three_mf_path) if export_3mf else None,
            "blend": str(blend_path) if save_blend else None,
            "level_cube": bool(level_cube),
            "raft_holes": raft_hole_count,
            "repair": repair,
            "tree_qa": tree_qa,
            "contact_status": contact_status,
            "preview_only": bool(contact_status and contact_status['incomplete']),
        }
    finally:
        _remove_temp_object(level_copy)
        for supplemental_copy in supplemental_copies:
            _remove_temp_object(supplemental_copy)
        _remove_temp_object(support_copy)
        _remove_temp_object(mini_copy)


def config_from_props(props):
    keys = (
        "support_strategy", "tree_contact_backend", "orientation_front",
        "tree_route_mode", "tree_route_budget", "tree_show_missing",
        "tree_budget_enabled", "tree_prioritize_contacts", "tree_recovery_seconds", "tree_recovery_region_seconds",
        "tree_guided_recovery", "tree_required_minima", "tree_layer_height", "tree_reuse_branches", "tree_complete_contacts",
        "tree_stabilize_stems", "tree_stem_slenderness", "tree_stem_min_length", "tree_stem_max_diameter",
        "orientation_front_vector", "orientation_front_path",
        "touch_diameter", "touch_depth", "neck_diameter", "neck_length",
        "tree_tip_cone_length", "tree_tip_neck_length",
        "pillar_diameter", "base_diameter", "base_height", "resolution",
        "max_neck_angle", "spacing", "safe_distance", "overhang_angle",
        "use_islands", "use_trees", "tree_merge_distance", "branch_descent",
        "tree_branch_diameter", "tree_trunk_diameter",
        "tree_max_branch_angle", "tree_ground_search_radius",
        "tree_ground_search_step", "tree_model_clearance",
        "tree_merge_rounds", "tree_contact_limit",
        "use_trusses", "truss_diameter", "truss_minimum_height",
        "truss_spacing", "truss_top_spacing", "truss_distance_limit", "truss_angle",
        "use_raft", "raft_expand_width", "raft_floor_thickness",
        "raft_wall_height", "raft_wall_thickness",
        "validate_support_contacts", "auto_fix_contact_gaps",
        "contact_tolerance", "tip_overlap", "max_contact_extension",
    )
    return {k: (tuple(getattr(props,k)) if k == 'orientation_front_vector' else getattr(props,k)) for k in keys}


def config_from_preset(name="BALANCED", **overrides):
    p = dict(PRESETS[name])
    p.update({
        "support_strategy": "SLASG_CLASSIC",
        "tree_contact_backend": "SLASG",
        "resolution": 8,
        "max_neck_angle": 25.0,
        "use_islands": True,
        "use_trees": True,
        "tree_branch_diameter": p.get("tree_branch_diameter", 1.00),
        "tree_trunk_diameter": p.get("tree_trunk_diameter", 1.80),
        "tree_max_branch_angle": 32.0,
        "tree_ground_search_radius": 16.0,
        "tree_ground_search_step": 1.5,
        "tree_model_clearance": p.get("tree_model_clearance", 0.45),
        "tree_tip_cone_length": p.get("tree_tip_cone_length", 0.32),
        "tree_tip_neck_length": p.get("tree_tip_neck_length", 0.35),
        "tree_merge_rounds": 6,
        "tree_contact_limit": 400,
        "tree_stabilize_stems": True,
        "tree_required_minima": True,
        "tree_complete_contacts": True,
        "tree_guided_recovery": True,
        "use_trusses": True,
        "truss_angle": 45.0,
        "truss_top_spacing": p.get("truss_top_spacing", 0.0),
        "use_raft": True,
        "raft_expand_width": 1.50,
        "raft_floor_thickness": 0.60,
        "raft_wall_height": 0.80,
        "raft_wall_thickness": 0.60,
        "validate_support_contacts": False,
        "auto_fix_contact_gaps": False,
        "contact_tolerance": 0.04,
        "tip_overlap": 0.12,
        "max_contact_extension": 0.30,
    })
    p.update({k: v for k, v in overrides.items() if v is not None})
    return p


def prepare_model(
    source_path,
    slasg_path,
    *,
    config,
    optimize=True,
    optimizer_strength="BALANCED",
    optimization_config=None,
    orientation_mode="SCORED",
    tilt_x=35.0,
    tilt_y=7.0,
    lift=3.0,
    generate_supports=True,
    clear=True,
    progress=None,
):
    _progress(progress, 2, "Preparing scene")
    if orientation_mode == 'SCORED' and config.get('orientation_front') == 'VIEW':
        captured_path = config.get('orientation_front_path')
        if not captured_path or Path(captured_path).resolve() != Path(source_path).resolve():
            raise ValueError('Front direction is missing for this file: import it and set the view')
    if clear:
        clear_scene(purge=True)
    configure_mm_units()

    _progress(progress, 5, "Import STL")
    model = import_stl(source_path)
    if config.get('orientation_front') == 'VIEW':
        model[orientation.FRONT_KEY] = list(config['orientation_front_vector'])

    if optimize:
        log("Running FDM optimization pipeline...")
        opt_cfg = (
            dict(optimization_config)
            if optimization_config is not None
            else optimization_config_from_preset(optimizer_strength)
        )
        run_optimization_pipeline(model, opt_cfg, progress=progress, start=10, end=45)

    _progress(progress, 48, "Orientation")
    chosen_orientation = (0.0, 0.0, 0.0)
    if orientation_mode == "SCORED":
        log("Scoring miniature orientations...")
        chosen_orientation = orient_scored(model, lift, config["overhang_angle"], config.get('orientation_front','AUTO'))
    elif orientation_mode == "FIXED":
        chosen_orientation = orient_fixed(model, tilt_x, tilt_y, lift)
    else:
        _place_lowest_at(model, lift)
        frame_object_in_viewports(model)

    support = None
    tree_stats = {
        "raw_points": 0, "contacts": 0, "rejected_points": 0,
        "merges": 0, "rooted_components": 0, "rooted_tips": 0,
        "unresolved_components": 0, "unresolved_tips": 0, "segments": 0,
    }
    contact_stats = {
        "candidates": 0, "valid": 0, "gaps": 0,
        "fixed": 0, "unresolved": 0,
    }

    if generate_supports:
        strategy = config.get("support_strategy", "SLASG_CLASSIC")
        if strategy == "FDM_TREE":
            backend = contacts.backend_for(config)
            _progress(progress, 60, f"Acquire Tree contacts: {backend}")
            point_source = contacts.create_tree_point_object(
                model, config, slasg_path, progress=progress,
            )
            try:
                _progress(progress, 70, "Build experimental grounded FDM tree")
                support, tree_stats = tree_support.generate_tree_supports(
                    model, point_source, config,
                    progress=lambda pct, step: _progress(progress, 70 + pct * 0.10, step),
                )
            finally:
                tree_support.remove_point_source(point_source)
        else:
            if not slasg_path:
                raise RuntimeError("Classic SLASG requires the bundled resource .blend")
            _progress(progress, 56, "Load SLASG Classic")
            point_source, scatter, generator = append_slasg(slasg_path)
            _progress(progress, 62, "Configure Classic supports")
            configure_slasg(model, point_source, scatter, generator, config)
            _progress(progress, 70, "Bake SLASG supports")
            support = point_source
            bake_scatter(support, scatter, enable_generator=True)
            if config.get("validate_support_contacts", False):
                _progress(progress, 78, "Validate support contacts")
                contact_stats = validate_and_fix_support_contacts(
                    model, support,
                    tolerance=config.get("contact_tolerance", 0.04),
                    overlap=config.get("tip_overlap", 0.12),
                    max_extension=config.get("max_contact_extension", 0.30),
                    auto_fix=config.get("auto_fix_contact_gaps", False),
                )

    _progress(progress, 82, "Analyze model")
    stats = analyze(model, support, config["overhang_angle"])
    stats["contacts"] = contact_stats if support else {
        "candidates": 0, "valid": 0, "gaps": 0,
        "fixed": 0, "unresolved": 0,
    }
    stats["tree"] = tree_stats if support else {
        "raw_points": 0, "contacts": 0, "rejected_points": 0,
        "merges": 0, "rooted_components": 0, "rooted_tips": 0,
        "unresolved_components": 0, "unresolved_tips": 0, "segments": 0,
    }
    return model, support, chosen_orientation, stats


def one_click(
    source_path,
    slasg_path,
    *,
    output_dir=None,
    preset="BALANCED",
    optimizer_strength="BALANCED",
    optimize=True,
    optimization_config=None,
    orientation_mode="SCORED",
    tilt_x=35.0,
    tilt_y=7.0,
    lift=3.0,
    generate_supports=True,
    save_blend=True,
    use_level_cube=True,
    level_cube_size=1.0,
    level_cube_height=0.20,
    level_cube_margin=1.0,
    export_3mf=True,
    use_raft=True,
    raft_floor_thickness=0.60,
    perforate_raft=False,
    raft_hole_diameter=4.0,
    raft_hole_spacing=6.0,
    raft_hole_edge_keepout=2.0,
    raft_hole_pillar_keepout=2.0,
    do_final_manifold_repair=True,
    manifold_repair_mode="AUTO",
    manifold_hole_max_edges=12,
    manifold_mini_voxel_size=0.06,
    manifold_support_voxel_size=0.10,
    overrides=None,
    progress=None,
):
    config = config_from_preset(preset, **(overrides or {}))
    model, support, orientation, stats = prepare_model(
        source_path, slasg_path,
        config=config,
        optimize=optimize,
        optimizer_strength=optimizer_strength,
        optimization_config=optimization_config,
        orientation_mode=orientation_mode,
        tilt_x=tilt_x,
        tilt_y=tilt_y,
        lift=lift,
        generate_supports=generate_supports,
        clear=True,
        progress=progress,
    )

    exports = None
    if generate_supports:
        exports = export_outputs(
            model,
            support,
            source_path,
            output_dir,
            save_blend=save_blend,
            use_level_cube=use_level_cube,
            level_cube_size=level_cube_size,
            level_cube_height=level_cube_height,
            level_cube_margin=level_cube_margin,
            export_3mf=export_3mf,
            use_raft=use_raft,
            raft_floor_thickness=raft_floor_thickness,
            perforate_raft=perforate_raft,
            raft_hole_diameter=raft_hole_diameter,
            raft_hole_spacing=raft_hole_spacing,
            raft_hole_edge_keepout=raft_hole_edge_keepout,
            raft_hole_pillar_keepout=raft_hole_pillar_keepout,
            do_final_manifold_repair=do_final_manifold_repair,
            manifold_repair_mode=manifold_repair_mode,
            manifold_hole_max_edges=manifold_hole_max_edges,
            manifold_mini_voxel_size=manifold_mini_voxel_size,
            manifold_support_voxel_size=manifold_support_voxel_size,
            progress=progress,
        )

    return {
        "source": str(source_path),
        "orientation": {"x": orientation[0], "y": orientation[1], "z": orientation[2]},
        "analysis": stats,
        "exports": exports,
    }
