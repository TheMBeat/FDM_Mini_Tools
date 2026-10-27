"""Contact acquisition boundary.

SLASG VertexScatter is the reference implementation for Tree contacts.
Native sampling is an EXPERIMENT and must pass repeatable A/B benchmarks
before being considered for default use. No version-specific SLASG wiring
is reimplemented here; core is the single source of truth.
"""

SLASG_BACKEND = "SLASG"
EXPERIMENTAL_NATIVE_BACKEND = "NATIVE_EXPERIMENTAL"
KNOWN_BACKENDS = (SLASG_BACKEND, EXPERIMENTAL_NATIVE_BACKEND)


def backend_for(config):
    value = config.get("tree_contact_backend", SLASG_BACKEND)
    if value not in KNOWN_BACKENDS:
        raise ValueError(f"Unknown tree contact backend: {value}")
    return value


def requires_slasg(config):
    """Both Classic and Tree/SLASG require the bundled .blend library."""
    method = config.get("support_strategy", "SLASG_CLASSIC")
    if method == "SLASG_CLASSIC":
        return True
    if method == "FDM_TREE":
        return backend_for(config) == SLASG_BACKEND
    raise ValueError(f"Unknown support strategy: {method}")


def create_tree_point_object(model, config, slasg_path, progress=None):
    """Return baked world-space point mesh, never generated SLASG supports.

    Caller owns temporary object and must remove it in a finally block.
    """
    backend = backend_for(config)
    if backend == EXPERIMENTAL_NATIVE_BACKEND:
        from . import native_scatter
        point_object = native_scatter.create_point_object(
            model, config, progress=progress,
        )
        point_object["fdm_contact_backend"] = backend
        return point_object

    if not slasg_path:
        raise RuntimeError(
            "SLASG contact baseline requires bundled SLASG_FDM_Mini.blend; "
            "reinstall the add-on or select a valid SLASG override."
        )
    from . import core
    points, scatter, generator = core.append_slasg(slasg_path)
    try:
        core.configure_slasg(model, points, scatter, generator, config)
        core.bake_scatter(points, scatter, enable_generator=False)
        points["fdm_contact_backend"] = backend
        return points
    except Exception:
        import bpy
        if points and points.name in bpy.data.objects:
            bpy.data.objects.remove(points, do_unlink=True)
        raise
