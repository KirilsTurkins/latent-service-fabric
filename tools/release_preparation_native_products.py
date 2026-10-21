"""Exact successful PrepareRelease producer; no guest qualification or old tuple mutation."""
from pathlib import Path
import sys
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.sdk_native_products_reader import FrozenNativeProducts

SOURCE = '21b2c84c74881701149115dd8511063c85800b47'
RUN = 39509107706
JOB = 118925373342
ARTIFACT = {'id': 12305592299, 'size_in_bytes': 66195901,
    'digest': 'sha256:35ce77454a17df4706e26a84582b8aa86de26ec03f2b95b5af24513e04e3b672'}
RECEIPTS = {
    'native-products.json': {'sha256': 'sha256:5137cb0c20a481f3cf81b7125a76b1dcff4cfbd959f2dc801810c1784dc548fd', 'bytes': 25662},
    'source-inputs.json': {'sha256': 'sha256:04b943b830a3fc29e598d23268f58f27095ed695a839c81beb0bb530413c40c4', 'bytes': 22275}}
STAGES = ('rust-version', 'normal-host-build', 'closed-http-refusal-controls',
    'neutral-resource-signing-controls', 'positive-timer-observer-controls',
    'phase-nominal-type-owner-controls', 'phase-emitted-type-owner-controls',
    'independent-http-configuration-controls', 'independent-http-dispatch-controls',
    'independent-http-secret-controls', 'phase-operational-metadata-controls',
    'phase-operational-binding-controls', 'release-preparation-protocol-reader-controls',
    'release-preparation-deadline-controls', 'release-preparation-web-readiness-controls',
    'release-preparation-rpc-controls', 'release-preparation-cli-controls',
    'release-preparation-projection-controls', 'release-preparation-transport-controls',
    'release-preparation-command-name-controls')
READER = FrozenNativeProducts(source=SOURCE, run=RUN, job=JOB, artifact=ARTIFACT,
    receipts=RECEIPTS, branch='feat/tenant-release-preparation-20261020', stages=STAGES,
    event='workflow_dispatch', include_protocol=True)
prepare = READER.prepare
verify_prepared = READER.verify_prepared
native_products = READER.native_products

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args().output)
