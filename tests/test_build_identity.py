import hashlib,json,tempfile,unittest
from pathlib import Path
from optimization_cli import load_module
version=load_module('version')

class BuildIdentity(unittest.TestCase):
 def setUp(self):
  base=Path(__file__).resolve().parents[1]/'build';base.mkdir(exist_ok=True)
  self.tmp=tempfile.TemporaryDirectory(dir=base);self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  (self.root/'code.py').write_bytes(b'answer=42\n');self.commit='a'*40
  self.metadata=dict(commit=self.commit,source_sha256={'code.py':hashlib.sha256((self.root/'code.py').read_bytes()).hexdigest()})
 def write(self):
  (self.root/version.BUILD_FILE).write_text(json.dumps(self.metadata),encoding='utf-8')
 def test_clean_package_reports_exact_commit(self):
  self.write();result=version.read_build(self.root)
  self.assertTrue(result['verified']);self.assertEqual(result['commit'],self.commit)
 def test_modified_source_is_not_reported_clean(self):
  self.write();(self.root/'code.py').write_bytes(b'answer=0\n')
  result=version.read_build(self.root);self.assertFalse(result['verified']);self.assertIn('Geaendert',result['label'])
 def test_missing_metadata_does_not_invent_commit(self):
  result=version.read_build(self.root);self.assertFalse(result['verified']);self.assertIsNone(result['commit'])
 def test_extra_file_invalidates_identity_but_bytecode_does_not(self):
  self.write();cache=self.root/'__pycache__';cache.mkdir();(cache/'code.pyc').write_bytes(b'cache')
  self.assertTrue(version.read_build(self.root)['verified'])
  (self.root/'other.py').write_bytes(b'');self.assertFalse(version.read_build(self.root)['verified'])
 def test_invalid_commit_is_rejected(self):
  self.metadata['commit']='not-a-commit';self.write();self.assertFalse(version.read_build(self.root)['verified'])
 def test_invalid_manifest_is_rejected(self):
  self.metadata['source_sha256']={'../outside':'0'*64};self.write()
  self.assertFalse(version.read_build(self.root)['verified'])

if __name__=='__main__':unittest.main()
