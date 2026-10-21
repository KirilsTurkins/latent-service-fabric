"""Immutable selected C/RootOnly producer; no guest qualification is implied."""
from pathlib import Path
import sys
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.sdk_native_products_reader import FrozenNativeProducts

SOURCE = 'f0d36b38d39a837cef7f6242b4b4a99aa36b8b75'
RUN = 39581446809
JOB = 119159766073
ARTIFACT = {'id': 12338580939, 'size_in_bytes': 68308279, 'digest': 'sha256:512a83eaed2f261e655f1cca569582f9147dadd6fd79a9e1e3e48250a45b2efb'}
RECEIPTS = {'native-products.json': {'sha256': 'sha256:e7d7cdae7ebd371c3dff45ab9daf4b81d7025e215088510059522b1dbe0e41a0', 'bytes': 26887}, 'source-inputs.json': {'sha256': 'sha256:f21a58ad6b8a6536d63a19e90d9985993bd75b62ae8260e9f03d1a80ff421b78', 'bytes': 22275}}
STAGES = ('rust-version', 'normal-host-build', 'closed-http-refusal-controls', 'neutral-resource-signing-controls', 'positive-timer-observer-controls', 'phase-nominal-type-owner-controls', 'phase-emitted-type-owner-controls', 'independent-http-configuration-controls', 'independent-http-dispatch-controls', 'independent-http-secret-controls', 'phase-operational-metadata-controls', 'phase-operational-binding-controls', 'release-preparation-protocol-reader-controls', 'release-preparation-deadline-controls', 'release-preparation-web-readiness-controls', 'release-preparation-rpc-controls', 'release-preparation-cli-controls', 'release-preparation-projection-controls', 'release-preparation-transport-controls', 'release-preparation-command-name-controls', 'release-preparation-dispatch-controls', 'c-original-and-final-proof-controls', 'c-profile-1', 'c-profile-2', 'c-profile-3', 'c-profile-4', 'c-profile-5', 'c-profile-6', 'c-profile-7', 'c-profile-8', 'c-profile-9', 'c-profile-10', 'c-profile-11')

READER = FrozenNativeProducts(source=SOURCE, run=RUN, job=JOB, artifact=ARTIFACT,
    receipts=RECEIPTS, branch='feat/c-thread-native-profile-20261021', stages=STAGES,
    event='workflow_dispatch', include_protocol=True)
prepare = READER.prepare
verify_prepared = READER.verify_prepared
native_products = READER.native_products

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args().output)
