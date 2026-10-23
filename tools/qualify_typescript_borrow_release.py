#!/usr/bin/env python3
"""Build once and check native import observer controls; no signed qualification."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.typescript_guest.borrow_controls import build

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tools', type=Path, required=True)
    parser.add_argument('--source-splicer-build', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--wit-bindgen', default='wit-bindgen')
    parser.add_argument('--wasm-tools', default='wasm-tools')
    args = parser.parse_args()
    print(json.dumps(build(args.output, args.tools, args.source_splicer_build,
                           bindgen=args.wit_bindgen, wasm_tools=args.wasm_tools)))
