"""Private standalone section worker; intentionally imports no Blender package."""
import json
from pathlib import Path
import sys
import numpy as np
from layer_islands import section,diagnose


def main(request_path):
    request=json.loads(Path(request_path).read_text(encoding='utf-8'))
    prepared=[tuple(np.load(path,mmap_mode='r',allow_pickle=False) for path in shell)
              for shell in request['arrays']]
    support=([tuple(np.load(path,mmap_mode='r',allow_pickle=False) for path in shell)
              for shell in request['support_arrays']] if request['support_arrays'] is not None else None)
    rows=[]
    if request['jobs'] and 'record' in request['jobs'][0]:
        result=diagnose(None,[job['record'] for job in request['jobs']],**request['jobs'][0]['profile'],
                        workers=0,_prepared=prepared,_prepared_support=support)
        rows=[(job['index'],row) for job,row in zip(request['jobs'],result['points'])]
        Path(request['output']).write_text(json.dumps(rows),encoding='utf-8')
        return
    for job in request['jobs']:
        height=job['height']
        try:rows.append((job['index'],section(None,height,prepared),None))
        except (ValueError,FloatingPointError) as error:rows.append((job['index'],None,str(error)))
    Path(request['output']).write_text(json.dumps(rows),encoding='utf-8')


if __name__=='__main__':main(sys.argv[1])
