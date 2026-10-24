#!/usr/bin/env python3
"""One fresh fixed probe and signed borrow-release logical-reference programme."""
import argparse
import json
from pathlib import Path
import sys
if __package__ in (None,''): sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.typescript_guest.borrow_signed_controls import qualify
from tools.typescript_guest.borrow_signed_inputs import prepare
if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tools',type=Path,required=True)
    parser.add_argument('--inputs',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--programme',choices=('borrow','node-net'),default='borrow')
    parser.add_argument('--prepared-native',type=Path)
    args=parser.parse_args()
    if args.programme == 'node-net' and args.prepared_native is None:
        parser.error('node-net requires the exact prepared native gate')
    if args.programme == 'borrow' and args.prepared_native is not None:
        parser.error('native CLI inputs are selected only by the closed node-net programme')
    prepare(args.inputs)
    if args.programme == 'node-net':
        from tools import java_phase_native_products
        java_phase_native_products.prepare(args.prepared_native)
    print(json.dumps(qualify(args.tools,args.inputs/'products',args.output,
        programme=args.programme, prepared_native=args.prepared_native)))
