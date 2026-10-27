"""Build matching install/source archives only from a clean public checkout."""
import argparse, hashlib, json, runpy, subprocess, zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def build(output):
 names=subprocess.check_output(["git","-C",str(ROOT),"ls-tree","-r","--name-only","HEAD"]).decode().splitlines()
 for n in names:
  p=Path(n)
  if n.startswith(("reports/","dist/")) or p.suffix.lower() in {".stl",".3mf",".gcode",".opc",".zip"} or (p.suffix.lower()==".blend" and n!="fdm_mini_tools/resources/SLASG_FDM_Mini.blend"):
   raise RuntimeError("Not a clean public source tree: "+n)
 builder=runpy.run_path(str(ROOT/"tests/build_versioned_package.py"))
 output=Path(output).resolve();meta=builder["build"](ROOT,output)
 source=output/("fdm_mini_tools_source_"+meta["commit"][:12]+".zip")
 subprocess.run(["git","-C",str(ROOT),"archive","--format=zip","--prefix=fdm-mini-tools/","--output",str(source),"HEAD"],check=True)
 with zipfile.ZipFile(meta["package"]) as z:
  assert "fdm_mini_tools/resources/SLASG_FDM_Mini.blend" in z.namelist()
  assert "fdm_mini_tools/resources/THIRD_PARTY_SLASG.txt" in z.namelist()
  assert "fdm_mini_tools/LICENSE" in z.namelist()
 archives=[Path(meta["package"]),source]
 hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in archives}
 (output/"SHA256SUMS.txt").write_text("".join(h+"  "+n+"\n" for n,h in hashes.items()),encoding="utf-8")
 result=dict(commit=meta["commit"],status="experimental prerelease",archives_sha256=hashes)
 (output/"release.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
 print(json.dumps(result,indent=2));return result
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--output-dir",type=Path,default=ROOT/"dist");build(p.parse_args().output_dir)
