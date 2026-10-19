"""Bind explicit standard logging to current, bounded owned std build inputs.

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
LOG = 'latent:log/log@0.1.0'
RECIPE = ('tools/rust_standard_logging_inputs.py', *source.RECIPE,
          'tools/rust_standard_sysroot_build.py', 'tools/rust_capsule_build.py',
          'tools/build_observation.py', 'tools/build_process.py', 'tools/build_process_linux.py',
          'tools/build_process_signals.py', 'tools/captured_compiler_isolation.py')


def selection(project: dict) -> str:
    value = project.get('runtimeProfile', DEFAULT)
    require(isinstance(value, str) and value in {DEFAULT, CLOSED, PROFILE}, 'rust-standard-runtime-profile')
    return value


class Prepared:
    def __init__(self, path: Path, rustc: Path, profile=PROFILE):
        # Late import avoids the existing Commands/build-source dependency cycle.
        from tools import rust_standard_sysroot_build as built
        self.path, self.rustc = checked_path(path), checked_path(rustc)
        require(profile in {CLOSED, PROFILE}, 'rust-standard-runtime-prepared-selection')
        self.profile = profile
        self.raw = read_file(self.path / 'std-sysroot-build.json', 1024 * 1024)
        value = read_json(self.path / 'std-sysroot-build.json', 1024 * 1024)
        require(isinstance(value, dict) and value.get('schemaVersion') == 'latent.rust.std-built-source.v1'
                and value.get('profile') == (built.LOGGING_PROFILE if profile == PROFILE else built.PROFILE)
                and value.get('standardStdio') == ('typed-log-v1' if profile == PROFILE else 'explicit-unsupported-v1')
                and value.get('target') == clock.TARGET and value.get('rust') == clock.RUST
                and value.get('rustCommit') == clock.RUST_COMMIT
                and value.get('archiveDigest') == 'sha256:' + clock.SOURCE_ARCHIVE_SHA256,
                'rust-standard-runtime-prepared-profile')
        unsigned = {key: item for key, item in value.items() if key != 'identity'}
        require(value.get('identity') == digest(encode(unsigned)), 'rust-standard-runtime-receipt-identity')
        require(value.get('recipeDigest') == digest(inventory({n: read_file(ROOT / n)
                for n in dict.fromkeys(built.RECIPE)})), 'rust-standard-runtime-recipe-drift')
        require(isinstance(value.get('tools'), dict)
                and value['tools'].get('rustc') == file_identity(self.rustc, 'rustc'),
                'rust-standard-runtime-compiler-drift')
        require(all(isinstance(value.get(name), str) and re.fullmatch(r'sha256:[0-9a-f]{64}', value[name])
                for name in ('originalInputsDigest', 'selectedInputsDigest')),
                'rust-standard-runtime-source-identity')
        require(value.get('rustFlags') == built.FLAGS and value.get('qualification') == 'built-source-only'
                and value.get('installedCompilerChanged') is False,
                'rust-standard-runtime-build-profile')
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

    def arguments(self):
        # Target-only Cargo config leaves host build scripts/macros on the
        # original compiler's host sysroot. It is not ambient RUSTFLAGS.
        return ['--config', 'target.' + clock.TARGET + '.rustflags=' +
                json.dumps(['--sysroot=' + str(self.root)], separators=(',', ':'))]

    def material(self):
        return encode({'schemaVersion': 'latent.rust.standard-stdio-input.v1', 'profile': self.profile,
            'preparedBuildIdentity': self.value['identity'], 'preparedReceiptDigest': digest(self.raw),
            'compiler': self.value['tools']['rustc'], 'recipeDigest': self.value['recipeDigest'],
            'originalInputsDigest': self.value['originalInputsDigest'],
            'selectedInputsDigest': self.value['selectedInputsDigest'], 'libraries': self.libraries,
            'authority': 'none', 'publisherAuthentication': False})
