"""Reproduce a selected executor port from original authenticated Cargo CAS.

The normal generic dependency transformation remains replacement-only. Selected
modules are inserted into the existing upstream lib.rs, so no file-creation
waiver or new dependency transformation format is required.
"""
from __future__ import annotations

import hashlib
import json

from tools import rust_standard_thread_profile as profile
from tools.build_snapshot import canonical, digest
from tools.dev_workflow.common import require
from tools.rust_capsule_project import ROOT, inventory, read_file

RECIPE = ('tools/rust_standard_thread_capture.py', *profile.RECIPE)
APPLICATION_PROFILE = 'rust-standard-owned-thread-v1'


def runtime_package(row):
    metadata = row.get('metadata', {})
    return (row.get('format') == 'directory' and metadata.get('ecosystem') == 'cargo'
            and metadata.get('package') == profile.EXECUTOR
            and metadata.get('vendorChecksum', {}).get('package') is not None)


def recipe():
    return {name: read_file(ROOT / name) for name in RECIPE}


def module_replacement(original, inputs):
    """Keep original host/features source and insert only the selected modules."""
    runtime = {name: inputs[name] for name in profile.EXECUTOR_SOURCES.values()}
    # Reuse all exact package/source/target/compiler checks before embedding.
    selected = profile.executor_overlay(original, runtime, package=profile.EXECUTOR,
        version=profile.EXECUTOR_VERSION, archive_sha256=profile.EXECUTOR_ARCHIVE_SHA256)
    needle = (b'#[cfg(feature = "thread-pool")]\n'
              b'#[cfg_attr(docsrs, doc(cfg(feature = "thread-pool")))]\n'
              b'#[cfg(feature = "std")]\nmod thread_pool;')
    condition = ('all(feature = "thread-pool", feature = "std", '
                 + profile.SELECTOR + ')').encode()
    bridge = (b'#[cfg(' + condition + b')]\nmod lsf_thread_pool {\n'
              + selected['src/lsf_thread_pool.rs'] + b'\n}\n')
    pool = (b'#[cfg(' + condition + b')]\nmod thread_pool {\n'
            + selected['src/lsf_thread_pool_impl.rs'] + b'\n}\n')
    original_branch = needle.replace(b'mod thread_pool;',
        b'#[cfg(not(' + profile.SELECTOR.encode() + b'))]\nmod thread_pool;')
    replacement = bridge + pool + original_branch
    lib = original['src/lib.rs']
    require(lib.count(needle) == 1, 'rust-thread-captured-executor-selector-preimage')
    derived = lib.replace(needle, replacement, 1)
    require(derived.replace(replacement, needle, 1) == lib,
            'rust-thread-captured-executor-selector-only')
    return derived


def captured_changes(row, files, selected_profile):
    if selected_profile != APPLICATION_PROFILE or not runtime_package(row):
        return {}, None
    metadata = row['metadata']
    require(metadata.get('version') == profile.EXECUTOR_VERSION
            and metadata['vendorChecksum']['package'] == profile.EXECUTOR_ARCHIVE_SHA256,
            'rust-thread-unreviewed-runtime-package')
    checksum = json.loads(files['.cargo-checksum.json'])
    require(checksum.get('package') == profile.EXECUTOR_ARCHIVE_SHA256
            and checksum.get('files') == {name: hashlib.sha256(raw).hexdigest()
                for name, raw in files.items() if name != '.cargo-checksum.json'},
            'rust-thread-captured-vendor-checksum')
    inputs = recipe()
    original = {name: files[name] for name in profile.EXECUTOR_ORIGINALS}
    changes = {'src/lib.rs': module_replacement(original, inputs)}
    checksum['files']['src/lib.rs'] = hashlib.sha256(changes['src/lib.rs']).hexdigest()
    changes['.cargo-checksum.json'] = canonical(checksum) + b'\n'
    require(set(changes) <= set(files), 'rust-thread-capture-replacement-only')
    material = {'profile': profile.PROFILE, 'recipeDigest': digest(inventory(inputs)),
        'package': profile.EXECUTOR, 'version': profile.EXECUTOR_VERSION,
        'archiveSha256': profile.EXECUTOR_ARCHIVE_SHA256,
        'originals': profile.EXECUTOR_ORIGINALS,
        'target': profile.TARGET, 'rust': profile.RUST,
        'canonicalThreadRuntimeQualified': False,
        'privateExecutorGraphAuthenticated': False}
    return changes, material


def verify_capture(verified, selected_profile):
    selected = selected_profile == APPLICATION_PROFILE
    transforms = verified.lock['transformations']
    for transform in transforms:
        if 'runtimeThreadPort' in transform['selection']:
            require(selected, 'rust-thread-port-without-selected-profile')
    for row in verified.lock['artifacts']:
        if not selected or not runtime_package(row):
            continue
        original_rows = json.loads(verified.store.get(**row['original']))
        files = {item['path']: verified.store.get(item['digest'], item['size'])
                 for item in original_rows}
        changes, expected = captured_changes(row, files, selected_profile)
        actual = {item['path']: item for item in row['files']}
        if actual['Cargo.toml']['digest'] != digest(files['Cargo.toml']):
            checksum = json.loads(changes['.cargo-checksum.json'])
            checksum['files']['Cargo.toml'] = actual['Cargo.toml']['digest'][7:]
            changes['.cargo-checksum.json'] = canonical(checksum) + b'\n'
        ports = [transform for transform in transforms if transform['artifact'] == row['id']
                 and 'runtimeThreadPort' in transform['selection']]
        require(len(ports) == 1 and ports[0]['selection']['runtimeThreadPort'] == expected,
                'rust-thread-captured-runtime-recipe-drift')
        require(all(name in actual and actual[name]['digest'] == digest(raw)
                    and actual[name]['size'] == len(raw) for name, raw in changes.items()),
                'rust-thread-captured-runtime-output-drift')
        require(set(changes) <= {item['path'] for item in ports[0]['changes']}
                <= {*changes, 'Cargo.toml'}, 'rust-thread-captured-runtime-change-set')
