"""Install/enable the release in temporary Blender directories, never user prefs."""
import argparse,json,os,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--zip',required=True,type=Path);p.add_argument('--output-dir',type=Path,default=ROOT/'reports/install_validation')
 a=p.parse_args();out=a.output_dir.resolve();out.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(prefix='fdm-install-test-') as directory:
  temp=Path(directory);env=os.environ.copy()
  for var,name in [('BLENDER_USER_SCRIPTS','scripts'),('BLENDER_USER_CONFIG','config'),('BLENDER_USER_EXTENSIONS','extensions')]:
   path=temp/name;path.mkdir();env[var]=str(path)
  cmd=[a.blender,'--factory-startup','-b','--python-exit-code','1','--python',str(ROOT/'tests/blender_install_package_smoke.py'),'--','--zip',str(a.zip.resolve()),'--output',str(out/'result.json')]
  with (out/'install.log').open('w',encoding='utf-8') as log:
   result=subprocess.run(cmd,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=180,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  if result.returncode:
   print((out/'install.log').read_text(encoding='utf-8')[-6000:]);raise SystemExit(result.returncode)
  assert json.loads((out/'result.json').read_text())['pass_gate']
 print('Isolated Blender ZIP install, both languages and tooltips: PASS')
if __name__=='__main__':main()
