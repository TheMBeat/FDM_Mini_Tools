"""Five ordered workflow panels; advanced controls stay out of the main path."""
import json
import textwrap
from pathlib import Path
import bpy
from bpy.types import Panel
from . import core, version, i18n


def _grid(layout, props, names):
    grid = layout.grid_flow(columns=2, even_columns=True, even_rows=False, align=True)
    for name in names:
        grid.prop(props, name)
    return grid


def _results(p):
    # Only the small, stored UI cache. Never read a multi-MB report in draw().
    try:
        rows = json.loads(p.optimization_results_json)
        return rows if isinstance(rows, list) else []
    except (ValueError, TypeError):
        return []


def workflow_state(p):
    rows = _results(p)
    selected = next((r for r in rows if r.get('id') == p.ui_selected_variant), None)
    variant = bool(p.target_model and p.optimization_report and selected)
    generated = bool(p.target_model and p.support_object and not p.optimization_report)
    gaps = p.support_strategy == 'FDM_TREE' and bool(p.analysis_tree_unresolved_tips or p.analysis_tree_missing_minima
                or p.analysis_tree_unstable_stems or p.analysis_tree_missing_patches)
    incomplete = bool(selected.get('incomplete', True)) if variant else gaps
    if p.progress_active:
        next_action = "Calculation running: " + p.progress_step
    elif not p.target_model:
        next_action = "Next: 1 - Load STL"
    elif p.progress_error:
        next_action = "Resolve the error and calculate again"
    elif variant or generated:
        next_action = "Next: 4 - Review contact gaps" if incomplete else "Next: 4 - Review result"
    else:
        next_action = "Next: 2 - Profile, then 3 - Calculate"
    return dict(rows=rows, selected=selected, variant=variant, generated=generated,
                incomplete=incomplete, next_action=next_action)


def _notice(layout, text, warning=False):
    text = i18n.iface(text)
    for index, line in enumerate(textwrap.wrap(text, width=32) or ['']):
        row = layout.row()
        row.alert = warning
        row.label(text=line, translate=False, icon=('ERROR' if warning else 'INFO') if index == 0 else 'BLANK1')


class FDMMINI_PT_main(Panel):
    bl_label = 'FDM Mini Tools'
    bl_idname = 'FDMMINI_PT_main'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FDM Mini'

    def draw(self, context):
        p = context.scene.fdm_mini_tools
        layout = self.layout
        identity = version.installed_build()
        layout.label(text='0.3.0 RC2 | ' + identity['short'] if identity['verified'] else "0.3.0 RC2 | Development build", icon='INFO')
        if not identity['verified']:
            _notice(layout, identity['label'])
        layout.prop(p, 'ui_workflow_step', expand=True)
        layout.prop(p, 'ui_level', expand=True)
        state = workflow_state(p)
        _notice(layout, state['next_action'], bool(p.progress_error))
        if p.progress_active or p.progress_error:
            layout.progress(factor=min(1, max(0, p.progress_percent / 100)), type='BAR',
                            text=i18n.format_iface('{v0:.0f}%  {v1}', v0=p.progress_percent, v1=p.progress_step))
            if p.progress_error:
                _notice(layout, p.progress_error[:70], True)
        if p.support_strategy == 'FDM_TREE':
            _notice(layout, "Tree: experimental. Print testing pending.")


class _Step:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FDM Mini'
    bl_parent_id = 'FDMMINI_PT_main'

    @classmethod
    def poll(cls, context):
        return context.scene.fdm_mini_tools.ui_workflow_step == cls.workflow_step


class FDMMINI_PT_model(_Step, Panel):
    bl_label = "1  Load model"
    bl_idname = 'FDMMINI_PT_model'
    bl_order = 1
    workflow_step = 'MODEL'

    def draw(self, context):
        p = context.scene.fdm_mini_tools
        col = self.layout.column()
        col.enabled = not p.progress_active
        action = col.column()
        action.scale_y = 1.25
        action.operator('fdm_mini_tools.import_mini', text="Load / replace STL", icon='IMPORT')
        col.label(text="Replaces the current working scene.", icon='INFO')
        if p.target_model:
            col.operator('fdm_mini_tools.workflow_step', text="Next: Print profile", icon='TRIA_RIGHT').step = 'PROFILE'
            col.label(text="Source: " + (Path(p.last_import_path).name if p.last_import_path else p.target_model.name), icon='MESH_DATA')
            if p.ui_level != 'SIMPLE':
                col.label(text="Source object: " + p.target_model.name)
        else:
            col.label(text="No model loaded yet.")


