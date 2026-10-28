
import bpy
import os
import datetime
import json
from pathlib import Path
from bpy.types import Operator
from bpy.props import StringProperty, BoolProperty
from bpy_extras.io_utils import ImportHelper

from . import core, contacts, orientation
from mathutils import Vector, Matrix
from .preferences import ADDON_ID


def get_prefs(context):
    addon = context.preferences.addons.get(ADDON_ID)
    return addon.preferences if addon else None

def validate_slasg(context):
    props = context.scene.fdm_mini_tools
    return core.resolve_slasg_path(props.slasg_blend_path)


def _record_progress(percent,step,active=True,error=None):
    # GUI painting can be blocked by synchronous Blender operations. Preserve
    # the actual stage independently, without background test runs overwriting it.
    if bpy.app.background:return
    try:
        from . import version
        directory=bpy.utils.user_resource('CONFIG')
        if not directory:return
        target=Path(directory)/'fdm_mini_tools_progress.json'
        temporary=target.with_suffix('.json.tmp')
        data=dict(pid=os.getpid(),updated_at=datetime.datetime.now().astimezone().isoformat(),
            percent_estimate=float(percent),step=str(step),active=bool(active),error=error,
            commit=version.installed_build()['commit'])
        temporary.write_text(json.dumps(data,indent=2),encoding='utf-8')
        temporary.replace(target)
    except (OSError,ValueError,TypeError):
        pass


def _begin_progress(context, props, step="Starting"):
    props.progress_active = True
    props.progress_percent = 0.0
    props.progress_step = step
    props.progress_error = ""
    _record_progress(0,step)
    context.window_manager.progress_begin(0, 100)
    _redraw_progress(context)


def _redraw_progress(context):
    try:
        if context.area:
            context.area.tag_redraw()
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
        # Force a UI swap so long blocking Blender operations still show the
        # last progress update instead of looking completely frozen.
        if not bpy.app.background:
            bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
    except Exception:
        pass


def _progress_callback(context, props):
    last = {"percent": -1.0, "step": None}

    def update(percent, step):
        percent = max(0.0, min(100.0, float(percent)))
        _record_progress(percent,step)
        props.progress_percent = percent
        props.progress_step = str(step)
        try:
            context.window_manager.progress_update(percent)
        except Exception:
            pass

        # Avoid excessive redraws during future fine-grained operations.
        if (
            abs(percent - last["percent"]) >= 0.5
            or step != last["step"]
        ):
            last["percent"] = percent
            last["step"] = step
            print(f"[FDM Mini Tools] {percent:5.1f}% - {step}",flush=True)
            _redraw_progress(context)

    return update


def _finish_progress(context, props, success=True, error=None):
    try:
        context.window_manager.progress_end()
    except Exception:
        pass

    if success:
        props.progress_percent = 100.0
        props.progress_step = "Done"
        props.progress_error = ""
    else:
        props.progress_step = "Error"
        props.progress_error = str(error or "Unknown error")

    props.progress_active = False
    _record_progress(props.progress_percent,props.progress_step,active=False,error=props.progress_error or None)
    _redraw_progress(context)




def _reset_comparison_ui(p):
    p.ui_selected_variant='ORIGINAL'
    p.ui_variant_assembly=False
    p.optimization_report=''
    p.optimization_results_json='[]'
    p.optimization_status=''


def _cache_comparison_ui(p, report):
    p.optimization_results_json=json.dumps([dict(id=row['id'],
        incomplete=row['incomplete'],parts_count=row.get('parts_count',1),
        unresolved_tips=row.get('unresolved_tips',0),
        missing_minima=sum(part['tree'].get('required_minima',{}).get('missing',0) for part in row['pieces']),
        filament_mm3=row.get('total_filament_mm3',0)) for row in report['candidates']])


class FDMMINI_OT_workflow_step(Operator):
    bl_idname='fdm_mini_tools.workflow_step'
    bl_label="Next workflow step"
    step: StringProperty(default='MODEL')

    def execute(self,context):
        if self.step not in {'MODEL','PROFILE','CALCULATE','REVIEW','EXPORT'}:
            return {'CANCELLED'}
        context.scene.fdm_mini_tools.ui_workflow_step=self.step
        return {'FINISHED'}


class FDMMINI_OT_workflow_single(Operator):
    bl_idname='fdm_mini_tools.workflow_single'
    bl_label="Prepare single model"
    bl_description="Reload the original STL, optimize, orient and support it; no variant comparison or Orca"

    def execute(self,context):
        p=context.scene.fdm_mini_tools
        previous=p.optimization_auto_compare
        previous_export=p.auto_export
        p.optimization_auto_compare=False
        p.auto_export=False
        try:
            result=bpy.ops.fdm_mini_tools.prepare_current()
            if result=={'FINISHED'}:
                p.ui_workflow_step='REVIEW'
            return result
        finally:
            p.optimization_auto_compare=previous
            p.auto_export=previous_export


class FDMMINI_OT_variant_files(Operator):
    bl_idname='fdm_mini_tools.variant_files'
    bl_label="Open variant files"
    bl_description="Open the displayed variant folder containing generated 3MF/STL files"

    def execute(self,context):
        p=context.scene.fdm_mini_tools
        try:
            report=json.loads(Path(bpy.path.abspath(p.optimization_report)).read_text(encoding='utf-8'))
            row=next(r for r in report['candidates'] if r['id']==p.ui_selected_variant)
            project=Path(row['project'])
            if not project.is_file():
                raise ValueError("Variant files are missing; run comparison again")
            return bpy.ops.wm.path_open(filepath=str(project.parent))
        except Exception as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


