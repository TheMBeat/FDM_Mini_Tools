"""Resolve local Orca presets with Orca itself, including binary system caches.

No user profile/config is modified. The isolated copy is deliberately limited
to preset files, never account configuration or printer credentials.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess

MACHINE = 'Qidi Q2 0.2 Minis'
PROCESS = '0.08mm Standard @Qidi Q2 0.2 nozzle - Minis'
FILAMENT = 'Generic PLA Matte Minis'


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def scalar(settings, key, default=None):
    value = settings.get(key, default)
    if isinstance(value, list):
        value = value[0] if value else default
    return value


def number(settings, key, default=None):
    value = scalar(settings, key, default)
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise ValueError(f'Missing/invalid profile field: {key}') from None
    if not math.isfinite(result):
        raise ValueError(f'Nonfinite profile field: {key}')
    return result


def summary(settings):
    height = number(settings, 'layer_height')
    nozzle = number(settings, 'nozzle_diameter')
    if not 0 < height <= nozzle or nozzle > 2:
        raise ValueError('Invalid layer height/nozzle combination')
    return dict(machine=scalar(settings, 'printer_settings_id'),
        process=scalar(settings, 'print_settings_id'),
        filament=scalar(settings, 'filament_settings_id'),
        material=scalar(settings, 'filament_type'), nozzle_mm=nozzle,
        layer_mm=height, first_layer_mm=number(settings, 'initial_layer_print_height'),
        bridge_speed_mm_s=number(settings, 'bridge_speed'),
        bridge_flow=number(settings, 'bridge_flow'),
        profile_bridge_limit_mm=number(settings, 'max_bridge_length', 0),
        measured_bridge_limit_mm=None, bridge_limit_confirmed=False,
        support_removal_enabled=False,
        note='Profile bridge length is not a measured clean span. No automatic contact removal.')


def run(command, log, timeout=300, temp_dir=None):
    # Blender's inherited working directory/TEMP can belong to its launcher or
    # an app container. Orca needs a writable runtime even for --info/profile
    # resolution, before it can produce any console diagnostics.
    log = Path(log).resolve()
    log.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(temp_dir).resolve() if temp_dir is not None else log.parent / '.orca_tmp'
    temporary.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment['TEMP'] = environment['TMP'] = str(temporary)
    with log.open('w', encoding='utf-8') as output:
        result = subprocess.run([str(x) for x in command], stdout=output,
            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, timeout=timeout,
            cwd=str(log.parent), env=environment,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        tail = log.read_text(encoding='utf-8', errors='replace')[-2500:].strip()
        code = result.returncode & 0xffffffff
        detail = tail or 'Keine Orca-Konsolenausgabe; nativer Prozessabbruch.'
        raise RuntimeError(f'Orca failed ({result.returncode}, 0x{code:08X}): '
                           f'{detail} Log: {log}')


def resolve(orca, output_dir, probe_stl, appdata=None, user_folder='default'):
    """Return a portable effective profile with input provenance.

    The actual user/default path inside the isolated datadir matters: Orca's
    identity resolver cannot resolve arbitrary copies of these inherited files.
    """
    orca, out = Path(orca).resolve(), Path(output_dir).resolve()
    appdata = Path(appdata or os.environ['APPDATA']) / 'OrcaSlicer'
    user = appdata / 'user' / user_folder
    if not user.is_dir():
        raise FileNotFoundError(f'Orca preset folder missing: {user}')
    out.mkdir(parents=True, exist_ok=True)
    isolated = out / 'isolated'
    destination = isolated / 'user' / 'default'
    copied = []
    for kind in ('machine', 'process', 'filament'):
        (destination / kind).mkdir(parents=True, exist_ok=True)
        for source in sorted((user / kind).glob('*')):
            if source.suffix.lower() in ('.json', '.info'):
                target = destination / kind / source.name
                shutil.copy2(source, target)
                copied.append(dict(path=str(source), sha256=sha256(source)))
    system = isolated / 'system'
    system.mkdir(parents=True, exist_ok=True)
    # Installed cache format is owned by Orca; never reverse engineer defaults.
    caches = {}
    for root in (orca.parent / 'resources' / 'profiles', appdata / 'system'):
        if root.is_dir():
            for file in sorted(root.glob('*.opc')):
                caches[file.name] = file
    for source in caches.values():
        shutil.copy2(source, system / source.name)
        copied.append(dict(path=str(source), sha256=sha256(source)))
    paths = [destination / kind / (name + '.json') for kind, name in
             (('machine', MACHINE), ('process', PROCESS), ('filament', FILAMENT))]
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)
    effective = out / 'effective.json'
    command = [orca, '--datadir', isolated, '--load-settings',
        str(paths[0])+';'+str(paths[1]), '--load-filaments', paths[2],
        '--export-settings', effective, '--info', Path(probe_stl).resolve()]
    run(command, out / 'resolve.log', 120)
    settings = json.loads(effective.read_text(encoding='utf-8'))
    info = summary(settings)
    if abs(info['nozzle_mm'] - .2) > 1e-8 or abs(info['layer_mm'] - .08) > 1e-8:
        raise RuntimeError('Orca resolved a different nozzle/layer profile')
    if (info['machine'], info['process'], info['filament']) != (MACHINE, PROCESS, FILAMENT):
        raise RuntimeError('Orca profile identities do not match requested profiles')
    bundle = dict(schema=1, summary=info, settings=settings, inputs=copied,
        orca_executable=str(orca), orca_sha256=sha256(orca),
        effective_sha256=sha256(effective))
    (out / 'profile.json').write_text(json.dumps(bundle, indent=2), encoding='utf-8')
    return bundle


def load(path):
    bundle = json.loads(Path(path).read_text(encoding='utf-8'))
    if bundle.get('schema') != 1:
        raise ValueError('Unknown print profile schema')
    # Recompute typed facts from the full settings, never trust UI summaries.
    bundle['summary'] = summary(bundle['settings'])
    return bundle
