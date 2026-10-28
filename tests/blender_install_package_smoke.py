"""Real Blender installer check; requires isolated environment paths."""
import argparse,json,os,sys
from pathlib import Path
import bpy
p=argparse.ArgumentParser();p.add_argument('--zip',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
expected=Path(os.environ['BLENDER_USER_SCRIPTS']).resolve()
assert Path(bpy.utils.user_resource('SCRIPTS')).resolve()==expected,'Refusing to touch the normal Blender installation'
assert 'FINISHED' in bpy.ops.preferences.addon_install(filepath=str(a.zip.resolve()),overwrite=True)
assert 'FINISHED' in bpy.ops.preferences.addon_enable(module='fdm_mini_tools')
import fdm_mini_tools
from fdm_mini_tools import version,i18n
root=Path(fdm_mini_tools.__file__).resolve().parent
assert root==expected/'addons/fdm_mini_tools',root
identity=version.installed_build();assert identity['verified'],identity
view=bpy.context.preferences.view;view.use_translate_interface=True;view.use_translate_tooltips=True
view.language='en_US';assert i18n.iface('1  Load model')=='1  Load model'
view.language='de_DE';assert i18n.iface('1  Load model')=='1  Modell laden'
desc=bpy.context.scene.fdm_mini_tools.bl_rna.properties['optimization_joint_type'].description
assert bpy.app.translations.pgettext_tip(desc)!=desc
assert 'FINISHED' in bpy.ops.preferences.addon_disable(module='fdm_mini_tools')
assert 'FINISHED' in bpy.ops.preferences.addon_enable(module='fdm_mini_tools')
assert version.installed_build()['verified']
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(dict(pass_gate=True,identity=identity,addon_root=str(root),installer='preferences.addon_install',languages=['en_US','de_DE'],tooltips=True,re_enabled=True),indent=2),encoding='utf-8')
print('Installer, enable/disable, bilingual UI and tooltips: PASS')