class FDMMINI_OT_import(Operator, ImportHelper):
    bl_idname = "fdm_mini_tools.import_mini"
    bl_label = "Import Mini"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".stl"
    filter_glob: StringProperty(default="*.stl", options={"HIDDEN"})

    def execute(self, context):
        props = context.scene.fdm_mini_tools
        core.clear_scene(purge=False)
        core.configure_mm_units()
        obj = core.import_stl(self.filepath)
        props.target_model = obj
        _reset_comparison_ui(props)
        props.analysis_text='Not analyzed'
        props.progress_error=''
        props.progress_percent=0
        props.last_import_path = self.filepath
        props.status_text = f"Imported {Path(self.filepath).name}"
        props.ui_workflow_step='PROFILE'
        return {"FINISHED"}


class FDMMINI_OT_import_one_click(Operator, ImportHelper):
    bl_idname = "fdm_mini_tools.import_one_click"
    bl_label = "Import + One Click Prepare"
    bl_description = "Choose an STL and run the complete preparation pipeline"
    bl_options = {"REGISTER"}

    filename_ext = ".stl"
    filter_glob: StringProperty(default="*.stl", options={"HIDDEN"})

    def execute(self, context):
        props = context.scene.fdm_mini_tools
        slasg = validate_slasg(context)
        if props.do_supports and contacts.requires_slasg(core.config_from_props(props)) and not slasg:
            self.report({"ERROR"}, "Bundled SLASG library is missing. Reinstall the add-on or select a custom SLASG .blend.")
            return {"CANCELLED"}

        _reset_comparison_ui(props)
        _begin_progress(context, props, "Starting One Click")
        progress = _progress_callback(context, props)

        try:
            cfg = core.config_from_props(props)
            if _early_variant_comparison(context,props,self.filepath,slasg,cfg,progress):
                return {"FINISHED"}
            model, support, orient, stats = core.prepare_model(
                self.filepath,
                slasg,
                config=cfg,
                optimize=props.do_optimize,
                optimizer_strength=props.optimizer_strength,
                optimization_config=core.optimization_config_from_props(props),
                orientation_mode=props.orientation_mode if props.do_orientation else "KEEP",
                tilt_x=props.tilt_x,
                tilt_y=props.tilt_y,
                lift=props.lift_mm,
                generate_supports=props.do_supports,
                clear=True,
                progress=progress,
            )
            props.target_model = model
            props.support_object = support
            props.last_import_path = self.filepath
            _store_stats(props, stats)

            if props.auto_export and support:
                out = bpy.path.abspath(props.export_directory) if props.export_directory else None
                core.export_outputs(
                    model,
                    support,
                    self.filepath,
                    out,
                    save_blend=props.save_blend,
                    use_level_cube=props.use_level_cube,
                    level_cube_size=props.level_cube_size,
                    level_cube_height=props.level_cube_height,
                    level_cube_margin=props.level_cube_margin,
                    export_3mf=props.export_3mf,
                    use_raft=props.use_raft,
                    raft_floor_thickness=props.raft_floor_thickness,
                    perforate_raft=props.perforate_raft,
                    raft_hole_diameter=props.raft_hole_diameter,
                    raft_hole_spacing=props.raft_hole_spacing,
                    raft_hole_edge_keepout=props.raft_hole_edge_keepout,
                    raft_hole_pillar_keepout=props.raft_hole_pillar_keepout,
                    do_final_manifold_repair=props.do_final_manifold_repair,
                    manifold_repair_mode=props.manifold_repair_mode,
                    manifold_hole_max_edges=props.manifold_hole_max_edges,
                    manifold_mini_voxel_size=props.manifold_mini_voxel_size,
                    manifold_support_voxel_size=props.manifold_support_voxel_size,
                    allow_incomplete_tree_export=props.allow_incomplete_tree_export,
                    progress=progress,
                )

            props.status_text = f"Prepared {Path(self.filepath).name}"
            _finish_progress(context, props, success=True)
            self.report({"INFO"}, "FDM Mini Tools: One Click preparation complete.")
            return {"FINISHED"}
        except Exception as exc:
            props.status_text = f"Error: {exc}"
            _finish_progress(context, props, success=False, error=exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


def _store_stats(props, stats):
    props.analysis_overhang_faces = stats["overhang_faces"]
    props.analysis_overhang_area = stats["overhang_area"]
    props.analysis_support_vertices = stats["support_vertices"]
    props.analysis_support_faces = stats["support_faces"]
    contacts = stats.get("contacts") or {}
    props.analysis_contact_candidates = contacts.get("candidates", 0)
    props.analysis_contact_fixed = contacts.get("fixed", 0)
    props.analysis_contact_unresolved = contacts.get("unresolved", 0)
    tree = stats.get("tree") or {}
    props.analysis_tree_contacts = tree.get("contacts", 0)
    props.analysis_tree_merges = tree.get("merges", 0)
    props.analysis_tree_rooted_tips = tree.get("rooted_tips", 0)
    props.analysis_tree_unresolved_tips = tree.get("unresolved_tips", 0)
    props.analysis_tree_missing_patches = tree.get("contact_audit",{}).get("missing_count",0)
    props.analysis_tree_missing_minima = tree.get('required_minima',{}).get('missing',0)
    props.analysis_tree_unstable_stems=tree.get('stability',{}).get('unresolved',0)
    props.analysis_tree_segments = tree.get("segments", 0)
    props.analysis_mini_nonmanifold = stats.get("mini_nonmanifold", 0)
    props.analysis_support_nonmanifold = stats.get("support_nonmanifold", 0)
    props.analysis_text = (
        f"{stats['overhang_faces']} overhang faces | "
        f"{stats['support_faces']} support faces"
    )


def _variant_analysis(original,row):
    result=dict(original)
    trees=[piece['tree'] for piece in row['pieces']]
    tree={key:sum(t.get(key,0) for t in trees) for key in
          ('contacts','merges','rooted_tips','unresolved_tips','segments')}
    for key,field in (('contact_audit','missing_count'),('required_minima','missing'),('stability','unresolved')):
        tree[key]={field:sum(t.get(key,{}).get(field,0) for t in trees)}
    result['tree']=tree
    result['support_vertices']=sum(t.get('mesh_qa',{}).get('vertices',0) for t in trees)
    result['support_faces']=sum(t.get('mesh_qa',{}).get('triangles',0) for t in trees)
    result['support_nonmanifold']=sum(t.get('mesh_qa',{}).get('nonmanifold_edges',0) for t in trees)
    return result


def _early_variant_comparison(context, props, source, slasg, cfg, progress):
    if not (props.optimization_auto_compare and props.optimization_split_mode=='AUTO'
            and props.do_supports and props.do_orientation and cfg.get('support_strategy')=='FDM_TREE'):
        return False
    # Candidate generation precedes expensive support recovery. Preserve source
    # geometry rather than remeshing it before the variant comparison.
    model,_,_,stats=core.prepare_model(source,slasg,config=cfg,optimize=False,
        orientation_mode='KEEP',lift=props.lift_mm,generate_supports=False,
        clear=True,progress=progress)
    props.last_import_path=str(source);props.target_model=model;props.support_object=None
    _store_stats(props,stats)
    if props.optimization_directory.startswith('//') and not bpy.data.filepath:
        props.optimization_directory=str(Path(source).resolve().parent/props.optimization_directory[2:])
    if bpy.ops.fdm_mini_tools.optimization_run()!={'FINISHED'}:
        raise RuntimeError("Variant comparison failed; see the comparison report")
    report=json.loads(Path(props.optimization_report).read_text(encoding='utf-8'))
    chosen=report.get('recommended')
    if not chosen and report['candidates']:
        def risk(row):
            missing=sum(p['tree'].get('required_minima',{}).get('missing',0) for p in row['pieces'])
            return (missing,row['unresolved_tips'],row['total_filament_mm3'],row['id'])
        chosen=min(report['candidates'],key=risk)['id']
    if chosen:
        row=next(r for r in report['candidates'] if r['id']==chosen)
        _store_stats(props,_variant_analysis(stats,row))
        bpy.ops.fdm_mini_tools.optimization_show(candidate=chosen)
        props.status_text=("Geometry-checked variant: " if report.get('recommended') else
                           "Incomplete preview: ")+chosen
    if props.save_blend:
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(props.optimization_report).with_name('comparison.blend')))
    return True