class FDMMINI_PT_profile(_Step, Panel):
    bl_label = "2  Print profile and detail protection"
    bl_idname = 'FDMMINI_PT_profile'
    bl_order = 2
    workflow_step = 'PROFILE'

    def draw(self, context):
        p = context.scene.fdm_mini_tools
        col = self.layout.column()
        col.enabled = not p.progress_active
        col.label(text='Qidi Q2 | 0,2 mm | 0,08 mm')
        col.label(text='PLA Matte Minis')
        profile = col.row(); profile.enabled = bool(p.target_model)
        profile.operator('fdm_mini_tools.optimization_profile', text="Load Orca profile", icon='FILE_REFRESH')
        col.label(text="Profile selected" if p.optimization_profile else "Comparison loads the profile automatically.", icon='INFO')
        col.label(text="Bridge span is unverified.")
        col.prop(p, 'preset', text="Stability")
        col.prop(p, 'orientation_mode', text="Print orientation")
        if p.orientation_mode == 'SCORED':
            col.prop(p, 'orientation_front', text="Face direction")
            front = col.row()
            front.enabled = bool(p.target_model)
            front.operator('fdm_mini_tools.front_from_view', text="Use current view as front", icon='VIEW_CAMERA')
            col.label(text="Automatic estimate: review the preview.")
        nav = col.row(); nav.enabled = bool(p.target_model)
        nav.operator('fdm_mini_tools.workflow_step', text="Next: Calculate", icon='TRIA_RIGHT').step = 'CALCULATE'


class FDMMINI_PT_calculate(_Step, Panel):
    bl_label = "3  Calculate supports"
    bl_idname = 'FDMMINI_PT_calculate'
    bl_order = 3
    workflow_step = 'CALCULATE'

    def draw(self, context):
        p = context.scene.fdm_mini_tools
        layout = self.layout
        method = layout.column(); method.enabled = not p.progress_active
        method.prop(p, 'support_strategy', text="Method")
        col = layout.column()
        col.enabled = bool(p.target_model) and not p.progress_active
        if p.support_strategy == 'FDM_TREE':
            col.prop(p, 'optimization_auto_compare', text="Compare orientations and splits")
        compare = p.support_strategy == 'FDM_TREE' and p.optimization_auto_compare
        if compare:
            col.prop(p, 'optimization_split_mode', text="Splitting")
            if p.optimization_split_mode != 'OFF':
                col.prop(p, 'optimization_max_parts', text="Max. parts")
                col.prop(p, 'optimization_joint_type', text="Connection")
                if p.optimization_joint_type == 'FLAT':
                    col.label(text="Cut face on bed; no alignment key.")
                    col.label(text="Additional supports without a shared raft.")
                else:
                    col.label(text="Hemispheres with matching sockets.")
            if p.optimization_split_mode == 'MANUAL':
                col.prop(p, 'optimization_cut_plane', text="Cutting plane")
                col.operator('fdm_mini_tools.optimization_plane', text="Create cutting plane")
            col.label(text="With Orca: last measured about 5-6 minutes.", icon='TIME')
            col.label(text="Compares source, orientation and splits.")
            button = col.column(); button.scale_y = 1.35
            button.operator('fdm_mini_tools.optimization_run', text="Calculate and compare variants", icon='PLAY')
        else:
            col.label(text="Single model; no variants or Orca.")
            col.label(text="Restarts from the original STL.")
            button = col.column(); button.scale_y = 1.35
            button.enabled = bool(p.last_import_path)
            button.operator('fdm_mini_tools.workflow_single', text="Prepare single model", icon='PLAY')
        if p.ui_level != 'SIMPLE':
            col.separator()
            col.label(text="Edit the current source mesh manually:")
            manual = col.column(); manual.enabled = p.ui_selected_variant == 'ORIGINAL'
            if p.ui_selected_variant != 'ORIGINAL':
                col.label(text="View the source model in step 4 first.")
            manual.operator('fdm_mini_tools.orient_current', text="Apply orientation only")
            manual.operator('fdm_mini_tools.generate_supports', text="Support current orientation only")


