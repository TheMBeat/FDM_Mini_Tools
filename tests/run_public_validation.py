"""Portable public subset: synthetic fixtures; no private model downloads."""
import argparse, json, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser();p.add_argument("--blender",required=True);p.add_argument("--output-dir",type=Path,default=ROOT/"reports/public_validation")
 a=p.parse_args();out=a.output_dir.resolve();out.mkdir(parents=True,exist_ok=True)
 runs=[("offline",[sys.executable,"-m","unittest","discover","-s",str(ROOT/"tests"),"-p","test_*.py","-v"])]
 for name in ["blender_cap24_regression.py","blender_smoke.py","blender_classic_smoke.py"]:
  cmd=[a.blender,"--factory-startup","-b","--python-exit-code","1","--python",str(ROOT/"tests"/name)]
  if name=="blender_smoke.py":cmd += ["--","--strict-geometry","--output",str(out/"tree_smoke.json")]
  runs.append((name,cmd))
 results=[]
 for name,cmd in runs:
  with (out/(name+".log")).open("w",encoding="utf-8") as log:
   proc=subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=600,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
  results.append(dict(check=name,exit_code=proc.returncode));(out/"results.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
  print(name,proc.returncode,flush=True)
  if proc.returncode:raise SystemExit(proc.returncode)
if __name__=="__main__":main()
