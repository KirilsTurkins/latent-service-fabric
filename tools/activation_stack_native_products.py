"""Immutable c713 C/ordinary-worker products; guest qualification is separate."""
from pathlib import Path
import sys
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.sdk_native_products_reader import FrozenNativeProducts

SOURCE = 'c7134289f446cb3171eb0ffd800a94afc2a5209f'
RUN = 39598763649
JOB = 119217613970
ARTIFACT = {'id': 12345773653, 'size_in_bytes': 68318919, 'digest': 'sha256:de16d786e7a2a72bae7176451e4887b2afca9f2ec08f9583e2b1caf72d38c491'}
RECEIPTS = {'native-products.json': {'sha256': 'sha256:bec02c077f6df2167b77dff4c41f2cd79b14a501f4926b42dd06d69174d02523', 'bytes': 27004}, 'source-inputs.json': {'sha256': 'sha256:e0c607e6f6d62a0c2bc85f9e127f985c26ecac88d506bec74f8de533bcb4aa76', 'bytes': 22275}}
STAGES = ('rust-version', 'normal-host-build', 'closed-http-refusal-controls', 'neutral-resource-signing-controls', 'positive-timer-observer-controls', 'phase-nominal-type-owner-controls', 'phase-emitted-type-owner-controls', 'independent-http-configuration-controls', 'independent-http-dispatch-controls', 'independent-http-secret-controls', 'phase-operational-metadata-controls', 'phase-operational-binding-controls', 'release-preparation-protocol-reader-controls', 'release-preparation-deadline-controls', 'release-preparation-web-readiness-controls', 'release-preparation-rpc-controls', 'release-preparation-cli-controls', 'release-preparation-projection-controls', 'release-preparation-transport-controls', 'release-preparation-command-name-controls', 'release-preparation-dispatch-controls', 'c-original-and-final-proof-controls', 'c-profile-1', 'c-profile-2', 'c-profile-3', 'c-profile-4', 'c-profile-5', 'c-profile-6', 'c-profile-7', 'c-profile-8', 'c-profile-9', 'c-profile-10', 'c-profile-11', 'ordinary-async-worker-owner-controls')

READER = FrozenNativeProducts(source=SOURCE, run=RUN, job=JOB, artifact=ARTIFACT,
    receipts=RECEIPTS, branch='diag/activation-stack-native-products-20261021',
    stages=STAGES, event='workflow_dispatch', include_protocol=True)
prepare = READER.prepare
verify_prepared = READER.verify_prepared
native_products = READER.native_products

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args().output)
