"""Stage authenticated full std sources; never execute/install a sysroot."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import tarfile

from tools import rust_standard_clock_profile as clock, rust_standard_tls_profile as tls
from tools.dev_workflow.common import digest, encode, require
from tools.rust_capsule_project import checked_path, inventory, read_file, write_json

ROOT = Path(__file__).resolve().parents[1]
MAX_FILES = 8192
MAX_BYTES = 128 * 1024 * 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
PREFIX = 'rust-src-1.97.1/rust-src/lib/rustlib/src/rust/library/'
PROFILE = 'lsf-rust-std-source-staging-v1'
RECIPE = ('tools/rust_standard_sysroot_source.py', *clock.RECIPE, *tls.RECIPE)


def selected_library_entries(source, *, modes=None):
    """Bound the compiler-source domain before writing any selected member."""
    result = {}; folded = set(); total = 0
    for entry in source:
        if not entry.name.startswith(PREFIX): continue
        name = entry.name[len(PREFIX):]
        if entry.isdir(): continue
        require(entry.isfile() and not entry.issym() and not entry.islnk(), 'rust-sysroot-source-regular-only')
        parts = PurePosixPath(name).parts
        require(parts and not name.startswith('/') and '\\' not in name and ':' not in name
                and all(p not in {'', '.', '..'} for p in parts) and '/'.join(parts) == name,
                'rust-sysroot-source-path')
        require(name not in result and name.casefold() not in folded, 'rust-sysroot-source-path-collision')
        require(0 <= entry.size <= MAX_FILE_BYTES and len(result) < MAX_FILES, 'rust-sysroot-source-entry-bound')
        total += entry.size; require(total <= MAX_BYTES, 'rust-sysroot-source-total-bound')
        value = source.extractfile(entry).read(); require(len(value) == entry.size, 'rust-sysroot-source-entry-size')
        result[name] = value; folded.add(name.casefold())
        if modes is not None: modes[name] = 0o755 if entry.mode & 0o111 else 0o644
    require({'Cargo.toml', 'Cargo.lock', '.cargo/config.toml', 'std/Cargo.toml', 'core/Cargo.toml',
             'alloc/Cargo.toml', 'sysroot/Cargo.toml'} <= set(result), 'rust-sysroot-source-closure-missing')
    return result


def library(archive: Path):
    raw = read_file(archive, 32 * 1024 * 1024)
    require(hashlib.sha256(raw).hexdigest() == clock.SOURCE_ARCHIVE_SHA256, 'rust-sysroot-source-archive-pin')
    modes = {}
    with tarfile.open(archive, 'r:xz') as source:
        result = selected_library_entries(source, modes=modes)
    require(read_file(archive, 32 * 1024 * 1024) == raw, 'rust-sysroot-source-archive-mutated')
    return result, modes


def prepare(archive: Path, output: Path, *, target=clock.TARGET, rust=clock.RUST):
    require(target == clock.TARGET and rust == clock.RUST, 'rust-sysroot-profile-not-maintained')
    archive, output = checked_path(archive), checked_path(output)
    require(not output.exists() and not output.is_symlink(), 'rust-sysroot-output-must-be-fresh')
    original, modes = library(archive)
    inputs = {name: read_file(ROOT / name) for name in dict.fromkeys(RECIPE)}
    tls.tool_pins(inputs)
    selected = dict(original)
    # Both helpers check their exact upstream preimages before changing a file.
    changes = clock.overlay({n: original[n] for n in clock.ORIGINALS}, inputs['sdk/rust-standard-runtime/clock.rs'])
    changes.update(tls.overlay({n: original[n] for n in tls.ORIGINALS}, inputs['sdk/rust-standard-runtime/tls.rs']))
    selected.update(changes)
    selected_modes = {**modes, **{name: 0o644 for name in changes if name not in modes}}
    output.mkdir(mode=0o700, parents=True)
    for name, raw in selected.items():
        path = output / 'library' / name; path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream: stream.write(raw)
        if os.name == 'posix': path.chmod(selected_modes[name])
    # The official archive remains the full original source carrier. Its exact
    # ordered inventory is a separately bounded compiler-source document, not
    # an application/controller snapshot and not a widened generic decoder.
    inventories = {}
    for name, files in (('original', original), ('selected', selected)):
        inventory_raw = inventory(files)
        require(len(inventory_raw) <= 1024 * 1024, 'rust-sysroot-inventory-byte-bound')
        with (output / (name + '-compiler-source-inventory.json')).open('xb') as stream: stream.write(inventory_raw)
        inventories[name] = {'digest': digest(inventory_raw), 'bytes': len(inventory_raw)}
    executable_modes = {'defaultRegularFileMode': 0o644,
        'executableMembers': sorted(name for name, mode in selected_modes.items() if mode == 0o755)}
    modes_raw = encode(executable_modes)
    with (output / 'compiler-source-executable-modes.json').open('xb') as stream: stream.write(modes_raw)
    value = {'schemaVersion': 'latent.rust.sysroot-source-stage.v1', 'profile': PROFILE,
        'target': target, 'rust': rust, 'rustCommit': clock.RUST_COMMIT,
        'originalArchiveDigest': 'sha256:' + clock.SOURCE_ARCHIVE_SHA256,
        'originalInputsDigest': digest(inventory(original)), 'selectedInputsDigest': digest(inventory(selected)),
        'recipeDigest': digest(inventory(inputs)), 'inventories': inventories,
        'executableModesDigest': digest(modes_raw), 'executableFiles': len(executable_modes['executableMembers']),
        'posixSourceModesPhysicallyApplied': os.name == 'posix',
        'originalFiles': len(original), 'selectedFiles': len(selected),
        'originalBytes': sum(map(len, original.values())), 'selectedBytes': sum(map(len, selected.values())),
        'changedPaths': sorted(changes), 'compilerSourceBounds': {'files': MAX_FILES, 'bytes': MAX_BYTES, 'fileBytes': MAX_FILE_BYTES},
        'applicationControllerBoundsChanged': False, 'qualification': 'unqualified-source',
        'installedSysroot': False, 'compilerInvoked': False, 'supportedRuntimeProfile': False,
        'automaticBuilderSelection': False, 'noStdAndAllocSourceBytesPreserved': True,
        'proposedOwnedBuild': {'command': ['cargo', 'build', '--locked', '--offline', '--manifest-path',
            '<owned-library>/Cargo.toml', '--package', 'std', '--target', target, '--release',
            '--features', 'compiler-builtins-mem'],
            'environment': {'RUSTC_BOOTSTRAP': '1', 'CARGO_HOME': '<owned-offline-cargo-home>',
                'CARGO_TARGET_DIR': '<owned-sysroot-target>', 'RUSTFLAGS': '-Cpanic=abort -Cembed-bitcode=yes'},
            'execution': 'not-run; validate with pinned compiler before accepting this recipe'},
        'remainingGates': ['actual owned locked offline sysroot build and exact emitted rlib graph',
            'owned clock/runtime world metadata and full linked-core stack context bootstrap',
            'logical thread/sync/timer/default-reactor/checkpoint implementation',
            'engine admission/physical accounting and real signed standard API qualification']}
    value['identity'] = digest(encode(value))
    require(len(encode(value)) <= 65536, 'rust-sysroot-stage-receipt-bound')
    require({name: read_file(ROOT / name) for name in inputs} == inputs, 'rust-sysroot-recipe-mutated')
    require(library(archive) == (original, modes), 'rust-sysroot-original-source-mutated')
    write_json(output / 'sysroot-source-stage.json', value)
    return value
