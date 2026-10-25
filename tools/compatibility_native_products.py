"""One source-exact normal bundle; an unfilled tuple is a strict refusal.

The concrete tuple is filled only after the reviewed normal prerequisite has
actually passed. This is neither a latest-run selector nor a historical reader
exception. All existing immutable native readers remain untouched.
"""
from pathlib import Path
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.phase2_operator_process import require
from tools.sdk_native_products_reader import FrozenNativeProducts

QUALIFIED = {
    'source': '17e8e622ecd3307a246196cbb5ca06c0fac37301',
    'run': 40208542534, 'job': 121214620779,
    'branch': 'feat/sdk-compatibility-native-prereq-20261025',
    'artifact': {'id': 12604978936, 'size_in_bytes': 71859543,
        'digest': 'sha256:9a78790a28e794a9be522e704b4c9e6885e6722a82474d61cc3867dce4f41ebf'},
    'receipts': {
        'native-products.json': {'bytes': 26869,
            'sha256': 'sha256:950fd228bf907e22f6545c3e43195e9e76b44907656e72bf5cd971199b9c76e7'},
        'source-inputs.json': {'bytes': 22447,
            'sha256': 'sha256:d96965513c8df4e43504225dce8eccf7f1b643d30d417e78e5b5923a18410ec0'}}}
STAGES = (
    'rust-version', 'compiler-diagnostic-wasm-tools-version', 'compiler-diagnostic-stack-parse',
    'normal-host-build', 'closed-http-refusal-controls', 'neutral-resource-signing-controls',
    'positive-timer-observer-controls', 'phase-nominal-type-owner-controls', 'descriptive-native-thread-proof-controls',
    'phase-emitted-type-owner-controls', 'independent-http-configuration-controls', 'independent-http-dispatch-controls',
    'independent-http-secret-controls', 'phase-operational-metadata-controls', 'phase-operational-binding-controls',
    'release-preparation-protocol-reader-controls', 'release-preparation-deadline-controls',
    'release-preparation-web-readiness-controls', 'release-preparation-rpc-controls', 'release-preparation-cli-controls',
    'release-preparation-projection-controls', 'release-preparation-transport-controls',
    'release-preparation-command-name-controls', 'release-preparation-dispatch-controls',
    'ordinary-async-worker-owner-controls', 'compiler-diagnostic-owner-buckets',
    'compiler-diagnostic-native-memory', 'compiler-diagnostic-engine-stack', 'compiler-diagnostic-actual-stack-component')


def reader():
    require(type(QUALIFIED) is dict and set(QUALIFIED) ==
        {'source', 'run', 'job', 'artifact', 'receipts', 'branch'}, 'compatibility-native-prerequisite-unqualified')
    return FrozenNativeProducts(**QUALIFIED, stages=STAGES, event='workflow_dispatch', include_protocol=True)


def prepare(output: Path): return reader().prepare(output)
def verify_prepared(output: Path): return reader().verify_prepared(output)
def native_products(output: Path): return reader().native_products(output)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args().output)
