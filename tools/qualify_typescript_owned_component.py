#!/usr/bin/env python3
"""One bounded real canonical OWN diagnostic from exact completed normal inputs."""
import argparse
import json
from pathlib import Path
import sys
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.typescript_guest.owned_component_controls import build

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--tools',required=True,type=Path)
    parser.add_argument('--prepared-products',required=True,type=Path)
    args=parser.parse_args()
    print(json.dumps(build(args.output,args.tools,args.prepared_products)))
