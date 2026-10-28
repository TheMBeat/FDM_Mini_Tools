
import bpy
from bpy.types import PropertyGroup
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from .presets import apply_preset


def _preset_update(self, context):
    if self.preset != "CUSTOM":
        apply_preset(self, self.preset)



def _optimizer_preset_update(self, context):
    if self.optimizer_strength == "CUSTOM":
        return

    presets = {
        "SAFE": {
            "do_cleanup": True,
            "do_detail_enhancement": True,
            "do_surface_smooth": False,
            "do_voxel_remesh": False,
            "do_retriangulate": True,
            "cleanup_merge_distance": 0.002,
            "groove_depth": 0.10,
            "ridge_height": 0.05,
            "detail_detection_min": 0.018,
            "detail_detection_max": 0.22,
            "detail_widen_rings": 1,
            "smooth_factor": 0.0,
            "smooth_iterations": 0,
            "voxel_size": 0.06,
            "triangulate_quad_method": "BEAUTY",
            "triangulate_ngon_method": "BEAUTY",
        },
        "BALANCED": {
            "do_cleanup": True,
            "do_detail_enhancement": True,
            "do_surface_smooth": True,
            "do_voxel_remesh": True,
            "do_retriangulate": True,
            "cleanup_merge_distance": 0.002,
            "groove_depth": 0.16,
            "ridge_height": 0.09,
            "detail_detection_min": 0.015,
            "detail_detection_max": 0.28,
            "detail_widen_rings": 1,
            "smooth_factor": 0.02,
            "smooth_iterations": 1,
            "voxel_size": 0.06,
            "triangulate_quad_method": "BEAUTY",
            "triangulate_ngon_method": "BEAUTY",
        },
        "STRONG": {
            "do_cleanup": True,
            "do_detail_enhancement": True,
            "do_surface_smooth": True,
            "do_voxel_remesh": True,
            "do_retriangulate": True,
            "cleanup_merge_distance": 0.003,
            "groove_depth": 0.22,
            "ridge_height": 0.13,
            "detail_detection_min": 0.012,
            "detail_detection_max": 0.32,
            "detail_widen_rings": 2,
            "smooth_factor": 0.03,
            "smooth_iterations": 1,
            "voxel_size": 0.05,
            "triangulate_quad_method": "BEAUTY",
            "triangulate_ngon_method": "BEAUTY",
        },
    }

    for key, value in presets[self.optimizer_strength].items():
        setattr(self, key, value)


