#!/usr/bin/env python3
"""Build the real source-owned Promise/clock engine after its normal library."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in {None,''}:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.typescript_guest.native_build import build

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--library',type=Path,required=True)
    parser.add_argument('--wit-bindgen',default='wit-bindgen')
    parser.add_argument('--wasm-tools',default='wasm-tools')
    arguments = parser.parse_args()
    print(json.dumps(build(arguments.output,arguments.library,
        bindgen=arguments.wit_bindgen,wasm_tools=arguments.wasm_tools)))
