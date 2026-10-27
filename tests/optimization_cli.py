"""Resolve Orca settings outside Blender without importing its bpy UI package."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import types

ROOT=Path(__file__).resolve().parents[1]

def load_module(name):
    package=sys.modules.setdefault('fdm_mini_tools',types.ModuleType('fdm_mini_tools'))
    package.__path__=[str(ROOT/'fdm_mini_tools')]
    spec=importlib.util.spec_from_file_location('fdm_mini_tools.'+name,ROOT/'fdm_mini_tools'/(name+'.py'))
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    return module

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['profile','slice'])
    parser.add_argument('--orca',default=r'C:\Program Files\OrcaSlicer\orca-slicer.exe')
    parser.add_argument('--input',required=True,type=Path)
    parser.add_argument('--output-dir',required=True,type=Path)
    parser.add_argument('--profile-dir',type=Path)
    args=parser.parse_args()
    profile=load_module('print_profile')
    if args.action=='profile':
        result=profile.resolve(args.orca,args.output_dir,args.input)
        print(json.dumps(result['summary'],indent=2))
    else:
        qa=load_module('slice_qa')
        result=qa.slice_project(args.orca,args.input,args.profile_dir,args.output_dir)
        print(json.dumps(result,indent=2))

if __name__=='__main__':main()