class FDMMINI_OT_prepare_current(Operator):
    bl_idname = "fdm_mini_tools.prepare_current"
    bl_label = "AUTO PREPARE CURRENT MINI"
    bl_description = "Optimize, orient, generate supports, analyze and optionally export"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.fdm_mini_tools
        source = props.last_import_path
        if not source or not os.path.exists(source):
            self.report({"ERROR"}, "Use Import + One Click for a file-based preparation.")
            return {"CANCELLED"}

        slasg = validate_slasg(context)
        if props.do_supports and contacts.requires_slasg(core.config_from_props(props)) and not slasg:
            self.report({"ERROR"}, "Bundled SLASG library is missing. Reinstall the add-on or select a custom SLASG .blend.")
            return {"CANCELLED"}

        # Re-run from source to make One Click deterministic/idempotent.
        _reset_comparison_ui(props)
        _begin_progress(context, props, "Starting One Click")
        progress = _progress_callback(context, props)
        try:
            cfg = core.config_from_props(props)
            if _early_variant_comparison(context,props,source,slasg,cfg,progress):
                return {"FINISHED"}
            model, support, orient, stats = core.prepare_model(
                source,
                slasg,
                config=cfg,
                optimize=props.do_optimize,
                optimizer_strength=props.optimizer_strength,
                optimization_config=core.optimization_config_from_props(props),
                orientation_mode=props.orientation_mode if props.do_orientation else "KEEP",
                tilt_x=props.tilt_x,
                tilt_y=props.tilt_y,
                lift=props.lift_mm,
                generate_supports=props.do_supports,
                clear=True,
                progress=progress,
            )
            props.target_model = model
            props.support_object = support
            _store_stats(props, stats)

            if props.auto_export and support:
                out = bpy.path.abspath(props.export_directory) if props.export_directory else None
                core.export_outputs(
                    model,
                    support,
                    source,
                    out,
                    save_blend=props.save_blend,
                    use_level_cube=props.use_level_cube,
                    level_cube_size=props.level_cube_size,
                    level_cube_height=props.level_cube_height,
                    level_cube_margin=props.level_cube_margin,
                    export_3mf=props.export_3mf,
                    use_raft=props.use_raft,
                    raft_floor_thickness=props.raft_floor_thickness,
                    perforate_raft=props.perforate_raft,
                    raft_hole_diameter=props.raft_hole_diameter,
                    raft_hole_spacing=props.raft_hole_spacing,
                    raft_hole_edge_keepout=props.raft_hole_edge_keepout,
                    raft_hole_pillar_keepout=props.raft_hole_pillar_keepout,
                    do_final_manifold_repair=props.do_final_manifold_repair,
                    manifold_repair_mode=props.manifold_repair_mode,
                    manifold_hole_max_edges=props.manifold_hole_max_edges,
                    manifold_mini_voxel_size=props.manifold_mini_voxel_size,
                    manifold_support_voxel_size=props.manifold_support_voxel_size,
                    allow_incomplete_tree_export=props.allow_incomplete_tree_export,
                    progress=progress,
                )

            props.status_text = "One Click complete"
            _finish_progress(context, props, success=True)
            return {"FINISHED"}
        except Exception as exc:
            props.status_text = f"Error: {exc}"
            _finish_progress(context, props, success=False, error=exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


class FDMMINI_OT_analyze(Operator):
    bl_idname = "fdm_mini_tools.analyze"
    bl_label = "Analyze"

    def execute(self, context):
        props = context.scene.fdm_mini_tools
        if not props.target_model:
            self.report({"ERROR"}, "No MINI object.")
            return {"CANCELLED"}

        _begin_progress(context, props, "Analyzing")
        progress = _progress_callback(context, props)
        try:
            progress(15, "Analyze MINI / supports")
            stats = core.analyze(
                props.target_model, props.support_object, props.overhang_angle
            )
            if props.support_object and props.support_object.get("fdm_tree_strategy"):
                s_obj = props.support_object
                stats["tree"] = {
                    "contacts": int(s_obj.get("fdm_tree_contacts", 0)),
                    "merges": int(s_obj.get("fdm_tree_merges", 0)),
                    "rooted_tips": int(s_obj.get("fdm_tree_rooted_tips", 0)),
                    "unresolved_tips": int(s_obj.get("fdm_tree_unresolved_tips", 0)),
                    "rooted_components": int(s_obj.get("fdm_tree_rooted_components", 0)),
                    "segments": int(s_obj.get("fdm_tree_segments", 0)),
                }
                audit=json.loads(s_obj.get('fdm_tree_contact_audit','{}'))
                stats['tree']['contact_audit']=audit
                stats['tree']['required_minima']=audit.get('required_minima',{})
                stats['tree']['stability']=audit.get('stability',{})
            progress(90, "Update analysis")
            _store_stats(props, stats)
            progress(100, "Analysis complete")
            _finish_progress(context, props, success=True)
            return {"FINISHED"}
        except Exception as exc:
            _finish_progress(context, props, success=False, error=exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


class FDMMINI_OT_export(Operator):
    bl_idname = "fdm_mini_tools.export"
    bl_label = "Export for Orca"

    def execute(self, context):
        props = context.scene.fdm_mini_tools
        if props.ui_selected_variant!='ORIGINAL' and props.optimization_report:
            self.report({'ERROR'}, "Displayed variant: open existing files in step 5")
            return {'CANCELLED'}
        if not props.target_model or not props.support_object:
            self.report({"ERROR"}, "Generate supports first.")
            return {"CANCELLED"}
        if not props.last_import_path:
            self.report({"ERROR"}, "No source filename is known.")
            return {"CANCELLED"}

        _begin_progress(context, props, "Exporting")
        progress = _progress_callback(context, props)
        out = bpy.path.abspath(props.export_directory) if props.export_directory else None
        try:
            paths = core.export_outputs(
            props.target_model,
            props.support_object,
            props.last_import_path,
            out,
            save_blend=props.save_blend,
            use_level_cube=props.use_level_cube,
            level_cube_size=props.level_cube_size,
            level_cube_height=props.level_cube_height,
            level_cube_margin=props.level_cube_margin,
            export_3mf=props.export_3mf,
            use_raft=props.use_raft,
            raft_floor_thickness=props.raft_floor_thickness,
            perforate_raft=props.perforate_raft,
            raft_hole_diameter=props.raft_hole_diameter,
            raft_hole_spacing=props.raft_hole_spacing,
            raft_hole_edge_keepout=props.raft_hole_edge_keepout,
            raft_hole_pillar_keepout=props.raft_hole_pillar_keepout,
            do_final_manifold_repair=props.do_final_manifold_repair,
            manifold_repair_mode=props.manifold_repair_mode,
            manifold_hole_max_edges=props.manifold_hole_max_edges,
            manifold_mini_voxel_size=props.manifold_mini_voxel_size,
                manifold_support_voxel_size=props.manifold_support_voxel_size,
                    allow_incomplete_tree_export=props.allow_incomplete_tree_export,
                progress=progress,
            )
            mini_nm = (paths.get("repair") or {}).get("mini") or {}
            sup_nm = (paths.get("repair") or {}).get("supports") or {}
            props.status_text = (
                f"Exported 3MF | non-manifold after repair: "
                f"MINI {mini_nm.get('after', '?')} / SUPPORTS {sup_nm.get('after', '?')}"
            )
            _finish_progress(context, props, success=True)
            self.report(
                {"INFO"},
                "Exported shared-coordinate 3MF + compatibility STLs."
            )
            return {"FINISHED"}
        except Exception as exc:
            _finish_progress(context, props, success=False, error=exc)
            props.status_text = f"Export error: {exc}"
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


class FDMMINI_OT_open_preferences(Operator):
    bl_idname = "fdm_mini_tools.open_preferences"
    bl_label = "Configure SLASG"

    def execute(self, context):
        bpy.ops.screen.userpref_show()
        context.preferences.active_section = "ADDONS"
        return {"FINISHED"}



class FDMMINI_OT_optimize_current(Operator):
    bl_idname = "fdm_mini_tools.optimize_current"
    bl_label = "Optimize Details"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.fdm_mini_tools
        if not p.target_model:
            self.report({"ERROR"}, "No MINI object.")
            return {"CANCELLED"}
        _begin_progress(context, p, "Starting optimization")
        progress = _progress_callback(context, p)
        try:
            if not p.do_optimize:
                p.status_text = "Optimization master switch is off"
                _finish_progress(context, p, success=True)
                self.report({"INFO"}, "Detail Optimization is disabled.")
                return {"FINISHED"}

            cfg = core.optimization_config_from_props(p)
            core.run_optimization_pipeline(
                p.target_model,
                cfg,
                progress=progress,
                start=0,
                end=100,
            )
            p.status_text = "Optimization pipeline complete"
            _finish_progress(context, p, success=True)
            return {"FINISHED"}
        except Exception as exc:
            _finish_progress(context, p, success=False, error=exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


class FDMMINI_OT_front_from_view(Operator):
    bl_idname = 'fdm_mini_tools.front_from_view'
    bl_label = "Use current view as front"
    bl_options = {'REGISTER','UNDO'}

    def execute(self, context):
        p = context.scene.fdm_mini_tools
        obj = p.target_model
        region = getattr(context.space_data, 'region_3d', None)
        if obj is None or region is None:
            self.report({'ERROR'}, "Open MINI in a 3D view")
            return {'CANCELLED'}
        front = obj.matrix_world.to_3x3().inverted_safe() @ (region.view_rotation @ Vector((0,0,1)))
        front.normalize()
        if Vector((front.x,front.y,0)).length < .2:
            self.report({'ERROR'}, "Use a front view rather than a top view")
            return {'CANCELLED'}
        obj[orientation.FRONT_KEY] = list(front)
        basis = obj.get('fdm_orientation_source_basis')
        source_front = (Matrix([basis[i:i+3] for i in (0,3,6)]).inverted_safe() @ front
                        if basis else front)
        p.orientation_front_vector = source_front.normalized()
        p.orientation_front_path = p.last_import_path
        p.orientation_front = 'VIEW'
        p.status_text = "Front direction saved; apply orientation next"
        return {'FINISHED'}


class FDMMINI_OT_orient_current(Operator):
    bl_idname = "fdm_mini_tools.orient_current"
    bl_label = "Orient Mini"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.fdm_mini_tools
        obj = p.target_model
        if not obj:
            self.report({"ERROR"}, "No MINI object.")
            return {"CANCELLED"}
        _begin_progress(context, p, "Orienting mini")
        progress = _progress_callback(context, p)
        try:
            progress(10, "Evaluate orientation")
            if p.orientation_mode == "SCORED":
                core.orient_scored(obj, p.lift_mm, p.overhang_angle, p.orientation_front)
            elif p.orientation_mode == "FIXED":
                core.orient_fixed(obj, p.tilt_x, p.tilt_y, p.lift_mm)
            else:
                core._place_lowest_at(obj, p.lift_mm)
                core.frame_object_in_viewports(obj)
            # Rotating only MINI invalidates existing collision/contact witnesses.
            core.clear_supplemental_supports()
            if p.support_object and p.support_object.name in bpy.data.objects:
                bpy.data.objects.remove(p.support_object, do_unlink=True)
            p.support_object = None
            progress(100, "Orientation complete")
            p.status_text = "Mini oriented; regenerate supports"
            _finish_progress(context, p, success=True)
            return {"FINISHED"}
        except Exception as exc:
            _finish_progress(context, p, success=False, error=exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


class FDMMINI_OT_generate_supports(Operator):
    bl_idname = "fdm_mini_tools.generate_supports"
    bl_label = "Generate Supports"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.fdm_mini_tools
        model = p.target_model
        if not model:
            self.report({"ERROR"}, "No MINI object.")
            return {"CANCELLED"}
        slasg = validate_slasg(context)
        if contacts.requires_slasg(core.config_from_props(p)) and not slasg:
            self.report({"ERROR"}, "Bundled SLASG library is missing. Reinstall the add-on or select a custom SLASG .blend.")
            return {"CANCELLED"}

        _begin_progress(context, p, "Generating supports")
        progress = _progress_callback(context, p)
        point_source = None
        # Do not destroy existing printable supports until replacement succeeds.
        previous_support = (
            p.support_object
            if p.support_object and p.support_object.name in bpy.data.objects
            else None
        )
        try:
            progress(5, "Prepare new supports")
            core.clear_supplemental_supports()

            cfg = core.config_from_props(p)
            strategy = cfg.get("support_strategy", "FDM_TREE")

            if strategy == "FDM_TREE":
                backend = contacts.backend_for(cfg)
                progress(15, f"Acquire Tree contacts: {backend}")
                point_source = contacts.create_tree_point_object(
                    model, cfg, slasg,
                    progress=lambda pct, step: progress(15 + pct * 0.25, step),
                )
            else:
                progress(15, "Load stable SLASG Classic")
                point_source, scatter, generator = core.append_slasg(slasg)
                progress(30, "Configure Classic supports")
                core.configure_slasg(model, point_source, scatter, generator, cfg)

            contact_stats = {
                "candidates": 0, "valid": 0, "gaps": 0,
                "fixed": 0, "unresolved": 0,
            }
            tree_stats = {
                "raw_points": 0, "contacts": 0, "rejected_points": 0,
                "merges": 0, "rooted_components": 0, "rooted_tips": 0,
                "unresolved_components": 0, "unresolved_tips": 0,
                "segments": 0,
            }

            if strategy == "FDM_TREE":
                progress(48, "Tree contact points ready")
                progress(55, "Plan grounded FDM tree")
                support, tree_stats = core.tree_support.generate_tree_supports(
                    model,
                    point_source,
                    cfg,
                    progress=lambda pct, step: progress(55 + pct * 0.30, step),
                )
                core.tree_support.remove_point_source(point_source)
                point_source = None
            else:
                support = point_source
                progress(55, "Generate classic SLASG supports")
                core.bake_scatter(support, scatter, enable_generator=True)
                point_source = None

                if p.validate_support_contacts:
                    progress(78, "Validate support contacts")
                    contact_stats = core.validate_and_fix_support_contacts(
                        model,
                        support,
                        tolerance=p.contact_tolerance,
                        overlap=p.tip_overlap,
                        max_extension=p.max_contact_extension,
                        auto_fix=p.auto_fix_contact_gaps,
                    )

            progress(90, "Analyze supports")
            # Validate new support before removing the previous working object.
            stats = core.analyze(model, support, p.overhang_angle)
            stats["contacts"] = contact_stats
            stats["tree"] = tree_stats
            _store_stats(p, stats)
            # Commit only after analysis succeeded.
            if previous_support is not None and previous_support != support:
                bpy.data.objects.remove(previous_support, do_unlink=True)
            support.name = "SUPPORTS"
            p.support_object = support
            _reset_comparison_ui(p)
            progress(100, "Supports complete")
            p.status_text = (
                "FDM Tree supports generated"
                if strategy == "FDM_TREE"
                else "Classic SLASG supports generated"
            )
            _finish_progress(context, p, success=True)
            return {"FINISHED"}
        except Exception as exc:
            if point_source is not None:
                try:
                    core.tree_support.remove_point_source(point_source)
                except Exception:
                    pass
            _finish_progress(context, p, success=False, error=exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


class FDMMINI_OT_validate_contacts(Operator):
    bl_idname = "fdm_mini_tools.validate_contacts"
    bl_label = "Validate / Fix Contacts"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.fdm_mini_tools
        if p.support_strategy == "FDM_TREE":
            self.report(
                {"INFO"},
                "FDM Tree tips are generated directly from the MINI surface; the legacy contact fixer is not used.",
            )
            return {"FINISHED"}
        if not p.target_model or not p.support_object:
            self.report({"ERROR"}, "MINI and SUPPORTS are required.")
            return {"CANCELLED"}

        _begin_progress(context, p, "Validating contacts")
        progress = _progress_callback(context, p)
        try:
            progress(20, "Scan support endpoints")
            contact_stats = core.validate_and_fix_support_contacts(
                p.target_model,
                p.support_object,
                tolerance=p.contact_tolerance,
                overlap=p.tip_overlap,
                max_extension=p.max_contact_extension,
                auto_fix=p.auto_fix_contact_gaps,
            )
            stats = core.analyze(
                p.target_model,
                p.support_object,
                p.overhang_angle,
            )
            stats["contacts"] = contact_stats
            stats["tree"] = {}
            _store_stats(p, stats)
            progress(100, "Contact validation complete")
            _finish_progress(context, p, success=True)
            return {"FINISHED"}
        except Exception as exc:
            _finish_progress(context, p, success=False, error=exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


class FDMMINI_OT_clear_supports(Operator):
    bl_idname = "fdm_mini_tools.clear_supports"
    bl_label = "Remove Supports"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.fdm_mini_tools
        core.clear_supplemental_supports()
        if p.support_object and p.support_object.name in bpy.data.objects:
            bpy.data.objects.remove(p.support_object, do_unlink=True)
        p.support_object = None
        p.status_text = "Supports removed"
        return {"FINISHED"}


class FDMMINI_OT_optimization_profile(Operator):
    bl_idname='fdm_mini_tools.optimization_profile'
    bl_label="Load Qidi mini profile"
    bl_description="Resolve inherited Orca profiles in an isolated copy"

    def execute(self,context):
        from . import print_profile
        p=context.scene.fdm_mini_tools
        try:
            if not p.target_model:
                raise ValueError("Import a mini first")
            base=(Path(p.last_import_path).resolve().parent/p.optimization_directory[2:]
                  if p.optimization_directory.startswith('//') and not bpy.data.filepath and p.last_import_path
                  else Path(bpy.path.abspath(p.optimization_directory)))
            directory=base/datetime.datetime.now().strftime('profile_%Y%m%d_%H%M%S_%f')
            directory.mkdir(parents=True)
            probe=directory/'profile_probe.stl'
            core.export_selected_stl(str(probe),[p.target_model])
            result=print_profile.resolve(bpy.path.abspath(p.optimization_orca),directory,probe)
            p.optimization_profile=str(directory/'profile.json')
            p.tree_layer_height=result['summary']['layer_mm']
            p.optimization_status=f"Profile: {result['summary']['layer_mm']:.2f} mm; bridge span is unverified"
            p.ui_workflow_step='CALCULATE'
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


class FDMMINI_OT_optimization_plane(Operator):
    bl_idname='fdm_mini_tools.optimization_plane'
    bl_label="Create cutting plane"
    bl_options={'REGISTER','UNDO'}

    def execute(self,context):
        p=context.scene.fdm_mini_tools
        if not p.target_model:
            self.report({'ERROR'},"Import a mini first");return {'CANCELLED'}
        bounds=core.bounds(p.target_model)
        obj=bpy.data.objects.new('MINI_SCHNITTEBENE',None)
        context.scene.collection.objects.link(obj)
        obj.empty_display_type='ARROWS';obj.empty_display_size=5
        obj.location=((bounds[0]+bounds[1])/2,(bounds[2]+bounds[3])/2,bounds[4]+.4*(bounds[5]-bounds[4]))
        obj['fdm_optimization_role']='CUT_PLANE'
        p.optimization_cut_plane=obj;p.optimization_split_mode='MANUAL'
        core.activate(obj)
        return {'FINISHED'}


class FDMMINI_OT_optimization_run(Operator):
    bl_idname='fdm_mini_tools.optimization_run'
    bl_label="Compare mini variants (experimental)"
    bl_description="Compare current orientation, automatic orientation and safe splits with SLASG and Orca; may take several minutes"

    def execute(self,context):
        from . import mini_optimizer
        p=context.scene.fdm_mini_tools
        if not p.target_model:
            self.report({'ERROR'},"Import a mini first");return {'CANCELLED'}
        _begin_progress(context,p,"Compare mini variants")
        try:
            if not p.optimization_profile or not Path(bpy.path.abspath(p.optimization_profile)).is_file():
                if bpy.ops.fdm_mini_tools.optimization_profile() != {'FINISHED'}:
                    raise RuntimeError("Could not load print profile")
            plane=None
            if p.optimization_split_mode=='MANUAL':
                if not p.optimization_cut_plane:
                    raise ValueError("Create and position cutting plane")
                obj=p.optimization_cut_plane
                normal=obj.matrix_world.to_3x3().inverted().transposed() @ Vector((0,0,1))
                plane=dict(center=list(obj.matrix_world.translation),normal=list(normal.normalized()))
            cfg=core.config_from_props(p);cfg['optimization_lift']=p.lift_mm
            directory=p.optimization_directory
            base=(Path(p.last_import_path).resolve().parent/directory[2:]
                  if directory.startswith('//') and not bpy.data.filepath and p.last_import_path
                  else Path(bpy.path.abspath(directory)))
            out=base/datetime.datetime.now().strftime('compare_%Y%m%d_%H%M%S_%f')
            result=mini_optimizer.optimize(p.target_model,bpy.path.abspath(p.optimization_profile),out,
                bpy.path.abspath(p.optimization_orca),cfg,
                max_parts=1 if p.optimization_split_mode=='OFF' else p.optimization_max_parts,
                clearance=p.optimization_clearance,joint_type=p.optimization_joint_type,front_mode=p.orientation_front,manual_plane=plane,
                progress=_progress_callback(context,p))
            p.optimization_report=str(out/'optimization.json')
            p.ui_selected_variant='ORIGINAL'
            p.ui_variant_assembly=False
            _cache_comparison_ui(p,result)
            p.optimization_status=(f"{len(result['candidates'])} comparisons; recommendation: {result['recommended'] or "no complete variant"}")
            if result['failures']:
                p.optimization_status+=f"; {len(result['failures'])} errors in the report"
            if not result['candidates']:
                raise RuntimeError("No variant passed all comparison checks; see the saved report")
            chosen=result.get('recommended') or min(result['candidates'],key=lambda row:(
                sum(part['tree'].get('required_minima',{}).get('missing',0) for part in row['pieces']),
                row.get('unresolved_tips',0),row.get('total_filament_mm3',0),row['id']))['id']
            if bpy.ops.fdm_mini_tools.optimization_show(candidate=chosen)!={'FINISHED'}:
                raise RuntimeError("Comparison finished, but the preview could not be loaded")
            _finish_progress(context,p,success=True)
            self.report({'INFO'},p.optimization_status)
            return {'FINISHED'}
        except Exception as exc:
            _finish_progress(context,p,success=False,error=exc)
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


class FDMMINI_OT_optimization_show(Operator):
    bl_idname='fdm_mini_tools.optimization_show'
    bl_label="Comparison preview"
    candidate: StringProperty(default='ORIGINAL')
    assembly: BoolProperty(default=False,options={'HIDDEN'})

    def execute(self,context):
        p=context.scene.fdm_mini_tools
        try:
            report=json.loads(Path(bpy.path.abspath(p.optimization_report)).read_text(encoding='utf-8'))
            row=None
            if self.candidate!='ORIGINAL':
                row=next(r for r in report['candidates'] if r['id']==self.candidate)
                if not bpy.data.collections.get(row['collection']) or any(
                        bpy.data.objects.get(part['object']) is None for part in row['pieces']):
                    raise ValueError("Variant objects are missing from this scene; run comparison again")
            for collection in bpy.data.collections:
                if collection.get('fdm_optimization_assembly_preview'):
                    collection.hide_viewport=True;collection.hide_render=True
            for row in report['candidates']:
                collection=bpy.data.collections.get(row['collection'])
                if collection:
                    collection.hide_viewport=row['id']!=self.candidate
                    collection.hide_render=row['id']!=self.candidate
            for obj in (p.target_model,p.support_object):
                if obj:obj.hide_set(self.candidate!='ORIGINAL')
            if self.candidate!='ORIGINAL':
                row=next(r for r in report['candidates'] if r['id']==self.candidate)
                obj=bpy.data.objects.get(row['pieces'][0]['object'])
                if self.assembly:
                    from . import mini_optimizer
                    key=p.optimization_report+'|'+self.candidate
                    collection=next((c for c in bpy.data.collections if c.get('fdm_optimization_assembly_key')==key),None)
                    if collection is None:
                        sources=[bpy.data.objects.get(part['object']) for part in row['pieces']]
                        if any(source is None for source in sources):
                            raise ValueError("Variant objects are missing from this scene; run comparison again")
                        objects=[]
                        try:
                            for source,part in zip(sources,row['pieces']):
                                copy=source.copy();copy.data=source.data.copy()
                                context.scene.collection.objects.link(copy)
                                copy.matrix_world=Matrix(part['assembly_from_print']) @ source.matrix_world
                                copy.name='ZUSAMMENBAU_'+source.name
                                copy['fdm_optimization_role']='ASSEMBLY_PREVIEW'
                                objects.append(copy)
                            collection=mini_optimizer._collection('FDM_ZUSAMMENBAU_'+self.candidate,objects)
                            collection['fdm_optimization_assembly_preview']=True
                            collection['fdm_optimization_assembly_key']=key
                        except Exception:
                            from . import mini_split
                            for copy in objects:mini_split.remove(copy)
                            raise
                    collection.hide_viewport=False;collection.hide_render=False
                    chosen=bpy.data.collections.get(row['collection'])
                    if chosen:chosen.hide_viewport=True;chosen.hide_render=True
                    context.view_layer.update()
                    obj=next(iter(collection.objects))
                shown=collection if self.assembly else bpy.data.collections.get(row['collection'])
                context.view_layer.update()
                if obj:core.frame_object_in_viewports(obj,additional=list(shown.all_objects))
                original=dict(overhang_faces=p.analysis_overhang_faces,overhang_area=p.analysis_overhang_area,
                              mini_nonmanifold=p.analysis_mini_nonmanifold)
                _store_stats(p,_variant_analysis(original,row))
            elif p.target_model:
                core.frame_object_in_viewports(p.target_model)
            _cache_comparison_ui(p,report)
            p.ui_workflow_step='REVIEW'
            p.ui_selected_variant=self.candidate
            p.ui_variant_assembly=self.assembly and self.candidate!='ORIGINAL'
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


class FDMMINI_OT_optimization_calibration(Operator):
    bl_idname='fdm_mini_tools.optimization_calibration'
    bl_label="Create bridge and fit test"
    bl_options={'REGISTER','UNDO'}

    def execute(self,context):
        from . import mini_split,mini_optimizer
        p=context.scene.fdm_mini_tools
        try:
            objects=mini_split.calibration_objects(p.optimization_clearance)
            directory=Path(bpy.path.abspath(p.optimization_directory))/datetime.datetime.now().strftime('calibration_%Y%m%d_%H%M%S_%f')
            directory.mkdir(parents=True)
            for obj in objects:
                core.export_selected_stl(str(directory/(obj.name+'.stl')),[obj])
            mini_optimizer._collection('FDM_KALIBRIERUNG',objects)
            p.optimization_status="Created 2/4/6/8/10/12/14 mm bridges and fit test; print testing pending"
            self.report({'INFO'},p.optimization_status);return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


classes = (
    FDMMINI_OT_workflow_step,
    FDMMINI_OT_workflow_single,
    FDMMINI_OT_variant_files,
    FDMMINI_OT_optimization_profile,
    FDMMINI_OT_optimization_plane,
    FDMMINI_OT_optimization_run,
    FDMMINI_OT_optimization_show,
    FDMMINI_OT_optimization_calibration,
    FDMMINI_OT_import,
    FDMMINI_OT_optimize_current,
    FDMMINI_OT_orient_current,
    FDMMINI_OT_front_from_view,
    FDMMINI_OT_generate_supports,
    FDMMINI_OT_validate_contacts,
    FDMMINI_OT_clear_supports,
    FDMMINI_OT_import_one_click,
    FDMMINI_OT_prepare_current,
    FDMMINI_OT_analyze,
    FDMMINI_OT_export,
    FDMMINI_OT_open_preferences,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
