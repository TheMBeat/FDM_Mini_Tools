"""Reject source ZIPs, nesting, traversal, and damaged install payloads."""
import importlib.util,json,hashlib,tempfile,unittest,zipfile
from pathlib import Path
spec=importlib.util.spec_from_file_location('package_builder',Path(__file__).with_name('build_versioned_package.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class InstallArchive(unittest.TestCase):
 def payload(self):
  data={name:b'fixture' for name in ['__init__.py','core.py','i18n.py','LICENSE','resources/SLASG_FDM_Mini.blend','resources/translations_de.json']}
  data['_build.json']=json.dumps(dict(source_sha256={k:hashlib.sha256(v).hexdigest() for k,v in data.items()})).encode()
  return {'fdm_mini_tools/'+k:v for k,v in data.items()}
 def check(self,files):
  with tempfile.TemporaryDirectory() as directory:
   p=Path(directory)/'install.zip'
   with zipfile.ZipFile(p,'w') as z:
    for k,v in files.items():z.writestr(k,v)
   return m.validate_install_archive(p)
 def test_single_module_folder_is_installable(self):self.assertTrue(self.check(self.payload()))
 def test_version_wrapper_is_rejected(self):
  with self.assertRaises(ValueError):self.check({'FDM_Mini_Tools_0.3.0_RC2/'+k:v for k,v in self.payload().items()})
 def test_source_root_files_are_rejected(self):
  with self.assertRaises(ValueError):self.check(dict(self.payload(),**{'README.md':b'source'}))
 def test_traversal_is_rejected(self):
  with self.assertRaises(ValueError):self.check(dict(self.payload(),**{'fdm_mini_tools/../extra.py':b'bad'}))
 def test_corruption_is_rejected(self):
  files=self.payload();files['fdm_mini_tools/core.py']=b'changed'
  with self.assertRaises(ValueError):self.check(files)
if __name__=='__main__':unittest.main()
