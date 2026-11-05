"""Exact 678b Wasmtime 48.0.8 SDK products; no signed guest qualification."""
from pathlib import Path
import sys
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.sdk_native_products_reader import FrozenNativeProducts

SOURCE = '678b19d42b26a12ac35f3d6de525029b82e169f7'
RUN = 41921393987
JOB = 126894520371
EVENT = 'workflow_dispatch'
BRANCH = 'feat/wasmtime-4808-678b-owner-20261104'
ARTIFACT = {'id': 13369717189,
 'size_in_bytes': 72700380,
 'digest': 'sha256:4a5b49fb2b27775a75fa4eae71daa25dc098fb999e6690b405575a08bab9688d'}
RECEIPTS = {'native-products.json': {'sha256': 'sha256:2dbd7bcec568f99174d5560a39958ded8b0381fcdbedc4ed7ffa0e195ef7ac82',
                          'bytes': 26188},
 'source-inputs.json': {'sha256': 'sha256:a001dc39c6a12f2aff7a72e4140e7fb87520c790dda75553065e86aa77681a77',
                        'bytes': 22445}}
STAGES = ('rust-version',
 'normal-host-build',
 'closed-http-refusal-controls',
 'neutral-resource-signing-controls',
 'positive-timer-observer-controls',
 'phase-nominal-type-owner-controls',
 'descriptive-native-thread-proof-controls',
 'phase-emitted-type-owner-controls',
 'independent-http-configuration-controls',
 'independent-http-dispatch-controls',
 'independent-http-secret-controls',
 'phase-operational-metadata-controls',
 'phase-operational-binding-controls',
 'release-preparation-protocol-reader-controls',
 'release-preparation-deadline-controls',
 'release-preparation-web-readiness-controls',
 'release-preparation-rpc-controls',
 'release-preparation-cli-controls',
 'release-preparation-projection-controls',
 'release-preparation-transport-controls',
 'release-preparation-command-name-controls',
 'release-preparation-dispatch-controls',
 'ordinary-async-worker-owner-controls')

READER = FrozenNativeProducts(source=SOURCE, run=RUN, job=JOB, artifact=ARTIFACT,
    receipts=RECEIPTS, branch=BRANCH, stages=STAGES, event=EVENT, include_protocol=True)
prepare = READER.prepare
verify_prepared = READER.verify_prepared
native_products = READER.native_products

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args().output)
