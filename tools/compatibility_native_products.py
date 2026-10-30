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
from tools.phase3_resource_identity import file_identity, source_identity
from tools.rust_capsule_project import ROOT
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

# Two exact censuses, not an ignored-path rule. The second differs ONLY in the
# ten generated management-client constants. latent-sdk is not a dependency of
# any of the five produced host targets; their Cargo/build.rs/proto inputs are
# byte-identical. The descriptor JSON is a test oracle, not the compiled proto.
# The original archive/source/material attestations are never rewritten.
ORIGINAL_SOURCE = {'sha256': 'sha256:5db73985742dcd383f3b76491b36560267f31fba24195689e27a743e5b0b95a4',
    'files': 3753, 'bytes': 34470544, 'scope': 'explicit-apps-crates-rust-sdk-workloads-and-workspace-inputs',
    'hermetic': False, 'implicitCompilerInputs': 'not-attested'}
CLIENT_DATA_SOURCE = {**ORIGINAL_SOURCE,
    'sha256': 'sha256:f75950327458321d594393d94e3f14f3765786c92d3e0adbfbbe8d3e626f7a72', 'bytes': 34471085}
NON_COMPILED_DATA = {
    'sdk/rust/src/management.rs': {
        'before': {'bytes': 22456, 'sha256': 'sha256:885be3d11d99eb2004a70e4cc1bdc12153a30fd38f28c15e213b4111bee93d07'},
        'after': {'bytes': 22997, 'sha256': 'sha256:2e5114f48efb5015fe54a5b5ed2ff0c42ab52381a089d1cdd2b211706629e5c9'}},
    'api/proto/phase1-descriptor-contract.json': {
        'before': {'bytes': 249286, 'sha256': 'sha256:b08186d23e2c55063cfb2a6c69e0a48cc1f6d57ba063967ef0c9d2e6b704ba95'},
        'after': {'bytes': 249917, 'sha256': 'sha256:0decef676919a3c250077d4d2de701e6a543f7af6ec2c7055c364c309b0aa184'}}}


def current_source(producer_inputs, *, root=ROOT):
    """Check one reviewed noncompiled-data migration without relabeling a build."""
    require(producer_inputs['native'] == ORIGINAL_SOURCE, 'compatibility-native-original-producer-source')
    current = source_identity(root)
    require(current in (ORIGINAL_SOURCE, CLIENT_DATA_SOURCE), 'compatibility-native-unreviewed-current-source')
    version = 'before' if current == ORIGINAL_SOURCE else 'after'
    for name, identities in NON_COMPILED_DATA.items():
        require(file_identity(root / name, 8 * 1024**2) == identities[version],
            'compatibility-native-incomplete-or-unreviewed-client-data')
    for name, expected in producer_inputs['materials'].items():
        if name.startswith(('api/proto/', 'wit/', 'schemas/', 'examples/echo-contract/wit/')) \
                or name == '.cargo/managed-guest.toml':
            if name in NON_COMPILED_DATA:
                require(expected == NON_COMPILED_DATA[name]['before'],
                    'compatibility-native-original-material-not-rebound')
            else:
                require(file_identity(root / name, 8 * 1024**2) == expected,
                    'compatibility-native-original-compiled-auxiliary-input')
    require(producer_inputs['materials'].get('api/proto/phase1-descriptor-contract.json') ==
        NON_COMPILED_DATA['api/proto/phase1-descriptor-contract.json']['before'],
        'compatibility-native-original-descriptor-material')
    return {'currentSource': current, 'originalProducerSource': ORIGINAL_SOURCE,
        'sourceRelabeled': False, 'migration': 'none' if version == 'before' else 'exact-ten-generated-client-constants',
        'nonCompiledData': {name: row[version] for name, row in NON_COMPILED_DATA.items()},
        'compiledInputScope': 'same-five-targets-Cargo-build-rs-proto-and-linked-inputs',
        'historicalArchiveAndMaterialsUnchanged': True}


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
