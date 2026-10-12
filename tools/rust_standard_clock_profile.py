"""Authenticated std platform source overlay; never claim an installed sysroot."""
from __future__ import annotations

import hashlib
from pathlib import Path
import tarfile

from tools.dev_workflow.common import digest, encode, require
from tools.rust_capsule_project import checked_path, inventory, read_file, write_json

ROOT = Path(__file__).resolve().parents[1]
PROFILE = 'lsf-rust-std-clock-source-v1'
TARGET = 'wasm32-unknown-unknown'
RUST = '1.97.1'
RUST_COMMIT = '8bab26f4f68e0e26f0bb7960be334d5b520ea452'
SOURCE_ARCHIVE_SHA256 = 'e9a1e616d04c6845895c827a178b9227f7c7199f3f4a80af81ab3aff7b80156b'
ORIGINALS = {
    'std/src/sys/time/mod.rs': '449afdd86955252a302d889032a6cb2cbb04dd786f8cb81d9a9059ad933e7e4c',
    'std/src/sys/time/unsupported.rs': 'e1022bb35359dfaffdb76c4b14d03360ed1ccf8e9b002a89aacec16249c3444a',
    'std/src/sys/thread/unsupported.rs': 'cbdbe5561b93229d695732485c6a981e6d97f2a063436545bdbdea37848df268',
    'std/src/sys/sync/mutex/no_threads.rs': 'c790a191cb1bee4a02ae7d52e6945bdf4e1af15e34ea6b1b12574e0e5f5e51f6',
}
RECIPE = ('tools/rust_standard_clock_profile.py', 'sdk/rust-standard-runtime/clock.rs',
          'wit/platform/clock/package.wit', 'rust-toolchain.toml')
UNQUALIFIED = ('std::thread::Builder::spawn', 'std::thread::JoinHandle::join',
    'std::thread::sleep', 'std::thread::yield_now', 'thread_local concurrent isolation',
    'std::sync blocking mutex/condvar/channel', 'default executor/reactor construction',
    'compiler checkpoints and bounded spin-loop progress', 'std::net/socket/DNS/readiness')


def originals(archive: Path):
    raw = read_file(archive, 32 * 1024 * 1024)
    require(hashlib.sha256(raw).hexdigest() == SOURCE_ARCHIVE_SHA256, 'rust-std-source-archive-pin')
    selected = {}
    with tarfile.open(archive, 'r:xz') as source:
        for item in source:
            if '/library/' not in item.name: continue
            name = item.name.split('/library/', 1)[1]
            if name not in ORIGINALS: continue
            require(item.isfile() and item.size <= 1024 * 1024 and name not in selected,
                    'rust-std-source-original-entry')
            data = source.extractfile(item).read()
            require(len(data) == item.size and hashlib.sha256(data).hexdigest() == ORIGINALS[name],
                    'rust-std-source-original-preimage')
            selected[name] = data
    require(set(selected) == set(ORIGINALS), 'rust-std-source-original-missing')
    require(read_file(archive, 32 * 1024 * 1024) == raw, 'rust-std-source-archive-mutated')
    return selected


def overlay(original: dict[str, bytes], clock: bytes):
    require(set(original) == set(ORIGINALS), 'rust-std-source-original-set')
    for name, value in original.items():
        require(hashlib.sha256(value).hexdigest() == ORIGINALS[name], 'rust-std-source-original-preimage')
    selector = b'    _ => {\n        mod unsupported;\n        use unsupported as imp;\n    }'
    require(original['std/src/sys/time/mod.rs'].count(selector) == 1, 'rust-std-clock-selector-shape')
    selected = b'''    all(target_arch = "wasm32", target_os = "unknown", target_vendor = "unknown", target_env = "") => {
        mod lsf;
        use lsf as imp;
    }
''' + selector
    return {'std/src/sys/time/mod.rs': original['std/src/sys/time/mod.rs'].replace(selector, selected),
            'std/src/sys/time/lsf.rs': clock}


def prepare(archive: Path, output: Path, *, target=TARGET, rust=RUST):
    require(target == TARGET and rust == RUST, 'rust-std-clock-profile-target-or-compiler-not-maintained')
    archive, output = checked_path(archive), checked_path(output)
    require(not output.exists() and not output.is_symlink(), 'rust-std-clock-output-must-be-fresh')
    original = originals(archive)
    inputs = {name: read_file(ROOT / name) for name in RECIPE}
    selected = overlay(original, inputs['sdk/rust-standard-runtime/clock.rs'])
    # Only changed platform files are staged. The original archive and each
    # reviewed preimage remain attributable and no installed compiler changes.
    output.mkdir(mode=0o700, parents=True)
    for directory, files in (('originals', original), ('overlay/library', selected)):
        for name, raw in files.items():
            path = output / directory / name; path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream: stream.write(raw)
    value = {'schemaVersion': 'latent.rust.std-source-overlay.v1', 'profile': PROFILE,
        'target': target, 'rust': rust, 'rustCommit': RUST_COMMIT, 'sourceArchiveDigest': 'sha256:' + SOURCE_ARCHIVE_SHA256,
        'originalInputsDigest': digest(inventory(original)), 'originals': {name: digest(raw) for name, raw in original.items()},
        'selectedInputsDigest': digest(inventory(selected)), 'selected': {name: digest(raw) for name, raw in selected.items()},
        'recipeDigest': digest(inventory(inputs)), 'clockWitDigest': digest(inputs['wit/platform/clock/package.wit']),
        'candidateApis': ['std::time::Instant::now', 'std::time::SystemTime::now'],
        'qualification': 'unqualified-source', 'installedSysroot': False, 'automaticBuilderSelection': 'pending-qualified-sysroot',
        'compilerObservation': 'not-observed', 'sysrootObservation': 'not-built',
        'engineObservation': 'not-observed', 'bindgenObservation': 'not-observed',
        'applicationRuntimeInjectionRequired': False, 'concurrencyClaimed': False, 'authority': 'none',
        'unqualifiedOperations': list(UNQUALIFIED), 'requiredLinking': 'owned-clock-world-metadata-and-rebuilt-sysroot',
        'remainingGates': ['build/pin qualified sysroot and component metadata', 'ordinary unchanged source signed component qualification',
                           'thread/TLS/synchronization/timer/loop/reactor/stream ports']}
    value['identity'] = digest(encode(value))
    require(len(encode(value)) <= 65536, 'rust-std-clock-receipt-byte-limit')
    require({name: read_file(ROOT / name) for name in RECIPE} == inputs, 'rust-std-clock-recipe-mutated')
    require(originals(archive) == original, 'rust-std-clock-original-source-mutated')
    write_json(output / 'std-source-overlay.json', value)
    return value
