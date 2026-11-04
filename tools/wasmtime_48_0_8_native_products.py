"""Exact a727 Wasmtime 48.0.8 SDK products; no signed guest qualification."""
from pathlib import Path
import sys
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.sdk_native_products_reader import FrozenNativeProducts

SOURCE = 'a727d409243b5ae80218a8ff393e87c1428625f7'
RUN = 41908612327
JOB = 126849878597
EVENT = 'workflow_dispatch'
BRANCH = 'feat/wasmtime-4808-a727-owner-20261104'
ARTIFACT = {'id': 13365320985,
 'size_in_bytes': 72700405,
 'digest': 'sha256:f348c20182cc5e656b87036ded8a3be70723493d215eb6436bbc43db9c15e267'}
RECEIPTS = {'native-products.json': {'sha256': 'sha256:5075c1fe6a8ccf128e23161d88aef2b77d4f5b2333d0a32cf9ebf9fab3411c11',
                          'bytes': 26187},
 'source-inputs.json': {'sha256': 'sha256:1cc2e9bd69782afc934525f9e8e5467f771f0fefcce72b4d876a87d71c6057d9',
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
