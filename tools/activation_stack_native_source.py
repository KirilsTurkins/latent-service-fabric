"""Closed source projections; compiled products retain their original identity."""
import hashlib
from pathlib import Path

from tools.java_replay_materials import git_source_identity
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import source_identity
from tools.rust_capsule_project import ROOT, read_file

SOURCE = 'c7134289f446cb3171eb0ffd800a94afc2a5209f'
EXTRACTION = '8473afecac55bbf6d67b411b7d7b73820991b289'
PATH = 'apps/latentd/src/config/runtime.rs'
TEST_DEFAULT_FIX = 'd79bd0d49431d95f7cf46297629649682c277b69'
TEST_PATH = 'apps/latentd/src/config/tests/engine.rs'
COMPILED = {
    'sha256': 'sha256:8ae85103a4ea211b686ac7b16222bfa2f6a950a08c5957f9b488785c7f007268',
    'files': 3325, 'bytes': 26391555,
    'scope': 'explicit-apps-crates-rust-sdk-workloads-and-workspace-inputs',
    'hermetic': False, 'implicitCompilerInputs': 'not-attested',
}
EXTRACTED = {**COMPILED,
    'sha256': 'sha256:0d2952689f3ceae7aecc5d2f951be8934e0282e495a5226c0300d8f23a8dedfb',
    'bytes': 26391743,
}
TEST_DEFAULTS = {**COMPILED,
    'sha256': 'sha256:a55ef0a2b05ef959f47bab7b44e817da5f73c1c8afc9faa3364d4520ec0ad200',
    'bytes': 26391846,
}
ORIGINAL_TEST = {
    'sha256': 'sha256:c640fd38d4702aeadc919269086f0653374720ff2db3b22d7f60cab4c27e4e33',
    'bytes': 7524,
}
EXPLICIT_TEST = {
    'sha256': 'sha256:7dd8fee5a7ac533fbcb815a02145291d421129f24899f03e1a2f494c0fda298c',
    'bytes': 7627,
}
_TEST_SUBSTITUTIONS = (
    (b'threading_profile: Default::default(),',
     b'threading_profile: crate::config::model::EngineThreadingProfile::default(),'),
    (b'activation_stack_accounting: Default::default(),',
     b'activation_stack_accounting:\n'
     b'                    crate::config::model::EngineActivationStackAccounting::default(),'),
)
ORIGINAL_FILE = {
    'sha256': 'sha256:afb01d90bba9bbbecf641bc8467075c67fa3b83696e7f37004c25a3cc71d38a6',
    'bytes': 9601,
}
EXTRACTED_FILE = {
    'sha256': 'sha256:439a1879d288e2658b4b95865d6e58bab548e40cc618c0b6e9a8c5b991f70be9',
    'bytes': 9789,
}
_SIGNATURE = (b'fn install_stack_accounting(\n    config: &NodeConfig,\n'
              b'    runtime: &mut WasmtimeConfig,\n) -> Result<(), PlatformError> {\n')
_END = b'    Ok(())\n}\n\n'
_CALL = b'    install_stack_accounting(config, &mut runtime)?;\n'


def _identity(raw):
    return {'sha256': 'sha256:' + hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def _same(value, expected):
    return (type(value) is dict and set(value) == set(expected)
            and all(type(value[key]) is type(item) and value[key] == item
                    for key, item in expected.items()))


def _reverse_extraction(raw):
    require(type(raw) is bytes and len(raw) == EXTRACTED_FILE['bytes']
            and _identity(raw) == EXTRACTED_FILE,
            'activation-native-exact-extracted-file')
    require(raw.count(_SIGNATURE) == raw.count(_CALL) == 1,
            'activation-native-one-fixed-helper-and-call')
    start = raw.index(_SIGNATURE)
    body = start + len(_SIGNATURE)
    end = raw.index(_END, body)
    block = raw[body:end]
    helper = raw[start:end + len(_END)]
    original = raw.replace(helper, b'', 1).replace(_CALL, block, 1)
    require(_identity(original) == ORIGINAL_FILE,
            'activation-native-reverse-extraction-original-preimage')
    return original


def _reverse_test_defaults(raw):
    require(type(raw) is bytes and _identity(raw) == EXPLICIT_TEST,
            'activation-native-exact-explicit-test-file')
    original = raw
    for old, new in _TEST_SUBSTITUTIONS:
        require(original.count(new) == 1 and original.count(old) == 0,
                'activation-native-two-fixed-test-defaults')
        original = original.replace(new, old, 1)
    require(_identity(original) == ORIGINAL_TEST,
            'activation-native-reverse-test-defaults-original-preimage')
    return original


def assert_current(root=ROOT):
    """Verify actual Git/current trees; admit only three complete fixed inputs.

    The second input differs in exactly one pinned helper extraction. Its full
    native aggregate, file bytes and reverse projection all remain mandatory.
    The third adds only two pinned explicit enum defaults in an existing test.
    This never attributes a new source tree to the historical compilation.
    """
    root = Path(root).resolve(strict=True)
    compiled = git_source_identity(SOURCE)
    require(_same(compiled, COMPILED), 'activation-native-exact-compiled-source')
    current = source_identity(root)
    require(any(_same(current, item) for item in (COMPILED, EXTRACTED, TEST_DEFAULTS)),
            'activation-native-exact-current-source')
    changes = []
    if current != compiled:
        _reverse_extraction(read_file(root / PATH, 16 * 1024))
        changes.append({'path': PATH, 'reviewedRevision': EXTRACTION,
            'operation': 'reverse-fixed-stack-profile-helper-extraction',
            'compiledFile': dict(ORIGINAL_FILE), 'currentFile': dict(EXTRACTED_FILE),
            'reverseInlineByteExact': True,
            'allOtherNativeFilesByteExact': 3323 if current == TEST_DEFAULTS else 3324})
        if current == TEST_DEFAULTS:
            _reverse_test_defaults(read_file(root / TEST_PATH, 16 * 1024))
            changes.append({'path': TEST_PATH, 'reviewedRevision': TEST_DEFAULT_FIX,
                'operation': 'reverse-two-fixed-explicit-test-defaults',
                'compiledFile': dict(ORIGINAL_TEST), 'currentFile': dict(EXPLICIT_TEST),
                'reverseSubstitutionsByteExact': True, 'allOtherNativeFilesByteExact': 3323})
    return {'compiledSourceRevision': SOURCE, 'compiledNativeSource': compiled,
            'consumerNativeSource': current, 'compiledSourceByteExact': current == compiled,
            'reviewedSourceChanges': changes}