class FDMMINI_PT_review(_Step, Panel):
    bl_label = "4  Review result"
    bl_idname = 'FDMMINI_PT_review'
    bl_order = 4
    workflow_step = 'REVIEW'

    def draw(self, context):
        p = context.scene.fdm_mini_tools
        state = workflow_state(p)
        layout = self.layout
        if state['rows'] and p.target_model and p.optimization_report:
            col = layout.column(); col.enabled = not p.progress_active
            col.operator('fdm_mini_tools.optimization_show', text="View source model").candidate = 'ORIGINAL'
            names = {'KEEP': "Current orientation", 'AUTO': "Automatic orientation"}
            for row in state['rows']:
                cid = row['id']
                box = col.box()
                label = names.get(cid, "Split: " + cid.removeprefix('SPLIT_') + " parts")
                box.operator('fdm_mini_tools.optimization_show', text=label,
                             depress=p.ui_selected_variant == cid).candidate = cid
                if 'unresolved_tips' in row:
                    box.label(text=i18n.format_iface('{v0} unresolved contacts | {v1} low points', v0=row['unresolved_tips'], v1=row.get('missing_minima', 0)))
                    box.label(text=i18n.format_iface('Total material: {v0:.2f} cm3', v0=row.get('filament_mm3', 0) / 1000))
                box.label(text="Incomplete preview" if row.get('incomplete', True) else "Geometry checked")
                if row.get('parts_count', 1) > 1:
                    op = box.operator('fdm_mini_tools.optimization_show', text="View assembly")
                    op.candidate = cid; op.assembly = True
            if p.optimization_status:
                layout.label(text=p.optimization_status[:75])
        if not (state['variant'] or state['generated']):
            layout.label(text="Source shown: no print result selected yet.", icon='INFO')
            return
        layout.label(text="Shown: " + (p.ui_selected_variant if state['variant'] else "Single model"))
        if state['variant']:
            layout.label(text="Assembly view" if p.ui_variant_assembly else "Print orientation")
        if state['incomplete']:
            _notice(layout, "Contact gaps: not cleared for printing.", True)
        if p.support_strategy == 'FDM_TREE' or state['variant']:
            layout.label(text=i18n.format_iface('{v0} rooted contacts', v0=p.analysis_tree_rooted_tips))
            _notice(layout, i18n.format_iface('{v0} unresolved contacts', v0=p.analysis_tree_unresolved_tips), bool(p.analysis_tree_unresolved_tips))
            _notice(layout, i18n.format_iface('{v0} unsupported low points', v0=p.analysis_tree_missing_minima), bool(p.analysis_tree_missing_minima))
            if p.analysis_tree_missing_patches:
                _notice(layout, i18n.format_iface('{v0} additional review regions', v0=p.analysis_tree_missing_patches), True)
            if p.analysis_tree_unstable_stems:
                _notice(layout, i18n.format_iface('{v0} unsupported stem spans', v0=p.analysis_tree_unstable_stems), True)
        if p.analysis_support_nonmanifold:
            _notice(layout, i18n.format_iface('{v0} open support edges', v0=p.analysis_support_nonmanifold), True)
        layout.label(text="Physical print quality is unverified.", icon='INFO')
        if p.target_model and p.target_model.get('fdm_preparation_warning'):
            _notice(layout, "Mesh rebuild rejected; original shape retained.", True)
        nav = layout.row(); nav.enabled = not p.progress_active
        nav.operator('fdm_mini_tools.workflow_step', text="Next: Export", icon='TRIA_RIGHT').step = 'EXPORT'
        if state['generated'] and not state['variant']:
            layout.operator('fdm_mini_tools.analyze', text="Check result again", icon='VIEWZOOM')


