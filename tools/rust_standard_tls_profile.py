"""Pinned std TLS source overlay; never install/qualify an incomplete sysroot."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tarfile
import tomllib

from tools import rust_standard_clock_profile as clock
from tools.dev_workflow.common import digest, encode, require
from tools.rust_capsule_project import checked_path, inventory, read_file, write_json

ROOT = Path(__file__).resolve().parents[1]
PROFILE = 'lsf-rust-std-logical-tls-source-v1'
SELECTOR = b'all(target_arch = "wasm32", target_os = "unknown", target_vendor = "unknown", target_env = "")'
ORIGINALS = {
    'std/src/sys/thread_local/mod.rs': '56a94ba2ad4d2c30fc82c8f0b1c728bc05f8817340e7821019f7b05606a7456e',
    'std/src/sys/thread_local/os.rs': 'bd5344458222df838065f33a1a00f6d8c4bdc7cb6db79d722cd1593f47d24355',
    'std/src/sys/thread_local/no_threads.rs': '5fbac3fec13b7c337411b7875c47d07538fdae7a53008310d48cd830a4718904',
    'std/src/rt.rs': 'f435576c645fb30eaca560e819c2a113b556452d79c0303f49ffd4487018c01f',
}
PINS = {
    'wasmtime': ('48.0.4', '10d804b62a332e9221b1441ed56f4da4309494423958efe42c7b0d67a2334ca4'),
    'wasmtime-environ': ('48.0.4', 'e0c2ac967bc75bf01e8619f446d75c8276df784917fda6afe922ee68cd642fa9'),
    'wit-bindgen': ('0.62.0', '53cb4b5556c3a791e86838ea287782bdafa704d55b0e68b5b81a3a16b9ea5f4b'),
}
RECIPE = ('tools/rust_standard_tls_profile.py', 'sdk/rust-standard-runtime/tls.rs',
          'sdk/rust-standard-runtime/activation-abi.json',
          'wit/platform/activation-runtime/package.wit', 'rust-toolchain.toml', 'Cargo.toml', 'Cargo.lock')
BRANCHES = (
    (b'cfg_select! {\n    any(', b'cfg_select! {\n    ' + SELECTOR + b''' => {
        mod os;
        pub use os::{Storage, thread_local_inner, value_align};
        pub(crate) use os::{LocalPointer, local_pointer};
    }
    any('''),
    (b'pub(crate) mod guard {\n    cfg_select! {\n', b'pub(crate) mod guard {\n    cfg_select! {\n        ' + SELECTOR + b''' => {
            pub(crate) fn enable() { super::key::lsf::mark_cleanup(); }
        }
'''),
    (b'pub(crate) mod key {\n    cfg_select! {\n', b'pub(crate) mod key {\n    cfg_select! {\n        ' + SELECTOR + b''' => {
            pub(crate) mod lsf;
            pub(super) use lsf::{Key, LazyKey, get, set};
        }
'''),
)


def originals(archive: Path):
    raw = read_file(archive, 32 * 1024 * 1024)
    require(hashlib.sha256(raw).hexdigest() == clock.SOURCE_ARCHIVE_SHA256, 'rust-tls-source-archive-pin')
    selected = {}
    with tarfile.open(archive, 'r:xz') as source:
        for entry in source:
            if '/library/' not in entry.name: continue
            name = entry.name.split('/library/', 1)[1]
            if name not in ORIGINALS: continue
            require(entry.isfile() and entry.size <= 1024 * 1024 and name not in selected,
                    'rust-tls-source-original-entry')
            data = source.extractfile(entry).read()
            require(len(data) == entry.size and hashlib.sha256(data).hexdigest() == ORIGINALS[name],
                    'rust-tls-source-original-preimage')
            selected[name] = data
    require(set(selected) == set(ORIGINALS), 'rust-tls-source-original-missing')
    require(read_file(archive, 32 * 1024 * 1024) == raw, 'rust-tls-source-archive-mutated')
    return selected


def overlay(original: dict[str, bytes], tls: bytes):
    require(set(original) == set(ORIGINALS), 'rust-tls-source-original-set')
    for name, data in original.items():
        require(hashlib.sha256(data).hexdigest() == ORIGINALS[name], 'rust-tls-source-original-preimage')
    source = original['std/src/sys/thread_local/mod.rs']
    for before, after in BRANCHES:
        require(source.count(before) == 1, 'rust-tls-selector-shape')
        source = source.replace(before, after, 1)
    return {'std/src/sys/thread_local/mod.rs': source,
            'std/src/sys/thread_local/key/lsf.rs': tls}


def tool_pins(inputs):
    require(tomllib.loads(inputs['rust-toolchain.toml'].decode())['toolchain']['channel'] == clock.RUST,
            'rust-tls-compiler-pin')
    packages = tomllib.loads(inputs['Cargo.lock'].decode())['package']
    workspace = tomllib.loads(inputs['Cargo.toml'].decode())['workspace']['dependencies']
    for name in ('wasmtime', 'wit-bindgen'):
        value = workspace[name]
        version = value.get('version') if isinstance(value, dict) else value
        require(version == '=' + PINS[name][0],
                'rust-tls-selected-engine-or-bindgen-pin')
    for name, (version, checksum) in PINS.items():
        require(any(p.get('name') == name and p.get('version') == version and p.get('checksum') == checksum
                    for p in packages), 'rust-tls-engine-or-bindgen-pin')
    abi = json.loads(inputs['sdk/rust-standard-runtime/activation-abi.json'])
    require(abi['target'] == clock.TARGET and abi['runtimeWitDigest'] == digest(inputs['wit/platform/activation-runtime/package.wit']),
            'rust-tls-canonical-abi-preimage')


def prepare(archive: Path, output: Path, *, target=clock.TARGET, rust=clock.RUST):
    require(target == clock.TARGET and rust == clock.RUST, 'rust-tls-profile-not-maintained')
    archive, output = checked_path(archive), checked_path(output)
    require(not output.exists() and not output.is_symlink(), 'rust-tls-output-must-be-fresh')
    original = originals(archive)
    inputs = {name: read_file(ROOT / name) for name in RECIPE}
    tool_pins(inputs)
    selected = overlay(original, inputs['sdk/rust-standard-runtime/tls.rs'])
    output.mkdir(mode=0o700, parents=True)
    for directory, files in (('originals', original), ('overlay/library', selected)):
        for name, data in files.items():
            path = output / directory / name; path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream: stream.write(data)
    value = {'schemaVersion': 'latent.rust.std-tls-source-overlay.v1', 'profile': PROFILE,
        'target': target, 'rust': rust, 'rustCommit': clock.RUST_COMMIT,
        'sourceArchiveDigest': 'sha256:' + clock.SOURCE_ARCHIVE_SHA256,
        'originalInputsDigest': digest(inventory(original)), 'originals': {name: digest(data) for name, data in original.items()},
        'selectedInputsDigest': digest(inventory(selected)), 'selected': {name: digest(data) for name, data in selected.items()},
        'recipeDigest': digest(inventory(inputs)), 'runtimeWitDigest': digest(inputs['wit/platform/activation-runtime/package.wit']),
        'toolPins': {name: {'version': p[0], 'archiveDigest': 'sha256:' + p[1]} for name, p in PINS.items()},
        'candidateApis': ['std::thread_local!', 'std internal current Thread/Parker LocalPointer'],
        'contextSlot': 1, 'witBindgenContextSlotPreserved': 0, 'nativeHostTlsUsed': False,
        'originalLedgerOwner': 'native', 'entryAdmissionBeforeInitializer': True,
        'memoryBoundary': 'original Wasm linear-memory limiter plus original runtime owner metadata reservation',
        'lifecycleBinding': 'requires owned thread bootstrap and post-frame retirement; not yet selected',
        'qualification': 'unqualified-source', 'installedSysroot': False,
        'automaticBuilderSelection': 'pending-qualified-sysroot-and-thread-lifecycle',
        'compilerObservation': 'not-observed', 'sysrootObservation': 'not-built',
        'guestSchedulingObservation': 'not-observed', 'concurrencyClaimed': False,
        'applicationRuntimeInjectionRequired': False,
        'providerInstallationAndRuntimeGrantRequired': True,
        'authority': 'runtime support only; no application effect grant conferred',
        'remainingGates': ['qualified rebuilt sysroot and owned world metadata',
                          'thread/start/stack switch and every suspension resume hook',
                          'post-frame ordinary export/accepted-work retirement integration',
                          'engine/guest ledger admission and measured physical stack/heap costs',
                          'real signed std TLS/independent-thread/cancel/trap/fresh-tenant components']}
    value['identity'] = digest(encode(value))
    require(len(encode(value)) <= 65536, 'rust-tls-receipt-byte-limit')
    require({name: read_file(ROOT / name) for name in RECIPE} == inputs, 'rust-tls-recipe-mutated')
    require(originals(archive) == original, 'rust-tls-original-source-mutated')
    write_json(output / 'std-tls-source-overlay.json', value)
    return value
