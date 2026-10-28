
bl_info = {
    "name": "FDM Mini Tools",
    "author": "FDM Mini Tools",
    "version": (0, 3, 0),
    "blender": (5, 2, 0),
    "location": "3D View > Sidebar > FDM Mini Tools",
    "description": "Miniature preparation: SLASG Classic and experimental FDM Tree with SLA tips",
    "category": "3D View",
}

from . import preferences, properties, operators, ui, i18n

_modules = (preferences, properties, operators, ui)


def register():
    i18n.register()
    for module in _modules:
        module.register()


def unregister():
    for module in reversed(_modules):
        module.unregister()
    i18n.unregister()