class FDMMINI_Properties(PropertyGroup):
    tree_guided_recovery: BoolProperty(name="Route around obstacles to rooted branches (experimental)",default=True,
        description="Bounded search with full collision checks and layer diagnostics. Complete coverage is not guaranteed")
    tree_complete_contacts: BoolProperty(name="Recover unresolved contacts (experimental)",default=True,
        description="Try compact tips and low bases within existing angle and collision limits; unresolved regions remain blocked")
    tree_stabilize_stems: BoolProperty(name="Stabilize long stems (experimental)",default=True,
        description="Check free spans; compare diagonal bracing, thicker stems and paired rooted stems; mechanical strength is unverified")
    tree_stem_slenderness: FloatProperty(name="Max. free span / effective diameter",default=18.,min=5.,max=50.)
    tree_stem_min_length: FloatProperty(name="Check stems longer than (mm)",default=12.,min=1.,max=100.)
    tree_stem_max_diameter: FloatProperty(name="Max. reinforced stem diameter (mm)",default=3.2,min=.5,max=8.)
    tree_reuse_branches: BoolProperty(name="Reuse branches (experimental)",default=False,
        description="Attach unresolved contacts to rooted branches; reinforce carrying paths and recheck collisions")
    tree_required_minima: BoolProperty(name="Support required low points (experimental)",default=True,
        description="Supplement SLASG with first-layer birth contacts regardless of overhang angle; preserve all collision limits")
    tree_layer_height: FloatProperty(name="Layer height for low points (mm)",default=.08,min=.01,max=.4,precision=3)
    optimization_profile: StringProperty(name="Resolved print profile",subtype='FILE_PATH', description='Resolved printer settings imported from Orca, including inherited settings. Bridge span remains unverified without calibration.')
    optimization_directory: StringProperty(name="Comparison folder",subtype='DIR_PATH',default='//mini_optimization/')
    optimization_orca: StringProperty(name='OrcaSlicer',subtype='FILE_PATH',default=r'C:\Program Files\OrcaSlicer\orca-slicer.exe')
    optimization_auto_compare: BoolProperty(name="Automatically compare variants",default=True, description='Compare orientations and optional splits with Orca instead of preparing one model. This can take several minutes.')
    optimization_max_parts: IntProperty(name="Maximum parts",default=6,min=1,max=6, description='Upper limit on generated parts; fewer parts may be selected when splitting has no proven advantage.')
    optimization_joint_type: EnumProperty(name="Connection",items=[
        ('FLAT',"Flat glue face","Closed cut faces without keys; place cut face directly on the bed"),
        ('HEMISPHERE',"Hemisphere","Two unequal hemispheres with matching sockets; cut face upwards")],default='FLAT', description='Flat faces can rest on the print bed. Hemispherical keys need matching sockets and a calibrated fit.')
    optimization_clearance: FloatProperty(name="Fit clearance per side (mm)",default=.15,min=.02,max=.5,precision=3,
        description="Uncalibrated starting value. Print the fit test before the miniature")
    optimization_split_mode: EnumProperty(name="Splitting",items=[
        ('AUTO',"Automatic","Search for safe split variants"),
        ('MANUAL',"Manual cutting plane","Use the cutting helper position and rotation"),
        ('OFF',"No splitting","Compare current and automatic orientation only")],default='AUTO', description='Choose automatic splitting, a manually positioned cutting plane, or an unsplit comparison.')
    optimization_cut_plane: PointerProperty(name="Cutting plane",type=bpy.types.Object, description='Object defining the position and normal of the manual cut. The original model is preserved.')
    optimization_report: StringProperty(name="Comparison report",subtype='FILE_PATH')
    optimization_status: StringProperty(name="Optimization status")
    optimization_results_json: StringProperty(default='[]',options={'HIDDEN'})
    ui_workflow_step: EnumProperty(name="Workflow step",items=[
        ('MODEL','1',"Load model"),('PROFILE','2',"Print profile and detail protection"),
        ('CALCULATE','3',"Calculate supports"),('REVIEW','4',"Review result"),
        ('EXPORT','5',"Files for Orca")],default='MODEL')
    ui_selected_variant: StringProperty(default='ORIGINAL',options={'HIDDEN'})
    ui_variant_assembly: BoolProperty(default=False,options={'HIDDEN'})
    target_model: PointerProperty(name="Mini", type=bpy.types.Object)
    support_object: PointerProperty(name="Supports", type=bpy.types.Object)

    preset: EnumProperty(
        name="Support preset",
        items=[
            ("FINE", "0.2 Mini - Fine", "Small contacts, easiest removal"),
            ("BALANCED", "0.2 Mini - Balanced", "Recommended default"),
            ("ROBUST", "0.2 Mini - Heavy", "Maximum support stability for difficult minis"),
            ("CUSTOM", "Custom", "Use current values"),
        ],
        default="BALANCED",
        update=_preset_update,
    )

    optimizer_strength: EnumProperty(
        name="Optimization preset",
        items=[
            ("SAFE", "Safe", "Conservative: cleanup + enhancement + retriangulate"),
            ("BALANCED", "Balanced", "Recommended for 0.2 mm FDM minis"),
            ("STRONG", "Strong", "Stronger detail enhancement and finer remesh"),
            ("CUSTOM", "Custom", "Use the current per-step settings"),
        ],
        default="BALANCED",
        update=_optimizer_preset_update,
    )

    do_optimize: BoolProperty(
        name="Detail optimization",
        default=True,
        description="Master switch for the optimization pipeline",
    )

    do_cleanup: BoolProperty(name="Mesh Cleanup", default=True)
    do_detail_enhancement: BoolProperty(name="Detail Enhancement", default=True)
    do_surface_smooth: BoolProperty(name="Surface Smooth", default=True)
    do_voxel_remesh: BoolProperty(name="Voxel Remesh", default=True)
    do_retriangulate: BoolProperty(name="Retriangulate", default=True)

    cleanup_merge_distance: FloatProperty(
        name="Merge distance mm",
        default=0.002,
        min=0.0001,
        max=0.05,
        precision=4,
    )

    groove_depth: FloatProperty(
        name="Groove depth mm",
        default=0.16,
        min=0.0,
        max=0.50,
        precision=3,
    )
    ridge_height: FloatProperty(
        name="Ridge height mm",
        default=0.09,
        min=0.0,
        max=0.50,
        precision=3,
    )
    detail_detection_min: FloatProperty(
        name="Detail threshold min",
        default=0.015,
        min=0.001,
        max=0.10,
        precision=4,
    )
    detail_detection_max: FloatProperty(
        name="Detail threshold max",
        default=0.28,
        min=0.05,
        max=1.00,
        precision=3,
    )
    detail_widen_rings: IntProperty(
        name="Detail widen rings",
        default=1,
        min=0,
        max=4,
    )

    smooth_factor: FloatProperty(
        name="Smooth factor",
        default=0.02,
        min=0.0,
        max=0.50,
        precision=3,
    )
    smooth_iterations: IntProperty(
        name="Smooth iterations",
        default=1,
        min=0,
        max=10,
    )

    voxel_size: FloatProperty(
        name="Voxel size mm",
        default=0.06,
        min=0.02,
        max=0.50,
        precision=3,
    )

    triangulate_quad_method: EnumProperty(
        name="Quad method",
        items=[
            ("BEAUTY", "Beauty", "Choose diagonals for good triangle shapes"),
            ("FIXED", "Fixed", "Fixed diagonal"),
            ("FIXED_ALTERNATE", "Fixed Alternate", "Alternate fixed diagonal"),
            ("SHORTEST_DIAGONAL", "Shortest Diagonal", "Use the shortest diagonal"),
            ("LONGEST_DIAGONAL", "Longest Diagonal", "Use the longest diagonal"),
        ],
        default="BEAUTY",
    )
    triangulate_ngon_method: EnumProperty(
        name="N-gon method",
        items=[
            ("BEAUTY", "Beauty", "Use Blender's beauty triangulation"),
            ("EAR_CLIP", "Ear Clip", "Triangulate N-gons by ear clipping"),
        ],
        default="BEAUTY",
    )
    do_orientation: BoolProperty(name="Auto orientation", default=True)
    do_supports: BoolProperty(name="Auto supports", default=True)
    auto_export: BoolProperty(
        name="Export after One Click",
        default=True,
        description="Automatically export MINI, SUPPORTS and combined STL after preparation",
    )
    save_blend: BoolProperty(
        name="Save .blend project",
        default=True,
        description="Save an editable Blender project next to the exported STLs",
    )

    orientation_mode: EnumProperty(
        name="Orientation mode",
        items=[
            ("SCORED", "Automatic (details)", "Score orientation by overhangs and detail region"),
            ("FIXED", "Manual angles", "Set back and side tilt manually"),
            ("KEEP", "Keep orientation", "Do not rotate model"),
        ],
        default="SCORED",
    )
    orientation_front: EnumProperty(
        name="Front side",
        description="Automatic detail heuristic or manually selected front; face detection is uncertain",
        items=[('AUTO',"Automatic (details)","Estimate the upper central detail region"),
               ('VIEW',"From view","Use the direction saved with Use current view as front"),
               ('POS_Y','+Y',"Model front along +Y"),('NEG_Y','-Y',"Model front along -Y"),
               ('POS_X','+X',"Model front along +X"),('NEG_X','-X',"Model front along -X")],
        default='AUTO',
    )
    tilt_x: FloatProperty(name="Back tilt °", default=35.0, min=-60.0, max=60.0)
    orientation_front_vector: FloatVectorProperty(size=3, default=(0,1,0))
    orientation_front_path: StringProperty(default='')
    tilt_y: FloatProperty(name="Side tilt °", default=7.0, min=-45.0, max=45.0)
    lift_mm: FloatProperty(name="Lift mm", default=3.0, min=1.5, max=30.0)

    support_strategy: EnumProperty(
        name="Support method",
        items=[
            ("SLASG_CLASSIC", "Classic (tested)",
             "Bundled proven SLASG path; no external resource setup needed"),
            ("FDM_TREE", "Tree + SLA tips (preview)",
             "Experimental Tree generator; SLASG contact baseline by default"),
        ],
        default="SLASG_CLASSIC",
    )

    tree_contact_backend: EnumProperty(
        name="Contact points",
        description="SLASG is the reference; native sampler is for A/B tests only",
        items=[
            ("SLASG", "SLASG (reference)", "Reference SLASG distribution: overhangs, islands and local low points"),
            ("NATIVE_EXPERIMENTAL", "Python (Experiment)", "For A/B tests only; parity has not been demonstrated"),
        ],
        default="SLASG",
    )

    ui_level: EnumProperty(
        name="Options",
        description="Choose how many controls are visible, without changing the saved settings",
        items=[
            ("SIMPLE", "Simple", "Few controls and a guided workflow"),
            ("ADVANCED", "Advanced", "Tuning and manual preparation steps"),
            ("EXPERT", "Expert", "All configuration and diagnostic controls"),
        ],
        default="SIMPLE",
    )

    touch_diameter: FloatProperty(name="Touch Ø mm", default=0.30, min=0.15, max=1.0, description="Classic SLASG contact diameter at the MINI; Tree mode expands from this diameter to Neck Ø over a short cone")
    touch_depth: FloatProperty(name="Touch depth mm", default=0.18, min=0.05, max=1.0)
    neck_diameter: FloatProperty(name="Neck Ø mm", default=0.50, min=0.20, max=2.0, description="Classic SLASG neck diameter; reached immediately after the short Tree contact cone")
    neck_length: FloatProperty(name="Neck length mm", default=2.10, min=0.5, max=10.0, description="Classic SLASG total neck reach; after the short cone the remaining neck stays at full Neck Ø")
    tree_tip_cone_length: FloatProperty(
        name="Tree tip cone mm",
        default=0.32,
        min=0.18,
        max=0.80,
        precision=2,
        description="FDM Tree only: short conical distance from Touch Ø to Neck Ø outside the MINI",
    )
    tree_tip_neck_length: FloatProperty(
        name="Tree neck mm",
        default=0.35,
        min=0.12,
        max=1.20,
        precision=2,
        description="FDM Tree only: short full-Neck-Ø section after the cone; classic 2 mm Neck Length is not used for Tree tips",
    )
    pillar_diameter: FloatProperty(name="Pillar Ø mm", default=1.35, min=0.40, max=4.0)
    base_diameter: FloatProperty(name="Base Ø mm", default=4.60, min=0.8, max=6.0)
    base_height: FloatProperty(name="Base taper height mm", default=1.80, min=0.1, max=4.0)
    resolution: IntProperty(name="Support sides", default=8, min=5, max=24)
    max_neck_angle: FloatProperty(name="Max neck angle °", default=25.0, min=5.0, max=60.0)

    spacing: FloatProperty(name="Spacing mm", default=1.45, min=0.5, max=10.0, description='Requested spacing between contact candidates in millimeters. Smaller spacing can add contacts and increase runtime.')
    safe_distance: FloatProperty(name="Safe distance mm", default=0.55, min=0.0, max=5.0)
    overhang_angle: FloatProperty(name="Overhang °", default=45.0, min=20.0, max=80.0, description='Surface angle used to select support candidates. Local low points are checked separately when enabled.')
    use_islands: BoolProperty(name="Topological islands", default=True)
    use_trees: BoolProperty(name="Auto trees", default=True)
    tree_merge_distance: FloatProperty(name="Tree merge mm", default=4.0, min=1.0, max=20.0)
    branch_descent: FloatProperty(name="Branch descent mm", default=4.5, min=0.5, max=15.0)

    use_trusses: BoolProperty(name="Trusses", default=True)
    truss_diameter: FloatProperty(name="Truss Ø mm", default=1.10, min=0.2, max=2.0)
    truss_minimum_height: FloatProperty(name="Truss start mm", default=2.75, min=1.0, max=50.0)
    truss_spacing: FloatProperty(name="Truss vertical spacing mm", default=2.75, min=1.0, max=30.0)
    truss_top_spacing: FloatProperty(name="Truss top spacing mm", default=0.00, min=0.0, max=10.0)
    truss_distance_limit: FloatProperty(name="Truss max distance mm", default=6.5, min=2.0, max=30.0)
    truss_angle: FloatProperty(name="Truss angle °", default=45.0, min=20.0, max=70.0)

    tree_branch_diameter: FloatProperty(
        name="Tree branch Ø mm",
        default=1.00,
        min=0.40,
        max=3.00,
        precision=2,
        description="Diameter of a single-leaf structural branch below the SLA neck",
    )
    tree_trunk_diameter: FloatProperty(
        name="Tree trunk max Ø mm",
        default=1.80,
        min=0.60,
        max=4.00,
        precision=2,
        description="Maximum diameter reached by merged load-bearing trunks",
    )
    tree_max_branch_angle: FloatProperty(
        name="Tree max angle °",
        default=32.0,
        min=10.0,
        max=55.0,
        precision=1,
        description="Hard maximum angle away from vertical for every structural branch/trunk; horizontal segments are rejected",
    )
    tree_ground_search_radius: FloatProperty(
        name="Ground search radius mm",
        default=16.0,
        min=0.0,
        max=30.0,
        precision=1,
        description="Maximum lateral search radius for a collision-free buildplate root",
    )
    tree_route_mode: EnumProperty(name="Routing",items=[
        ('DIRECT',"Direct (reference)","Established direct connection to the bed"),
        ('WAYPOINT_EXPERIMENTAL',"Obstacle routing (experimental)","Bounded downward waypoint search")],default='DIRECT')
    tree_route_budget: IntProperty(name="Search budget",default=64,min=8,max=512)
    tree_budget_enabled: BoolProperty(name="Limit additional search",default=True)
    tree_prioritize_contacts: BoolProperty(name="Prioritize island support",default=True)
    tree_recovery_seconds: FloatProperty(name="Total additional search (s)",default=20,min=.1,max=300)
    tree_recovery_region_seconds: FloatProperty(name="Additional search per region (s)",default=3,min=.05,max=30)
    tree_show_missing: BoolProperty(name='Mark missing supports',default=True)
    allow_incomplete_tree_export: BoolProperty(name='Export incomplete preview',default=False,
        description="Explicit preview export with missing contacts; not cleared for printing")
    tree_ground_search_step: FloatProperty(
        name="Ground search step mm",
        default=1.5,
        min=0.5,
        max=6.0,
        precision=1,
    )
    tree_model_clearance: FloatProperty(
        name="Tree MINI surface gap mm",
        default=0.45,
        min=0.10,
        max=2.50,
        precision=2,
        description="Requested minimum gap between the OUTSIDE of structural tree branches/trunks and the MINI; branch radius is added automatically during collision checks",
    )
    tree_contact_limit: IntProperty(
        name="Max contacts",
        description="Native tree sampler maximum candidate contacts (before tree clearance filtering)",
        default=400,
        min=20,
        max=1500,
    )
    tree_merge_rounds: IntProperty(
        name="Tree merge rounds",
        default=6,
        min=1,
        max=12,
        description="Maximum iterative branch-merge passes",
    )

    validate_support_contacts: BoolProperty(
        name="Validate support contacts",
        description="Optional support-tip contact validation. Normally not needed when using the shared 3MF export.",
        default=False,
    )
    auto_fix_contact_gaps: BoolProperty(
        name="Auto-fix contact gaps",
        description="Move near support endpoints onto/into the MINI surface",
        default=False,
    )
    contact_tolerance: FloatProperty(
        name="Contact tolerance mm",
        default=0.04,
        min=0.005,
        max=0.30,
        precision=3,
    )
    tip_overlap: FloatProperty(
        name="Tip overlap mm",
        description="How far corrected support endpoints intentionally overlap the MINI",
        default=0.12,
        min=0.0,
        max=0.40,
        precision=3,
    )
    max_contact_extension: FloatProperty(
        name="Max auto extension mm",
        description="Maximum detected gap that may be repaired automatically",
        default=0.30,
        min=0.05,
        max=1.0,
        precision=3,
    )

    use_raft: BoolProperty(name="Skate raft", default=True, description='Create a shared base under Tree supports. Raft geometry and model clearance must pass validation.')
    raft_expand_width: FloatProperty(name="Raft expand mm", default=1.50, min=0.2, max=6.0)
    raft_floor_thickness: FloatProperty(name="Raft floor mm", default=0.60, min=0.2, max=3.0)
    raft_wall_height: FloatProperty(name="Raft wall height mm", default=0.80, min=0.0, max=4.0)
    raft_wall_thickness: FloatProperty(name="Raft wall mm", default=0.60, min=0.2, max=3.0)
    perforate_raft: BoolProperty(
        name="Perforate raft",
        description="Punch optional holes into free raft areas to save filament",
        default=False,
    )
    raft_hole_diameter: FloatProperty(
        name="Hole Ø mm",
        description="Diameter of optional raft perforation holes",
        default=4.0,
        min=1.0,
        max=12.0,
        precision=2,
    )
    raft_hole_spacing: FloatProperty(
        name="Hole spacing mm",
        description="Center-to-center spacing of optional raft holes",
        default=6.0,
        min=2.0,
        max=20.0,
        precision=2,
    )
    raft_hole_edge_keepout: FloatProperty(
        name="Edge keepout mm",
        description="Minimum clearance from the outer raft edge to any raft hole",
        default=2.0,
        min=0.0,
        max=10.0,
        precision=2,
    )
    raft_hole_pillar_keepout: FloatProperty(
        name="Pillar keepout mm",
        description="Extra clearance from pillar/base geometry to any raft hole",
        default=2.0,
        min=0.0,
        max=10.0,
        precision=2,
    )

    export_3mf: BoolProperty(
        name="Export 3MF (recommended)",
        description="Export MINI and SUPPORTS as separate 3MF objects with shared world coordinates",
        default=True,
    )
    do_final_manifold_repair: BoolProperty(
        name="Final Manifold Repair",
        description="Repair export-only copies of MINI and SUPPORTS before STL/3MF export",
        default=True,
    )
    manifold_repair_mode: EnumProperty(
        name="Repair mode",
        items=[
            ("AUTO", "Auto", "Conservative repair first, then voxel repair only if non-manifold edges remain"),
            ("CONSERVATIVE", "Conservative", "Merge/clean/fill small holes without voxel remesh"),
            ("VOXEL", "Voxel", "Always voxel-remesh export copies after conservative repair"),
        ],
        default="AUTO",
    )
    manifold_hole_max_edges: IntProperty(
        name="Max hole edges",
        description="Maximum boundary-loop edge count filled by conservative repair",
        default=12,
        min=3,
        max=100,
    )
    manifold_mini_voxel_size: FloatProperty(
        name="Mini repair voxel mm",
        description="Voxel size used only when voxel manifold repair is required",
        default=0.06,
        min=0.03,
        max=0.30,
        precision=3,
    )
    manifold_support_voxel_size: FloatProperty(
        name="Support repair voxel mm",
        description="Voxel size used to union intersecting support/truss shells",
        default=0.10,
        min=0.05,
        max=0.40,
        precision=3,
    )
    analysis_mini_nonmanifold: IntProperty(default=0)
    analysis_support_nonmanifold: IntProperty(default=0)

    use_level_cube: BoolProperty(
        name="Level cube",
        description="Add a tiny build-plate reference to the MINI export so slicers do not reject the floating miniature",
        default=True,
    )
    level_cube_size: FloatProperty(
        name="Level cube size mm",
        description="Width/depth of the small build-plate reference",
        default=1.0,
        min=0.4,
        max=5.0,
    )
    level_cube_height: FloatProperty(
        name="Level cube height mm",
        description="Height of the small build-plate reference",
        default=0.20,
        min=0.08,
        max=1.0,
    )
    level_cube_margin: FloatProperty(
        name="Level cube margin mm",
        description="Distance from the combined MINI/SUPPORTS footprint",
        default=1.0,
        min=0.2,
        max=10.0,
    )

    show_advanced: BoolProperty(name="Advanced settings", default=False)
    slasg_blend_path: StringProperty(
        name="SLASG .blend",
        description="Optional override. Leave empty to use the bundled tuned SLASG library for scatter/classic supports.",
        subtype="FILE_PATH",
        default="",
    )
    export_directory: StringProperty(name="Export folder", subtype="DIR_PATH", default="")
    last_import_path: StringProperty(default="", options={"HIDDEN"})
    progress_active: BoolProperty(default=False, options={"HIDDEN"})
    progress_percent: FloatProperty(
        name="Progress",
        default=0.0,
        min=0.0,
        max=100.0,
        subtype="PERCENTAGE",
        precision=0,
    )
    progress_step: StringProperty(default="Ready")
    progress_error: StringProperty(default="")
    status_text: StringProperty(default="Ready")
    analysis_text: StringProperty(default="Not analyzed")
    analysis_overhang_faces: IntProperty(default=0)
    analysis_overhang_area: FloatProperty(default=0.0)
    analysis_support_vertices: IntProperty(default=0)
    analysis_support_faces: IntProperty(default=0)
    analysis_contact_candidates: IntProperty(default=0)
    analysis_contact_fixed: IntProperty(default=0)
    analysis_contact_unresolved: IntProperty(default=0)
    analysis_tree_contacts: IntProperty(default=0)
    analysis_tree_merges: IntProperty(default=0)
    analysis_tree_rooted_tips: IntProperty(default=0)
    analysis_tree_unresolved_tips: IntProperty(default=0)
    analysis_tree_missing_patches: IntProperty(default=0)
    analysis_tree_missing_minima: IntProperty(default=0)
    analysis_tree_unstable_stems: IntProperty(default=0)
    analysis_tree_segments: IntProperty(default=0)


classes = (FDMMINI_Properties,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.fdm_mini_tools = PointerProperty(type=FDMMINI_Properties)


def unregister():
    del bpy.types.Scene.fdm_mini_tools
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
