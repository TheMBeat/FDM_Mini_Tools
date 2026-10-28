"""Check English/German panels, enum labels, tooltips and dynamic messages."""
import sys,unittest,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import bpy,fdm_mini_tools
from fdm_mini_tools import i18n,ui
if not hasattr(bpy.types.Scene,'fdm_mini_tools'):fdm_mini_tools.register()
class Localization(unittest.TestCase):
 maxDiff=None
 def setUp(self):
  self.view=bpy.context.preferences.view
  self.old=(self.view.language,self.view.use_translate_interface,self.view.use_translate_tooltips)
  self.view.use_translate_interface=True;self.view.use_translate_tooltips=True
 def tearDown(self):self.view.language,self.view.use_translate_interface,self.view.use_translate_tooltips=self.old
 def test_english_interface_and_explanations(self):
  self.view.language='en_US'
  self.assertEqual(i18n.iface('1  Load model'),'1  Load model')
  self.assertEqual(i18n.iface('Simple'),'Simple')
  desc=bpy.context.scene.fdm_mini_tools.bl_rna.properties['optimization_joint_type'].description
  self.assertIn('Flat faces',desc)
  self.assertEqual(bpy.app.translations.pgettext_tip(desc),desc)
 def test_german_labels_and_tooltips(self):
  self.view.language='de_DE'
  self.assertEqual(i18n.iface('1  Load model'),'1  Modell laden')
  self.assertEqual(i18n.iface('Simple'),'Einfach')
  props=bpy.context.scene.fdm_mini_tools
  for name in ['optimization_joint_type','optimization_split_mode','optimization_auto_compare','optimization_profile','overhang_angle','spacing','use_raft','tree_complete_contacts','tree_guided_recovery','tree_model_clearance']:
   desc=props.bl_rna.properties[name].description
   self.assertTrue(desc,name)
   self.assertNotEqual(bpy.app.translations.pgettext_tip(desc),desc,(name,desc))
 def test_dynamic_messages_and_state_keep_saved_identifiers(self):
  props=bpy.context.scene.fdm_mini_tools;props.ui_level='EXPERT';props.ui_workflow_step='MODEL'
  for locale in ['en_US','de_DE']:
   self.view.language=locale
   text=i18n.format_iface('{v0} rooted contacts',v0=83)
   self.assertIn('83',text)
   self.assertIn('angebunden' if locale=='de_DE' else 'rooted',text)
   self.assertEqual(props.ui_level,'EXPERT');self.assertEqual(props.ui_workflow_step,'MODEL')
 def test_all_explanations_have_german_catalog_entries(self):
  catalog=json.loads((Path(fdm_mini_tools.__file__).parent/'resources/translations_de.json').read_text())
  missing=[]
  for p in bpy.context.scene.fdm_mini_tools.bl_rna.properties:
   if p.identifier in {'rna_type','name'} or not p.description:continue
   if p.description not in catalog:missing.append((p.identifier,p.description))
  self.assertEqual(missing,[])
if __name__=='__main__':
 result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Localization))
 if not result.wasSuccessful():raise RuntimeError('Localization checks failed')
