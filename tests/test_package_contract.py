"""Offline source-wiring checks for the installable package."""
from pathlib import Path
import ast
import re
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'fdm_mini_tools'


class PackageContractTest(unittest.TestCase):
    def test_all_python_parses(self):
        for p in ROOT.rglob('*.py'):
            with self.subTest(p=p.name):
                ast.parse(p.read_text(encoding='utf-8'), filename=str(p), feature_version=(3, 11))

    def test_contact_backend_wiring(self):
        core = (ROOT/'core.py').read_text(encoding='utf-8')
        ops = (ROOT/'operators.py').read_text(encoding='utf-8')
        contact = (ROOT/'contacts.py').read_text(encoding='utf-8')
        self.assertIn('contacts.create_tree_point_object(', core)
        self.assertIn('contacts.create_tree_point_object(', ops)
        self.assertIn('core.bake_scatter(points, scatter, enable_generator=False)', contact)
        self.assertIn('append_slasg(slasg_path)', core)
        self.assertIn('append_slasg(slasg)', ops)
        self.assertIn('strategy == "FDM_TREE"', core)
        self.assertIn('"tree_contact_backend": "SLASG"', core)

    def test_levels_and_defaults(self):
        props = (ROOT/'properties.py').read_text(encoding='utf-8')
        ui = (ROOT/'ui.py').read_text(encoding='utf-8')
        for level in ('SIMPLE', 'ADVANCED', 'EXPERT'):
            self.assertIn(level, props)
        self.assertIn("p.ui_level in {'ADVANCED', 'EXPERT'}", ui)
        self.assertIn("p.ui_level == 'EXPERT'", ui)
        self.assertIn('default="SLASG_CLASSIC"', props)
        self.assertIn('default="SIMPLE"', props)

    def test_ui_props_exist(self):
        props = (ROOT/'properties.py').read_text(encoding='utf-8')
        ui = (ROOT/'ui.py').read_text(encoding='utf-8')
        declared = set(re.findall(r'^\s+(\w+):\s*\w+Property\(', props, re.M))
        # Inspect property bindings, not arbitrary strings such as JSON keys.
        # The old regex mistook pose['front_direction'] for a missing RNA field.
        used = set()
        for node in ast.walk(ast.parse(ui)):
            if isinstance(node,ast.Attribute) and isinstance(node.value,ast.Name) and node.value.id in {'p','props'}:
                used.add(node.attr)
            if not isinstance(node,ast.Call):
                continue
            if (isinstance(node.func,ast.Attribute) and node.func.attr=='prop' and len(node.args)>1
                    and isinstance(node.args[0],ast.Name) and node.args[0].id in {'p','props'}
                    and isinstance(node.args[1],ast.Constant)):
                used.add(node.args[1].value)
            if (isinstance(node.func,ast.Name) and node.func.id=='_grid' and len(node.args)>2
                    and isinstance(node.args[2],(ast.Tuple,ast.List))):
                used.update(item.value for item in node.args[2].elts if isinstance(item,ast.Constant))
        missing = sorted(used-declared)
        self.assertEqual(missing, [])

    def test_no_python_rooting_prototype_paths(self):
        for name in ('patch_slasg_buildplate_rooting_v8', 'FDM_RESCUE_TRUSSES', 'SLASG_Line_FDM_TwoPass'):
            if name == 'FDM_RESCUE_TRUSSES':
                continue  # compatibility cleanup of stale scene objects is intentional
            self.assertNotIn(name, (ROOT/'core.py').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
