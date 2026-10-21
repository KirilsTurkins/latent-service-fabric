"""Replay the immutable signed-guest programme with original-ledger root stacks."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import qualify_typescript_runtime_limits as limits
from tools import typescript_tracking_component as component
from tools import activation_stack_native_source as native_source
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, fresh, write_json

SOURCES = tuple(dict.fromkeys((*limits.SOURCES, '.github/workflows/typescript-owned-stack.yml',
    'tools/qualify_typescript_owned_stack.py', 'tools/typescript_tracking_component.py',
    'tools/activation_stack_native_products.py', 'tools/activation_stack_native_source.py')))


def qualify(acquired, prepared, output):
    # This producer is frozen only after the shared C/RootOnly SDK5 build passes.
    # No historical reader is repinned and no guest/engine/compiler is rebuilt.
    from tools import activation_stack_native_products as native

    acquired, prepared, output = (Path(p).resolve() for p in (acquired, prepared, output))
    require(output != ROOT and ROOT not in output.parents and all(output != p
        and output not in p.parents and p not in output.parents for p in (acquired, prepared)),
        'typescript-owned-stack-separated-inputs')
    original = component.verify_prepared(acquired)
    source_origin = native_source.assert_current(ROOT)
    native_origin = native.verify_prepared(prepared)
    products = native.native_products(prepared)
    binaries = {name: file_identity(path, 512*1024**2) for name, path in products.items()}
    sources = {name: file_identity(ROOT/name, 2*1024**2) for name in SOURCES}
    output = fresh(output)
    write_json(output/'qualification-source-inputs.json', sources)
    observed = limits.execute(acquired/'build', products, output/'node', activation_owned_stack=True)
    require(observed['status'] == 'passed' and len(observed['cases']) == 15
        and observed['activationStackAccounting'] == 'activation-owned-v1',
        'typescript-owned-stack-original-programme')
    boundaries = {row['name']: row['boundary'] for row in observed['profiles']}
    # The immutable previous programme admitted 53 Promise Native records.
    # Its same ceiling now also funds this one real root Native stack owner.
    require(boundaries['native']['admitted'] == 52, 'typescript-owned-stack-original-native-ceiling')
    # The unchanged component's previous 64MiB bootstrap peaked at 9,519,608B.
    # Account the normal 2MiB root mapping on that original memory ledger too.
    require(boundaries['memory']['bootstrapPeak'] >= 9519608+2*1024**2,
        'typescript-owned-stack-original-memory-charge')
    require(component.verify_prepared(acquired) == original, 'typescript-owned-stack-component-changed')
    require(native.verify_prepared(prepared) == native_origin
        and binaries == {name: file_identity(path, 512*1024**2) for name, path in products.items()},
        'typescript-owned-stack-native-changed')
    require(sources == {name: file_identity(ROOT/name, 2*1024**2) for name in SOURCES},
        'typescript-owned-stack-source-changed')
    require(native_source.assert_current(ROOT) == source_origin,
        'typescript-owned-stack-native-source-changed')
    value = {'profile': 'typescript-original-activation-root-stack-v1', 'status': 'passed',
        'component': component.COMPONENT, 'componentOrigin': original,
        'nativeOrigin': native_origin, 'nativeSource': source_origin, 'qualificationSources': sources,
        'execution': file_identity(output/'node/qualification.json', 2*1024**2),
        'cases': observed['cases'], 'activationStackAccounting': 'activation-owned-v1',
        'boundaries': boundaries,
        'nativeThreadsEnabled': False, 'guestComponentRebuilt': False, 'engineRebuilt': False,
        'fullTicketQualification': False, 'socketProfileQualified': False}
    write_json(output/'qualification.json', value)
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('acquired', 'prepared', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    qualify(args.acquired, args.prepared, args.output)
