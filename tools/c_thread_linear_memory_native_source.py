"""Exact v7 compilation or its reviewed unselected stream-test correction."""
import hashlib
from pathlib import Path

from tools.java_replay_materials import git_source_identity
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import source_identity
from tools.rust_capsule_project import ROOT, read_file

SOURCE = 'f5351a9331ed954c49ae83f2f4004e0f96d25d0e'
FIXTURE_FIX = 'ff5aadaecd11874f53aa80e56ffdfff0efda312b'
PATH = 'crates/latent-wasmtime/tests/outbound_streams.rs'
COMPILED = {
    'sha256': 'sha256:6503419aaf79eba04a8c3358c1dd6a91458fe3e7f447413bcff7da6025a0bc96',
    'files': 3622, 'bytes': 31499697,
    'scope': 'explicit-apps-crates-rust-sdk-workloads-and-workspace-inputs',
    'hermetic': False, 'implicitCompilerInputs': 'not-attested',
}
CORRECTED = {**COMPILED,
    'sha256': 'sha256:794420dfe99436c287fffd34516f0cff90e391bd9f0d9f58433c796c96891483',
    'bytes': 31499866,
}
ORIGINAL_FILE = {
    'sha256': 'sha256:a1c21e2afc9eb7a5c5561628ad8517236a6223d635dea022db16ba9c6b52b4c1',
    'bytes': 9989,
}
CORRECTED_FILE = {
    'sha256': 'sha256:6ef8e0e9b36c3c9fadd51a5a3d583a67f741e7f3f32fb12e7fe983c067047c1b',
    'bytes': 10158,
}
_INSERTION = (b'        assert!(control.budget.host_memory_bytes() >= output.capacity() as u64);\n'
              b'        assert_eq!(control.budget.outstanding_reservations(), 1);\n'
              b'        drop(output);\n')


def _identity(raw):
    return {'sha256': 'sha256:' + hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def _same(value, expected):
    return (type(value) is dict and set(value) == set(expected)
            and all(type(value[key]) is type(item) and value[key] == item
                    for key, item in expected.items()))


def _reverse_fixture(raw):
    require(type(raw) is bytes and _identity(raw) == CORRECTED_FILE,
            'c-thread-v7-exact-corrected-stream-fixture')
    require(raw.count(_INSERTION) == 1, 'c-thread-v7-one-result-drop-fixture-insertion')
    original = raw.replace(_INSERTION, b'', 1)
    require(_identity(original) == ORIGINAL_FILE,
            'c-thread-v7-reverse-stream-fixture-byte-exact')
    return original


def assert_current(root=ROOT):
    root = Path(root).resolve(strict=True)
    compiled = git_source_identity(SOURCE)
    require(_same(compiled, COMPILED), 'c-thread-v7-exact-compiled-native-source')
    current = source_identity(root)
    require(any(_same(current, item) for item in (COMPILED, CORRECTED)),
            'c-thread-v7-exact-current-native-source')
    changes = []
    if current != compiled:
        _reverse_fixture(read_file(root / PATH, 64 * 1024))
        changes.append({'path': PATH, 'reviewedRevision': FIXTURE_FIX,
            'operation': 'reverse-fixed-unselected-stream-result-drop-test',
            'compiledFile': dict(ORIGINAL_FILE), 'currentFile': dict(CORRECTED_FILE),
            'reverseSubstitutionByteExact': True, 'allOtherNativeFilesByteExact': 3621,
            'shippingProductionByteExact': True, 'all114SelectedLibCasesByteExact': True})
    return {'compiledSourceRevision': SOURCE, 'compiledNativeSource': compiled,
            'consumerNativeSource': current, 'compiledSourceByteExact': current == compiled,
            'reviewedSourceChanges': changes}
