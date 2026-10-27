"""Build only a clean committed source tree; embed its real SHA without self-reference."""
import argparse,hashlib,json,subprocess,zipfile
from pathlib import Path

def build(repo,out):
 repo=Path(repo).resolve();out=Path(out).resolve()
 def git(*args):return subprocess.check_output(['git','-C',str(repo),*args])
 if git('status','--porcelain').strip():raise RuntimeError('Commit source changes before building')
 commit=git('rev-parse','HEAD').decode().strip()
 names=git('ls-tree','-r','--name-only','HEAD','--','fdm_mini_tools').decode().splitlines()
 payload={}
 for name in names:
  if Path(name).name=='_build.json':raise RuntimeError('Generated build identity must not be tracked')
  data=git('show','HEAD:'+name)
  if (repo/name).read_bytes()!=data:raise RuntimeError('Committed bytes differ: '+name)
  payload[name]=data
 sources={name.split('/',1)[1]:hashlib.sha256(data).hexdigest() for name,data in payload.items()}
 payload['fdm_mini_tools/_build.json']=(json.dumps(dict(schema=1,commit=commit,source_sha256=sources),indent=2,sort_keys=True)+'\n').encode()
 out.mkdir(parents=True,exist_ok=True);archive=out/f'fdm_mini_tools_0.3.0_RC1_{commit[:12]}.zip'
 with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
  for name,data in sorted(payload.items()):
   info=zipfile.ZipInfo(name,(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16
   z.writestr(info,data)
 with zipfile.ZipFile(archive) as z:
  assert set(z.namelist())==set(payload)
  for name,data in payload.items():assert z.read(name)==data
 result=dict(commit=commit,package=str(archive),sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),source_files=len(sources))
 print(json.dumps(result,indent=2));return result
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[1]);parser.add_argument('--output-dir',type=Path,required=True)
 args=parser.parse_args();build(args.repo,args.output_dir)
