"""Identity embedded at packaging time; never infer an installed version from Git."""
from functools import lru_cache
from pathlib import Path, PurePosixPath
import hashlib,json,re

BUILD_FILE='_build.json'

def source_files(root):
    return sorted(p for p in Path(root).rglob('*') if p.is_file()
        and '__pycache__' not in p.parts and p.name!=BUILD_FILE and p.suffix not in {'.pyc','.pyo'})

def read_build(root):
    root=Path(root);result=dict(commit=None,short=None,verified=False,label="Unknown commit (development build)")
    try:
        data=json.loads((root/BUILD_FILE).read_text(encoding='utf-8'))
        commit=data['commit'];sources=data['source_sha256']
        if not re.fullmatch('[0-9a-f]{40}',commit) or not isinstance(sources,dict) or not sources:
            raise ValueError('Invalid build identity')
        result.update(commit=commit,short=commit[:12],label="Modified / Commit "+commit[:12])
        actual={p.relative_to(root).as_posix():p for p in source_files(root)}
        if set(actual)!=set(sources):raise ValueError('Build file list changed')
        for rel,checksum in sources.items():
            path=PurePosixPath(rel)
            if path.is_absolute() or '..' in path.parts or not re.fullmatch('[0-9a-f]{64}',checksum):
                raise ValueError('Invalid source manifest')
            if hashlib.sha256(actual[rel].read_bytes()).hexdigest()!=checksum:
                raise ValueError('Build contents changed')
        result.update(verified=True,label='Commit '+commit[:12])
    except (OSError,ValueError,KeyError,TypeError) as error:
        result['error']=str(error)
    return result

@lru_cache(maxsize=1)
def installed_build():
    # Hash once per loaded Blender session; the immutable packaged files are the authority.
    return read_build(Path(__file__).resolve().parent)
