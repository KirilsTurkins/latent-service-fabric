"""Exact successful CLI-dispatch producer; original21b evidence remains immutable."""
from pathlib import Path
import sys
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.sdk_native_products_reader import FrozenNativeProducts

SOURCE = '6fd19eab2c224fc31481d03de5008de4d3e4429e'
RUN = 39516047085
JOB = 118948325038
ARTIFACT = {'id': 12308282426, 'size_in_bytes': 66196624,
    'digest': 'sha256:2a8bdd8946a06ccc9f15ab599cdc869a450cc7c459c07a095e3cfb942f9518f1'}
RECEIPTS = {
    'native-products.json': {'sha256': 'sha256:253198f40836c349fe82b28363ca312a3ed51f9b022866623be995a967acece9', 'bytes': 25782},
    'source-inputs.json': {'sha256': 'sha256:02cd78c08043387f8c0d2a5bbf1624357b3071d3b9565fca92748876c4edf643', 'bytes': 22275}}
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
    receipts=RECEIPTS, branch='fix/release-preparation-cli-dispatch-20261021', stages=STAGES,
    event='workflow_dispatch', include_protocol=True)
prepare = READER.prepare
verify_prepared = READER.verify_prepared
native_products = READER.native_products

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args().output)
