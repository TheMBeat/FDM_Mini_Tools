"""Export an allowlisted HEAD snapshot to a NEW public repository directory.

Never copies .git/history, local files, private fixtures or generated evidence.
"""
import argparse, hashlib, json, subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {"README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "CONTRIBUTING.md", "CHANGELOG.md", ".gitignore", ".gitattributes", "requirements-dev.txt"}
DOCS = {"docs/RELEASE_NOTES.md", "docs/TESTING.md", "docs/PUBLISHING.md"}
TESTS = {"optimization_cli.py", "diagnose_tree_blender.py", "tree_export_qa.py", "blender_smoke.py", "blender_classic_smoke.py", "blender_cap24_regression.py", "blender_version_ui_smoke.py", "build_versioned_package.py", "run_public_validation.py", "blender_i18n_regression.py", "blender_install_package_smoke.py"}
def allowed(name):
 p = Path(name)
 return (name in ROOT_FILES or name in DOCS or name.startswith("fdm_mini_tools/") or name.startswith(".github/") or name.startswith("tools/") or
    (len(p.parts)==2 and p.parts[0]=="tests" and (p.name in TESTS or (p.name.startswith("test_") and p.suffix==".py"))) or
    (name.startswith("tests/reference/") and p.suffix==".py"))
def git(*args):
 return subprocess.check_output(["git", "-C", str(ROOT), *args])
def export(target):
 target = Path(target).resolve()
 if target.exists(): raise FileExistsError("Destination must be a new directory: " + str(target))
 if git("status", "--porcelain").strip(): raise RuntimeError("Commit source changes before exporting")
 commit = git("rev-parse", "HEAD").decode().strip()
 names = git("ls-tree", "-r", "--name-only", "HEAD").decode().splitlines()
 payload = {n:git("show", "HEAD:"+n) for n in names if allowed(n)}
 for name in payload:
  p=Path(name)
  if p.suffix.lower() in {".stl", ".3mf", ".gcode", ".opc", ".zip"}:raise RuntimeError("Forbidden public asset: "+name)
  if p.suffix.lower()==".blend" and name!="fdm_mini_tools/resources/SLASG_FDM_Mini.blend":raise RuntimeError("Unexpected Blender asset: "+name)
 target.mkdir(parents=True)
 for name,data in payload.items():
  p=target/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
 manifest={n:hashlib.sha256(data).hexdigest() for n,data in sorted(payload.items())}
 (target/"SOURCE_PROVENANCE.json").write_text(json.dumps(dict(upstream_commit=commit,files_sha256=manifest),indent=2)+"\n",encoding="utf-8")
 return dict(destination=str(target),upstream_commit=commit,files=len(payload))
if __name__=="__main__":
 parser=argparse.ArgumentParser();parser.add_argument("--output-dir",required=True,type=Path)
 print(json.dumps(export(parser.parse_args().output_dir),indent=2))
