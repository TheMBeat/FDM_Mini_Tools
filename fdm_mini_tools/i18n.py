"""Native Blender localization: English source, German UI and tooltips."""
import json
from pathlib import Path
import bpy

def register():
    messages=json.loads((Path(__file__).parent/'resources/translations_de.json').read_text(encoding='utf-8'))
    catalog={("*",source):translated for source,translated in messages.items()}
    bpy.app.translations.register(__package__,{"de_DE":catalog})

def unregister():
    bpy.app.translations.unregister(__package__)

def iface(message):
    return bpy.app.translations.pgettext_iface(message)

def format_iface(message,**values):
    return iface(message).format(**values)
