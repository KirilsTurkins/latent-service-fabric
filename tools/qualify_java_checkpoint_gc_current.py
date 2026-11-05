"""Explicit current-host entrypoint for the unchanged Java GC programme."""
import argparse
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import qualify_java_checkpoint_gc as owner
from tools import wasmtime_48_0_8_678b_native_products as products


def check_source_only():
    """Refuse stale current-host inputs before expensive downloads."""
    owner.native_materials(products)
    owner.require_current_native_source(products,owner.source_identity(owner.ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('native','wasi-sdk','output'):parser.add_argument('--'+name,type=Path)
    parser.add_argument('--check-source-only',action='store_true')
    parser.add_argument('--read-only-cache',type=Path)
    parser.add_argument('--diagnostic-node',type=Path)
    parser.add_argument('--diagnostic-client',type=Path)
    args=parser.parse_args()
    if args.check_source_only:
        if any(value is not None for value in (args.native,args.wasi_sdk,args.output,
                args.read_only_cache,args.diagnostic_node,args.diagnostic_client)):
            parser.error('--check-source-only does not accept runtime inputs')
        check_source_only()
        print('java-checkpoint-current-native-source-matched')
        return
    if any(value is None for value in (args.native,args.wasi_sdk,args.output)):
        parser.error('--native, --wasi-sdk and --output are required')
    print(owner.qualify(args.native,args.wasi_sdk,args.output,read_only_cache=args.read_only_cache,
        diagnostic_node=args.diagnostic_node,diagnostic_client=args.diagnostic_client,
        native_reader=products)['status'])


if __name__=='__main__':main()
