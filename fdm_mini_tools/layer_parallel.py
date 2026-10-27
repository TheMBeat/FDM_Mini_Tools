"""Isolated, bounded section workers. No bpy or Blender object crosses a process.

The parent writes each immutable array once. Workers share read-only memory maps;
the ordered result is consumed only after every child has exited successfully.
Any transport/runtime failure falls back to the serial implementation.
"""
import json
from contextlib import ExitStack
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import numpy as np
last_run={}


def _reap(processes):
    for process,_ in processes:
        if process.poll() is None:process.kill()
        process.wait()


def python_binary():
    # Blender's sys.executable is blender.exe, not a Python interpreter.
    prefix=Path(sys.prefix)
    candidates=([prefix/'bin/python.exe',prefix/'python.exe'] if os.name=='nt'
                else [prefix/'bin/python3',prefix/'bin/python'])
    if Path(sys.executable).name.lower().startswith('python'):
        candidates.insert(0,Path(sys.executable))
    return next((p for p in candidates if p.is_file()),None)


def _run(prepared,payloads,workers=2,timeout=180,support=None):
    binary=python_binary()
    count=min(max(0,int(workers)),2,max(1,os.cpu_count() or 1),len(payloads))
    last_run.clear();last_run.update(workers=count,jobs=len(payloads),python=str(binary),used=False)
    if binary is None or count<2:return None
    processes=[]
    try:
        with tempfile.TemporaryDirectory(prefix='fdm_sections_') as folder, ExitStack() as children:
            # Close child memory maps BEFORE TemporaryDirectory removes files.
            children.callback(_reap,processes)
            root=Path(folder)
            def save_arrays(data,prefix):
                if data is None:return None
                paths=[]
                for i,shell in enumerate(data):
                    names=[]
                    for j,array in enumerate(shell):
                        path=root/f'{prefix}_{i}_{j}.npy';np.save(path,array,allow_pickle=False);names.append(str(path))
                    paths.append(names)
                return paths
            paths=save_arrays(prepared,'model');support_paths=save_arrays(support,'support')
            for i in range(count):
                request=root/f'job{i}.json';response=root/f'out{i}.json'
                request.write_text(json.dumps(dict(arrays=paths,support_arrays=support_paths,
                    jobs=payloads[i::count],output=str(response))),encoding='utf-8')
                env=os.environ.copy()
                # Small vector kernels do not need nested BLAS thread pools.
                env.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
                process=subprocess.Popen([str(binary),str(Path(__file__).with_name('layer_worker.py')),str(request)],
                    stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                    env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                processes.append((process,response))
            deadline=time.monotonic()+timeout
            while any(p.poll() is None for p,_ in processes):
                if time.monotonic()>deadline:raise TimeoutError('Section workers timed out')
                time.sleep(.05)
            result=[]
            for process,response in processes:
                if process.returncode!=0:raise RuntimeError('Section worker failed')
                result.extend(json.loads(response.read_text(encoding='utf-8')))
            if sorted(row[0] for row in result)!=list(range(len(payloads))):raise RuntimeError('Incomplete worker result')
            result.sort(key=lambda row:row[0])
            last_run['used']=True
            return result
    except (OSError,ValueError,RuntimeError,TimeoutError) as error:
        last_run['fallback_reason']=str(error)
        return None
    finally:
        _reap(processes)


def sections(prepared,heights,workers=2,timeout=180):
    rows=_run(prepared,[dict(index=i,height=z) for i,z in enumerate(heights)],workers,timeout)
    if rows is None:return None
    return {heights[i]:(polygons,error) for i,polygons,error in rows}


def diagnose(prepared,records,profile,workers=2,support=None):
    # Diagnosis consumes id/point only; plateau meshes and planner candidates
    # stay in the parent instead of being copied into each request file.
    rows=_run(prepared,[dict(index=i,record=dict(id=record['id'],point=record['point']),profile=profile) for i,record in enumerate(records)],
              workers,support=support)
    if rows is None:return None
    return [row[1] for row in rows]

