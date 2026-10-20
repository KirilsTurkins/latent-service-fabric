"""Exact Wasmtime 48.0.7 SDK products; no signed guest qualification."""
from pathlib import Path
import sys
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.sdk_native_products_reader import FrozenNativeProducts

SOURCE = '724686748d39d84c86ac6ec053f615b887642e94'
RUN = 39480948895
JOB = 118829053989
EVENT = 'workflow_dispatch'
BRANCH = 'fix/wasmtime-48-0-7-development-20261020'
ARTIFACT = {'id': 12292667379, 'size_in_bytes': 66110576, 'digest': 'sha256:7cf353169b2cdffd240a5b58e87b63d1e4db46892654730197def581bfd05998'}
RECEIPTS = {'native-products.json': {'sha256': 'sha256:4c620e59e12762a0ae5be726aa874fe5f2a740864419e898e647c6499d5b266e', 'bytes': 21390}, 'source-inputs.json': {'sha256': 'sha256:e0e73ec413c313528266e0428bc97efdfb3ea2f0c17e57b60ea2626f964cd4d1', 'bytes': 18937}}
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
