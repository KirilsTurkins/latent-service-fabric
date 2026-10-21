"""Frozen current pool-retirement producer; historical6fd evidence remains immutable."""
from pathlib import Path
import sys
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.sdk_native_products_reader import FrozenNativeProducts

SOURCE = '357eecbd7744bbc026741d241b679966d14b0e95'
RUN = 39532689221
JOB = 119002071182
ARTIFACT = {'id': 12316652021, 'size_in_bytes': 66201411,
    'digest': 'sha256:3ccc2717ac335233335d0a37e5e173be786e201ca0619a594894ba0503776b6c'}
RECEIPTS = {
    'native-products.json': {'sha256': 'sha256:3a9c558088ef752d35efadbe0f0e77c0b09848b32f383acd531bf2ea0b98fa83', 'bytes': 25783},
    'source-inputs.json': {'sha256': 'sha256:22c362cbe76391864c6d716e1e383f64204c60e5fdf96d85c80a9247205fd7ba', 'bytes': 22275}}
STAGES = ('rust-version', 'normal-host-build', 'closed-http-refusal-controls',
    'neutral-resource-signing-controls', 'positive-timer-observer-controls',
    'phase-nominal-type-owner-controls', 'phase-emitted-type-owner-controls',
    'independent-http-configuration-controls', 'independent-http-dispatch-controls',
    'independent-http-secret-controls', 'phase-operational-metadata-controls',
    'phase-operational-binding-controls', 'release-preparation-protocol-reader-controls',
    'release-preparation-deadline-controls', 'release-preparation-web-readiness-controls',
    'release-preparation-rpc-controls', 'release-preparation-cli-controls',
    'release-preparation-projection-controls', 'release-preparation-transport-controls',
    'release-preparation-command-name-controls', 'release-preparation-dispatch-controls')
READER = FrozenNativeProducts(source=SOURCE, run=RUN, job=JOB, artifact=ARTIFACT,
    receipts=RECEIPTS, branch='diag/sdk-native-installed-http-20261021', stages=STAGES,
    event='workflow_dispatch', include_protocol=True)
prepare = READER.prepare
verify_prepared = READER.verify_prepared
native_products = READER.native_products

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args().output)
