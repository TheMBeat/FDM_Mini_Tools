"""Actual isolated Orca slicing and G-code evidence for candidate comparison."""
import json
from pathlib import Path
import re
import zipfile

from . import print_profile


def gcode_metrics(text):
    # Orca versions use both Prusa-style TYPE and Bambu-style FEATURE comments.
    metrics = dict(filament_mm=None, filament_volume_mm3=None,
        filament_g=None, estimated_time=None, bridge_extrusion_moves=0,
        positive_extrusion_moves=0, layers=0)
    expressions = {
        'filament_mm': r'filament used \[mm\]\s*=\s*([\d.]+)',
        'filament_volume_mm3': r'filament used \[cm3\]\s*=\s*([\d.]+)',
        'filament_g': r'filament used \[g\]\s*=\s*([\d.]+)',
        'estimated_time': r'estimated printing time \(normal mode\)\s*=\s*([^\r\n]+)'}
    for key, pattern in expressions.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            metrics[key] = match[1].strip() if key=='estimated_time' else float(match[1])
    if metrics['filament_volume_mm3'] is not None:
        metrics['filament_volume_mm3'] *= 1000
    bridge, relative, previous = False, False, 0.
    for line in text.splitlines():
        if line.startswith(';TYPE:') or line.startswith('; FEATURE:'):
            bridge = 'bridge' in line.lower()
        if line.startswith(';LAYER_CHANGE') or line.startswith('; CHANGE_LAYER'):
            metrics['layers'] += 1
        command = line.split(';',1)[0].strip()
        if command=='M83':
            relative=True
        elif command=='M82':
            relative=False
        if command.startswith(('G0 ','G1 ','G92 ')):
            match = re.search(r'(?:^|\s)E([-+\d.]+)',command)
            if not match:
                continue
            extrusion = float(match[1])
            delta = extrusion if relative else extrusion-previous
            previous=extrusion
            if not command.startswith('G92 ') and delta > 1e-8 and re.search(r'\s[XY][-+\d.]',command):
                metrics['positive_extrusion_moves'] += 1
                metrics['bridge_extrusion_moves'] += int(bridge)
    if not metrics['positive_extrusion_moves']:
        raise RuntimeError('Orca output contains no positive XY extrusion moves')
    if metrics['filament_mm'] is None or metrics['estimated_time'] is None:
        raise RuntimeError('Orca output is missing material/time statistics')
    return metrics


def slice_project(orca, project, profile_dir, output_dir, timeout=600):
    profile_dir, out = Path(profile_dir).resolve(), Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    isolated=profile_dir/'isolated'
    presets=isolated/'user/default'
    paths=[presets/kind/(name+'.json') for kind,name in
           (('machine',print_profile.MACHINE),('process',print_profile.PROCESS),
            ('filament',print_profile.FILAMENT))]
    target=out/'sliced.3mf'
    effective=out/'effective.json'
    command=[orca,'--datadir',isolated,'--load-settings',str(paths[0])+';'+str(paths[1]),
        '--load-filaments',paths[2], '--enable-support=0',
        '--slice','0','--export-settings',effective,'--export-3mf',target,
        '--mstpp',str(timeout-30),Path(project).resolve()]
    # Orca's Windows postprocessor cannot rename in the app-container temp
    # redirection on this host. A writable project-local temp fixes the repro;
    # do not disable normative checks or recover half-written G-code as success.
    print_profile.run(command,out/'orca.log',timeout,temp_dir=profile_dir.parent/'.orca_tmp')
    if not target.is_file():
        raise RuntimeError('Orca did not create sliced project')
    settings=json.loads(effective.read_text(encoding='utf-8'))
    actual=print_profile.summary(settings)
    original_profile=print_profile.load(profile_dir/'profile.json')
    expected=original_profile['summary']
    for field in ('machine','process','filament','nozzle_mm','layer_mm','bridge_speed_mm_s','bridge_flow'):
        if actual[field] != expected[field]:
            raise RuntimeError(f'Orca used a different profile value: {field}')
    if str(print_profile.scalar(settings,'enable_support')) not in ('0','false','False'):
        raise RuntimeError('Unexpected additional slicer supports; material comparison invalid')
    differences=[key for key,value in original_profile['settings'].items()
        if key!='enable_support' and settings.get(key)!=value]
    if differences:
        raise RuntimeError(f'Orca effective settings changed: {differences[:12]}')
    plates=[]
    with zipfile.ZipFile(target) as package:
        gcode_files=sorted(n for n in package.namelist() if n.endswith('.gcode'))
        if not gcode_files:
            raise RuntimeError('Import/export alone is not slicing: missing G-code')
        for name in gcode_files:
            data=package.read(name)
            metrics=gcode_metrics(data.decode('utf-8',errors='replace'))
            import math
            metrics['filament_volume_mm3']=metrics['filament_mm']*math.pi*(print_profile.number(settings,'filament_diameter')/2)**2
            local=out/Path(name).name
            local.write_bytes(data)
            plates.append(dict(file=str(local),sha256=print_profile.sha256(local),**metrics))
    result=dict(pass_gate=True, plates=plates,profile=actual,
        output=str(target),support_generation='explicit validated meshes; Orca additional supports disabled',
        print_validated=False,bridge_quality_validated=False)
    (out/'slice_qa.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result
