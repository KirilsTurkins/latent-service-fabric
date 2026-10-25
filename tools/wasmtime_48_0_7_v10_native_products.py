"""Exact v10 Wasmtime 48.0.7 normal native products; no signed guest qualification."""
from pathlib import Path
import sys
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.sdk_native_products_reader import FrozenNativeProducts

SOURCE = 'fe1653b42602270005d8f9935c021d7bd7a7412a'
RUN = 40180739956
JOB = 121131080926
EVENT = 'workflow_dispatch'
BRANCH = 'development'
ARTIFACT = {'id': 12593859879,
 'size_in_bytes': 71053947,
 'digest': 'sha256:16014d6ec1a9757d6f1975fdc3813f826b14d626872e87736b3ec5510cb3c8f5'}
RECEIPTS = {'native-products.json': {'sha256': 'sha256:fe17b3affbb585559c92550ed800d0cbca151cfa2e38c74ba408c7470d601687',
                          'bytes': 26188},
 'source-inputs.json': {'sha256': 'sha256:fd1f403fffcd8f1a9b3fe7c552c86fa0d1f678a235c21cf6cdb40b4f889c3437',
                        'bytes': 22447}}
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
