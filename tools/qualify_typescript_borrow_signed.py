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
    args=parser.parse_args()
    prepare(args.inputs)
    print(json.dumps(qualify(args.tools,args.inputs/'products',args.output)))
