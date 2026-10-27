"""Exercise actual panel draw calls for all UI levels using real Blender properties."""
import argparse,json,sys
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--addon-root',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:]);sys.path.insert(0,str(args.addon_root.resolve().parent))
import bpy,fdm_mini_tools
from fdm_mini_tools import version,ui,preferences
assert Path(fdm_mini_tools.__file__).resolve().parent==args.addon_root.resolve()
identity=version.installed_build();assert identity['verified'],identity
if not hasattr(bpy.types.Scene,'fdm_mini_tools'):fdm_mini_tools.register()
class Layout:
 def __init__(self,labels):self.labels=labels
 def label(self,**kwargs):self.labels.append(kwargs.get('text',''))
 def __getattr__(self,name):return lambda *args,**kwargs:Layout(self.labels)
labels=[];panel=type('PanelProxy',(),{'layout':Layout(labels),'draw_expert':staticmethod(ui.FDMMINI_PT_main.draw_expert)})()
props=bpy.context.scene.fdm_mini_tools
for level in ['SIMPLE','ADVANCED','EXPERT']:
 for strategy in ['SLASG_CLASSIC','FDM_TREE']:
  props.ui_level=level;props.support_strategy=strategy;labels.clear()
  for step in ('MODEL','PROFILE','CALCULATE','REVIEW','EXPORT'):
   props.ui_workflow_step=step
   for cls in ui.classes:
    if cls==ui.FDMMINI_PT_main or cls.poll(bpy.context):
     cls.draw(panel,bpy.context)
  assert any(identity['short'] in s for s in labels),(level,strategy,labels)
labels.clear();preferences.FDMMINI_Preferences.draw(panel,bpy.context)
assert identity['commit'] in labels
args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(dict(pass_gate=True,identity=identity,panel_variants=6,workflow_states=30,workflow_panels=5,preferences_full_sha=True,addon_root=str(args.addon_root.resolve())),indent=2),encoding='utf-8')
print('Six panel variants and preferences show verified build SHA:',identity['commit'])