class FDMMINI_PT_export(_Step, Panel):
    bl_label = "5  Files for Orca"
    bl_idname = 'FDMMINI_PT_export'
    bl_order = 5
    workflow_step = 'EXPORT'

    def draw(self, context):
        p = context.scene.fdm_mini_tools
        state = workflow_state(p)
        layout = self.layout
        if state['variant']:
            layout.label(text="3MF and STL files are in the variant folder.")
            if state['incomplete']:
                _notice(layout, "Files are marked as incomplete previews.", True)
            col = layout.column(); col.enabled = not p.progress_active
            col.operator('fdm_mini_tools.variant_files', text="Open files for the displayed variant", icon='FILE_FOLDER')
            return
        if not state['generated']:
            layout.label(text="Calculate or select a print result first.")
            return
        layout.prop(p, 'export_directory', text="Output folder")
        layout.prop(p, 'save_blend', text="Also save Blender scene")
        if p.support_strategy == 'FDM_TREE' and state['incomplete']:
            _notice(layout, "Preview export only: contact gaps remain.", True)
            layout.prop(p, 'allow_incomplete_tree_export', text="Allow incomplete preview export")
        col = layout.column()
        col.enabled = not p.progress_active and (not state['incomplete'] or p.allow_incomplete_tree_export or p.support_strategy != 'FDM_TREE')
        col.scale_y = 1.25
        col.operator('fdm_mini_tools.export', text="Export 3MF + STL", icon='EXPORT')
        if p.status_text and p.status_text != 'Ready':
            layout.label(text=p.status_text[:75], icon='INFO')


class FDMMINI_PT_settings(_Step, Panel):
    bl_label = "More settings and diagnostics"
    bl_idname = 'FDMMINI_PT_settings'
    bl_order = 6
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        p = context.scene.fdm_mini_tools
        return p.ui_level in {'ADVANCED', 'EXPERT'}

    def draw(self, context):
        p = context.scene.fdm_mini_tools
        layout = self.layout
        layout.enabled = not p.progress_active
        tree = p.support_strategy == 'FDM_TREE'
        layout.prop(p, 'do_optimize', text="Single model: enhance details")
        if p.do_optimize:
            layout.prop(p, 'optimizer_strength', text="Optimization")
        layout.label(text="Variant comparison uses the source geometry.")
        _grid(layout, p, ('lift_mm', 'overhang_angle', 'use_raft', 'do_supports'))
        if tree:
            _grid(layout, p, ('tree_required_minima', 'tree_complete_contacts', 'tree_guided_recovery',
                'tree_reuse_branches', 'tree_stabilize_stems', 'tree_route_mode', 'tree_layer_height',
                'touch_diameter', 'touch_depth', 'neck_diameter', 'tree_tip_cone_length',
                'tree_tip_neck_length', 'max_neck_angle', 'tree_branch_diameter', 'tree_trunk_diameter',
                'tree_model_clearance', 'tree_max_branch_angle', 'tree_merge_distance', 'tree_ground_search_radius',
                'tree_stem_slenderness', 'tree_stem_max_diameter'))
        else:
            _grid(layout, p, ('touch_diameter', 'touch_depth', 'neck_diameter', 'neck_length',
                'pillar_diameter', 'base_diameter', 'base_height', 'spacing', 'use_trees', 'use_trusses'))
        box = layout.box(); box.label(text="Comparison and calibration")
        for prop in ('optimization_profile', 'optimization_directory', 'optimization_orca'):
            box.prop(p, prop)
        box.operator('fdm_mini_tools.optimization_calibration', text="Create bridge and fit test")
        if p.optimization_joint_type == 'HEMISPHERE':
            box.prop(p, 'optimization_clearance')
            box.label(text="Hemisphere fit requires a print test.")
        if tree:
            layout.prop(p, 'tree_show_missing', text="Mark gaps during generation")
        _grid(layout, p, ('export_3mf', 'do_final_manifold_repair', 'use_level_cube'))
        if p.ui_level == 'EXPERT':
            FDMMINI_PT_main.draw_expert(layout, p, tree)
            layout.label(text=p.analysis_text[:80])
            layout.label(text=i18n.format_iface('MINI open edges: {v0}', v0=p.analysis_mini_nonmanifold))
            layout.label(text=i18n.format_iface('Support-Faces: {v0}', v0=p.analysis_support_faces))


