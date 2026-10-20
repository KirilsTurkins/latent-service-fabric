"""Exact Wasmtime 48.0.7 SDK products; no signed guest qualification."""
from pathlib import Path
import sys
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.sdk_native_products_reader import FrozenNativeProducts

SOURCE = 'fc9b44a6b8dce9effd6b490f1a169a7ad8edbf12'
RUN = 39495029026
JOB = 118877777415
EVENT = 'workflow_dispatch'
BRANCH = 'fix/wasmtime-48-0-7-development-20261020'
ARTIFACT = {'id': 12298206858, 'size_in_bytes': 66152643, 'digest': 'sha256:c29154ac4c9e44f6c29bf7524104832589152f03cfabfdb9a3f42e01eddb4486'}
RECEIPTS = {'native-products.json': {'sha256': 'sha256:d3d7b97d078d73291cf6f0c0950e99c92ec9378c0032806c6074fb943b5441b1', 'bytes': 21390}, 'source-inputs.json': {'sha256': 'sha256:fbf3f0f5c678cbbcfc583af714dce7e8388ba8d3f49cfe8a25ef8298f09c503f', 'bytes': 18937}}
STAGES = ('rust-version', 'normal-host-build', 'closed-http-refusal-controls', 'neutral-resource-signing-controls', 'positive-timer-observer-controls', 'phase-nominal-type-owner-controls', 'phase-emitted-type-owner-controls', 'independent-http-configuration-controls', 'independent-http-dispatch-controls', 'independent-http-secret-controls', 'phase-operational-metadata-controls', 'phase-operational-binding-controls')

READER = FrozenNativeProducts(source=SOURCE, run=RUN, job=JOB, artifact=ARTIFACT,
    receipts=RECEIPTS, branch=BRANCH, stages=STAGES, event=EVENT)
prepare = READER.prepare
verify_prepared = READER.verify_prepared
native_products = READER.native_products

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args().output)
