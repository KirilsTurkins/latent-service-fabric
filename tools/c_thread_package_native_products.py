"""Immutable f625 C-packaging/ordinary-worker products; guest qualification is separate."""
from pathlib import Path
import sys
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.sdk_native_products_reader import FrozenNativeProducts

SOURCE = 'f6251df89851de98cb869784d095ad5cc2e5b385'
RUN = 39621720110
JOB = 119296651794
ARTIFACT = {'id': 12355629104, 'size_in_bytes': 70117766, 'digest': 'sha256:eff899b51ceeea5af53c34ccb546b18a80dba735763730d517f2b65dc2b26254'}
RECEIPTS = {'native-products.json': {'sha256': 'sha256:f2369a8dcd9bc477dc19afec0a3dbf72ff9fd6251c2e2cb5a916d97590539edd', 'bytes': 27125}, 'source-inputs.json': {'sha256': 'sha256:2d4b53ee1d52592fd57dbb002416ea2839b2b3b85f402d92d2cd5ac89539af34', 'bytes': 22275}}
STAGES = ('rust-version', 'normal-host-build', 'closed-http-refusal-controls', 'neutral-resource-signing-controls', 'positive-timer-observer-controls', 'phase-nominal-type-owner-controls', 'descriptive-native-thread-proof-controls', 'phase-emitted-type-owner-controls', 'independent-http-configuration-controls', 'independent-http-dispatch-controls', 'independent-http-secret-controls', 'phase-operational-metadata-controls', 'phase-operational-binding-controls', 'release-preparation-protocol-reader-controls', 'release-preparation-deadline-controls', 'release-preparation-web-readiness-controls', 'release-preparation-rpc-controls', 'release-preparation-cli-controls', 'release-preparation-projection-controls', 'release-preparation-transport-controls', 'release-preparation-command-name-controls', 'release-preparation-dispatch-controls', 'c-original-and-final-proof-controls', 'c-profile-1', 'c-profile-2', 'c-profile-3', 'c-profile-4', 'c-profile-5', 'c-profile-6', 'c-profile-7', 'c-profile-8', 'c-profile-9', 'c-profile-10', 'c-profile-11', 'ordinary-async-worker-owner-controls')

READER = FrozenNativeProducts(source=SOURCE, run=RUN, job=JOB, artifact=ARTIFACT,
    receipts=RECEIPTS, branch='diag/c-thread-package-native-products-20261021',
    stages=STAGES, event='workflow_dispatch', include_protocol=True)
prepare = READER.prepare
verify_prepared = READER.verify_prepared
native_products = READER.native_products

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args().output)