def _draw_expert(layout, p, is_tree):
    box = layout.box()
    box.label(text="Expert: Mesh and geometry")
    _grid(box, p, (
        'do_cleanup', 'do_detail_enhancement', 'do_surface_smooth',
        'do_voxel_remesh', 'do_retriangulate', 'cleanup_merge_distance',
        'groove_depth', 'ridge_height', 'detail_detection_min',
        'detail_detection_max', 'detail_widen_rings', 'smooth_factor',
        'smooth_iterations', 'voxel_size', 'resolution',
    ))
    box.separator()
    box.label(text="Orientation")
    _grid(box, p, ('do_orientation', 'tilt_x', 'tilt_y', 'lift_mm'))

    box = layout.box()
    box.label(text="Expert: Supports")
    if is_tree:
        _grid(box, p, (
            'tree_contact_limit', 'spacing', 'safe_distance',
            'branch_descent', 'tree_ground_search_step',
            'tree_merge_rounds', 'base_diameter', 'base_height',
        ))
        box.prop(p, 'tree_contact_backend', text="Contact sampler")
        box.prop(p,'tree_route_budget')
        box.prop(p,'tree_stem_min_length')
        box.prop(p,'tree_budget_enabled')
        if p.tree_budget_enabled:
            box.prop(p,'tree_recovery_seconds')
            box.prop(p,'tree_recovery_region_seconds')
        if p.tree_contact_backend == 'NATIVE_EXPERIMENTAL':
            line = box.row()
            line.alert = True
            line.label(text="Experimental: compare with SLASG first", icon='ERROR')
    else:
        _grid(box, p, (
            'use_islands', 'truss_diameter', 'truss_minimum_height',
            'truss_spacing', 'truss_top_spacing', 'truss_distance_limit',
            'truss_angle', 'tree_merge_distance', 'branch_descent',
            'safe_distance', 'max_neck_angle',
        ))
        box.prop(p, 'validate_support_contacts')
        if p.validate_support_contacts:
            box.prop(p, 'auto_fix_contact_gaps')
            _grid(box, p, ('contact_tolerance', 'tip_overlap', 'max_contact_extension'))
        box.prop(p, 'slasg_blend_path', text='SLASG Override')
        bundled = core.bundled_slasg_path()
        if not bundled.is_file():
            warn = box.row()
            warn.alert = True
            warn.label(text="Classic .blend resource is missing", icon='ERROR')

    box = layout.box()
    box.label(text="Expert: Raft and export")
    _grid(box, p, (
        'raft_expand_width', 'raft_floor_thickness',
        'raft_wall_height', 'raft_wall_thickness',
        'manifold_repair_mode', 'manifold_hole_max_edges',
        'manifold_mini_voxel_size', 'manifold_support_voxel_size',
        'level_cube_size', 'level_cube_height', 'level_cube_margin',
    ))
    if not is_tree:
        box.prop(p, 'perforate_raft')
        if p.perforate_raft:
            _grid(box, p, (
                'raft_hole_diameter', 'raft_hole_spacing',
                'raft_hole_edge_keepout', 'raft_hole_pillar_keepout',
            ))
    else:
        box.label(text="Tree raft: perforation not implemented")
    box.operator('fdm_mini_tools.validate_contacts', text="Classic contact validation")

FDMMINI_PT_main.draw_expert = staticmethod(_draw_expert)

classes = (FDMMINI_PT_main, FDMMINI_PT_model, FDMMINI_PT_profile, FDMMINI_PT_calculate, FDMMINI_PT_review, FDMMINI_PT_export, FDMMINI_PT_settings)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
