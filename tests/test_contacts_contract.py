"""Offline contract checks; run without Blender and bpy."""
import importlib.util
import pathlib
import unittest

SRC = pathlib.Path(__file__).resolve().parents[1] / 'fdm_mini_tools' / 'contacts.py'
spec=importlib.util.spec_from_file_location('fdm_contacts_only', SRC)
contacts=importlib.util.module_from_spec(spec)
spec.loader.exec_module(contacts)


class ContactBackendContract(unittest.TestCase):
    def test_tree_defaults_to_slasg_reference(self):
        self.assertEqual(contacts.backend_for({'support_strategy':'FDM_TREE'}),'SLASG')
        self.assertTrue(contacts.requires_slasg({'support_strategy':'FDM_TREE'}))
    def test_native_is_opt_in_experiment(self):
        cfg={'support_strategy':'FDM_TREE','tree_contact_backend':'NATIVE_EXPERIMENTAL'}
        self.assertFalse(contacts.requires_slasg(cfg))
    def test_classic_always_requires_slasg(self):
        cfg={'support_strategy':'SLASG_CLASSIC','tree_contact_backend':'NATIVE_EXPERIMENTAL'}
        self.assertTrue(contacts.requires_slasg(cfg))
    def test_unknown_backend_rejected(self):
        with self.assertRaises(ValueError):
            contacts.backend_for({'tree_contact_backend':'unsupported'})

if __name__=='__main__': unittest.main()
