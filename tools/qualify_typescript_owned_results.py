#!/usr/bin/env python3
"""One fresh normal splicer/engine and bounded OWN-result native prerequisites."""
import argparse
import json
from pathlib import Path
import sys
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.typescript_guest.owned_result_controls import build

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--tools',required=True,type=Path)
    parser.add_argument('--wasm-tools',default='wasm-tools')
    parser.add_argument('--wit-bindgen',default='wit-bindgen')
    profiles=parser.add_mutually_exclusive_group()
    profiles.add_argument('--partial-own',action='store_true',help='Closed private ABI2 static partial-OWN prerequisites only')
    profiles.add_argument('--prepared-native',action='store_true',help='Closed9c626 completed inputs; rebuild only the partial-OWN fixture')
    args=parser.parse_args()
    print(json.dumps(build(args.output,args.tools,wasm_tools=args.wasm_tools,bindgen=args.wit_bindgen,partial_own=args.partial_own,prepared_native=args.prepared_native)))
