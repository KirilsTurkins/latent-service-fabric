"""Bind explicit standard facility profiles to bounded owned std build inputs.

The retained build receipt is a builder assertion, not a publisher signature.
Normal tool/executable approval and final signed component admission still apply.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

from tools import rust_standard_clock_profile as clock
from tools import rust_standard_logging_profile as stdio
from tools import rust_standard_sysroot_source as source
from tools.build_observation import file_identity
from tools.dev_workflow.common import encode, require
from tools.rust_capsule_project import ROOT, checked_path, digest, inventory, read_file, read_json

DEFAULT = 'wasm32-unknown-unknown-panic-abort-v1'
CLOSED = 'rust-standard-closed-v1'
PROFILE = 'rust-standard-logging-v1'
ENTROPY = 'rust-standard-entropy-v1'
LOGGING_ENTROPY = 'rust-standard-logging-entropy-v1'
THREAD = 'rust-standard-owned-thread-v1'
PREPARED = frozenset({CLOSED, PROFILE, ENTROPY, LOGGING_ENTROPY, THREAD})
LOG = 'latent:log/log@0.1.0'
# Workspace metadata authenticates the explicit std source build. It is not
# a required input to the normal compiler recipe or its minimal offline CLI.
SOURCE_BUILD_METADATA = ('Cargo.toml', 'Cargo.lock')
RECIPE = ('tools/rust_standard_logging_inputs.py',
          *(name for name in source.RECIPE if name not in SOURCE_BUILD_METADATA),
          'tools/rust_standard_sysroot_build.py', 'tools/rust_capsule_build.py',
          'tools/build_observation.py', 'tools/build_process.py', 'tools/build_process_linux.py',
          'tools/build_process_signals.py', 'tools/captured_compiler_isolation.py')


def selection(project: dict) -> str:
    value = project.get('runtimeProfile', DEFAULT)
    require(isinstance(value, str) and value in {DEFAULT, *PREPARED}, 'rust-standard-runtime-profile')
    return value


def has_logging(profile):
    return profile in {PROFILE, LOGGING_ENTROPY}


def has_entropy(profile):
    return profile in {ENTROPY, LOGGING_ENTROPY}


def has_threads(profile):
    return profile == THREAD


def source_build_inputs(profile):
    selection({'runtimeProfile': profile})
    if has_threads(profile):
        from tools import rust_standard_thread_capture as capture, rust_owned_thread_component as component
        return (*SOURCE_BUILD_METADATA, *capture.RECIPE, *component.RECIPE)
    return SOURCE_BUILD_METADATA if profile in PREPARED else ()


class Prepared:
    def __init__(self, path: Path, rustc: Path, profile=PROFILE):
        # Late import avoids the existing Commands/build-source dependency cycle.
        from tools import rust_standard_sysroot_build as built
        self.path, self.rustc = checked_path(path), checked_path(rustc)
        require(profile in PREPARED, 'rust-standard-runtime-prepared-selection')
        self.profile = profile
        self.raw = read_file(self.path / 'std-sysroot-build.json', 1024 * 1024)
        value = read_json(self.path / 'std-sysroot-build.json', 1024 * 1024)
        require(isinstance(value, dict) and value.get('schemaVersion') == 'latent.rust.std-built-source.v1'
                and value.get('profile') == (built.THREAD_PROFILE if has_threads(profile) else
                    ((built.LOGGING_ENTROPY_PROFILE if has_logging(profile) else built.ENTROPY_PROFILE)
                    if has_entropy(profile) else (built.LOGGING_PROFILE if has_logging(profile) else built.PROFILE)))
                and value.get('standardStdio') == ('typed-log-v1' if has_logging(profile) else 'explicit-unsupported-v1')
                and value.get('standardEntropy', 'original-unsupported-v1') ==
                    ('typed-random-u64-v1' if has_entropy(profile) else 'original-unsupported-v1')
                and value.get('target') == clock.TARGET and value.get('rust') == clock.RUST
                and value.get('rustCommit') == clock.RUST_COMMIT
                and value.get('archiveDigest') == 'sha256:' + clock.SOURCE_ARCHIVE_SHA256,
                'rust-standard-runtime-prepared-profile')
        unsigned = {key: item for key, item in value.items() if key != 'identity'}
        require(value.get('identity') == digest(encode(unsigned)), 'rust-standard-runtime-receipt-identity')
        if has_threads(profile):
            from tools.rust_standard_thread_profile import PROFILE as THREAD_SOURCE
            require(value.get('standardThreads') == THREAD_SOURCE
                    and value.get('standardThreadSourceSelected') is True
                    and value.get('standardThreadRuntimeQualified') is False,
                    'rust-standard-thread-source-profile')
        require(value.get('recipeDigest') == digest(inventory({n: read_file(ROOT / n)
                for n in dict.fromkeys(built.recipe(threads=has_threads(profile)))})),
                'rust-standard-runtime-recipe-drift')
        require(isinstance(value.get('tools'), dict)
                and value['tools'].get('rustc') == file_identity(self.rustc, 'rustc'),
                'rust-standard-runtime-compiler-drift')
        require(all(isinstance(value.get(name), str) and re.fullmatch(r'sha256:[0-9a-f]{64}', value[name])
                for name in ('originalInputsDigest', 'selectedInputsDigest')),
                'rust-standard-runtime-source-identity')
        require(value.get('rustFlags') == built.FLAGS and value.get('qualification') == 'built-source-only'
                and value.get('installedCompilerChanged') is False,
                'rust-standard-runtime-build-profile')
        if has_threads(profile):
            from tools.rust_thread_path_remap import verify_standard_receipt
            verify_standard_receipt(value.get('threadSourcePathRemap'),
                                    value.get('rustEncodedFlags'), built.FLAGS)
        self.libraries = value.get('libraries')
        require(isinstance(self.libraries, dict) and 5 <= len(self.libraries) <= 64,
                'rust-standard-runtime-library-count')
        self.root = checked_path(self.path / 'sysroot')
        self.directory = checked_path(self.root / 'lib/rustlib' / clock.TARGET / 'lib')
        for parent, child in ((self.root, 'lib'), (self.root / 'lib', 'rustlib'),
                              (self.root / 'lib/rustlib', clock.TARGET),
                              (self.root / 'lib/rustlib' / clock.TARGET, 'lib')):
            require({p.name for p in parent.iterdir()} == {child}, 'rust-standard-runtime-extra-sysroot-input')
        total, crates = 0, set()
        for name, row in self.libraries.items():
            require(isinstance(name, str) and re.fullmatch(r'lib[A-Za-z0-9_-]{1,200}\.rlib', name)
                    and isinstance(row, dict) and set(row) == {'digest', 'size', 'crate', 'package'}
                    and isinstance(row['crate'], str) and len(row['crate']) <= 256
                    and isinstance(row['package'], str) and len(row['package']) <= 4096
                    and type(row['size']) is int and 0 < row['size'] <= built.MAX_ARTIFACT_BYTES,
                    'rust-standard-runtime-library-record')
            raw = read_file(checked_path(self.directory / name), built.MAX_ARTIFACT_BYTES)
            require(digest(raw) == row['digest'] and len(raw) == row['size'],
                    'rust-standard-runtime-library-mutated')
            require(row['crate'] not in crates, 'rust-standard-runtime-ambiguous-crate')
            total += len(raw); crates.add(row['crate'])
        require(total <= 128 * 1024 * 1024
                and {'std', 'core', 'alloc', 'panic_abort', 'compiler_builtins'} <= crates,
                'rust-standard-runtime-incomplete-graph')
        require({p.name for p in self.directory.iterdir()} == set(self.libraries),
                'rust-standard-runtime-extra-library')
        self.value = value

    def check(self):
        current = Prepared(self.path, self.rustc, self.profile)
        require(current.raw == self.raw, 'rust-standard-runtime-receipt-mutated')

    def arguments(self, *, source_root=None):
        # Target-only Cargo config leaves host build scripts/macros on the
        # original compiler's host sysroot. It is not ambient RUSTFLAGS.
        flags = ['--sysroot=' + str(self.root)]
        if has_threads(self.profile):
            from tools.rust_thread_path_remap import source_mapping, APPLICATION
            require(isinstance(source_root, Path), 'rust-thread-actual-application-source-required')
            flags.append(source_mapping(source_root, APPLICATION)['argument'])
            # The selected bootstrap requires a non-null linker-owned low
            # bound. Keep the real stack after static data; do not invent or
            # relax a zero-address stack/context sentinel after linking.
            flags.append('-Clink-arg=--no-stack-first')
            # Preserve one MiB for Root and reserve a disjoint 64KiB System
            # stack inside the original linker-owned memory geometry.
            flags.extend(['-Clink-arg=-z', '-Clink-arg=stack-size=1114112'])
            # These are implementation support exports, not new public WIT.
            # The finite component route must authenticate all actual uses.
            for name in ('__stack_pointer', '__stack_low', '__indirect_function_table',
                         '__lsf_rust_owned_thread_entry', '__lsf_rust_root_bootstrap',
                         '__lsf_rust_root_finish', '__lsf_rust_root_reap'):
                flags.append('-Clink-arg=--export=' + name)
        arguments = ['--config', 'target.' + clock.TARGET + '.rustflags=' +
                     json.dumps(flags, separators=(',', ':'))]
        if has_threads(self.profile):
            # Preserve compiler-object boundaries for the selected profile's
            # complete private graph. Application Cargo source stays original.
            arguments.extend(['--config', 'profile.release.lto=false'])
        return arguments

    def material(self):
        return encode({'schemaVersion': 'latent.rust.standard-stdio-input.v1', 'profile': self.profile,
            'preparedBuildIdentity': self.value['identity'], 'preparedReceiptDigest': digest(self.raw),
            'compiler': self.value['tools']['rustc'], 'recipeDigest': self.value['recipeDigest'],
            'originalInputsDigest': self.value['originalInputsDigest'],
            'selectedInputsDigest': self.value['selectedInputsDigest'], 'libraries': self.libraries,
            'authority': 'none', 'publisherAuthentication': False})
