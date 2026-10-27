import bpy
from bpy.types import AddonPreferences
from . import version

ADDON_ID = "fdm_mini_tools"

class FDMMINI_Preferences(AddonPreferences):
    bl_idname = ADDON_ID

    def draw(self,context):
        identity=version.installed_build()
        self.layout.label(text='FDM Mini Tools 0.3.0 RC1')
        self.layout.label(text=identity['label'],icon='INFO')
        if identity['commit']:
            self.layout.label(text=identity['commit'])
        if not identity['verified']:
            self.layout.label(text='Build nicht verifiziert; Paket neu installieren',icon='ERROR')

classes = (FDMMINI_Preferences,)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
