"""Exact tool/material observation and one owned, bounded build process at a time."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import time
import tomllib

from tools.build_observation import build_environment, file_identity, resolve_tools
from tools.build_process import run_bounded
from tools.build_snapshot import SnapshotError, canonical, digest, is_reparse
from tools.angular_build.inputs import decode, read

ROOT = Path(__file__).resolve().parents[2]
NODE_VERSION = '24.19.0'
ADAPTER_FILES = ('Cargo.toml', 'src/abi.rs', 'src/lib.rs', 'src/wire.rs', 'wit/adapter.wit',
                 'runtime/bridge.js', 'runtime/timers.js')


def table(files: list[tuple[str, Path]], name: str) -> tuple[dict, bytes]:
    if len(files) > 64 or len({label for label, _ in files}) != len(files):
        raise SnapshotError('Angular material file count exceeded')
    rows = [file_identity(path, label, 4 * 1024 * 1024) for label, path in sorted(files)]
    data = canonical(rows)
    return {'name': name, 'digest': digest(data), 'size': len(data)}, data


def fixed_materials() -> list[dict]:
    adapter = ROOT / 'tools/angular-renderer-adapter'
    files = [('tools/angular-renderer-adapter/' + name, adapter / name) for name in ADAPTER_FILES]
    recipe = [
        ('tools/' + name, ROOT / 'tools' / name)
        for name in ('build_angular_package.py', 'build_observation.py', 'build_snapshot.py',
                     'build_inventory_units.py', 'build_inventory_manifests.py', 'build_sbom_inputs.py',
                     'build_process.py', 'build_process_linux.py', 'build_process_windows.py', 'build_process_signals.py')
    ]
    recipe += [('tools/angular_build/' + path.name, path) for path in (ROOT / 'tools/angular_build').iterdir()
               if path.suffix in ('.py', '.mjs', '.js')]
    recipe += [(name, ROOT / name) for name in ('Cargo.toml', '.cargo/config.toml', 'rust-toolchain.toml')]
    return [table(files, 'adapter-source')[0], table(recipe, 'build-recipe')[0],
            table([(name, ROOT / name) for name in ('wit/platform/web/package.wit', 'wit/platform/context/package.wit')], 'public-wit')[0],
            file_identity(adapter / 'wit/adapter.wit', 'private-wit', 65536),
            file_identity(ROOT / 'Cargo.lock', 'dependency-lock', 4 * 1024 * 1024),
            table([(name, ROOT / name) for name in ('tools/toolchain.toml', 'examples/renderer-profile/profile.json')], 'toolchain-config')[0]]


def npm_tree(root: Path, cancellation) -> dict:
    """Hash actual installed regular files, without claiming lockfile closure.

    npm's .bin links are excluded: commands use their observed module paths.
    Other links and special files are rejected. Source/registry trust is separate.
    """
    root = root.resolve(strict=True)
    rows, pending, entries, total = [], [root], 0, 0
    while pending:
        cancellation.check()
        parent = pending.pop()
        with os.scandir(parent) as iterator:
            for entry in iterator:
                entries += 1
                if entries > 40000:
                    raise SnapshotError('Angular tool tree entry limit exceeded')
                if entry.name == '.bin' and entry.is_dir(follow_symlinks=False):
                    continue
                path = Path(entry.path)
                if is_reparse(path):
                    raise SnapshotError('Angular tool tree contains a link')
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                elif entry.is_file(follow_symlinks=False):
                    name = path.relative_to(root).as_posix()
                    before = path.stat()
                    if before.st_size == 0:
                        with path.open('rb') as source:
                            empty = source.read(1)
                        after = path.stat()
                        if empty or after.st_size or before.st_ino != after.st_ino or is_reparse(path):
                            raise SnapshotError('Angular empty tool file changed during observation')
                        row = {'name': name, 'digest': digest(b''), 'size': 0}
                    else:
                        row = file_identity(path, name)
                    total += row['size']
                    if total > 1024 * 1024 * 1024:
                        raise SnapshotError('Angular tool tree byte limit exceeded')
                    rows.append(row)
                else:
                    raise SnapshotError('Angular tool tree contains a special file')
    encoded = canonical(sorted(rows, key=lambda row: row['name']))
    if len(encoded) > 8 * 1024 * 1024 or not rows:
        raise SnapshotError('Angular tool inventory byte limit exceeded')
    return {'name': 'npm-tree', 'digest': digest(encoded), 'size': len(encoded)}


class BuildTools:
    def __init__(self, toolchain: Path, cli: Path, temporary: Path, cargo_target: Path, cancellation):
        self.deadline = time.monotonic() + 1800
        self.cancellation = cancellation
        self.toolchain = toolchain.resolve(strict=True)
        self.fixed = fixed_materials()
        expected = ROOT / 'examples/renderer-profile'
        for name in ('package.json', 'package-lock.json'):
            if read(self.toolchain, name, 4 * 1024 * 1024) != read(expected, name, 4 * 1024 * 1024):
                raise SnapshotError('Angular tooling differs from its exact locked profile')
        self.npm_lock = file_identity(self.toolchain / 'package-lock.json', 'npm-lock', 4 * 1024 * 1024)
        self.tree = npm_tree(self.toolchain / 'node_modules', cancellation)
        config = tomllib.loads((ROOT / 'tools/toolchain.toml').read_text())
        self.environment = build_environment(temporary)
        self.paths, self.executables = resolve_tools(config, ROOT, self.environment)
        located = shutil.which('node', path=self.environment.get('PATH'))
        if not located:
            raise SnapshotError('Angular Node build tool is unavailable')
        self.paths['node'] = Path(located).resolve(strict=True)
        self.paths['package-assembler'] = cli.resolve(strict=True)
        for name in ('node', 'package-assembler'):
            self.executables.append(file_identity(self.paths[name], name))
        self.environment.update({'RUSTC': str(self.paths['rustc']), 'CARGO_TARGET_DIR': str(cargo_target),
                                 'CARGO_INCREMENTAL': '0'})
        # Node/Wizer children do not inherit Cargo locations, user config, keys,
        # auth tokens, npm settings, arbitrary Node options or application env.
        private_home = temporary / 'home'
        private_home.mkdir()
        self.node_environment = {key: value for key, value in self.environment.items()
                                 if key in ('PATH', 'SystemRoot', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'ComSpec',
                                            'PATHEXT', 'TEMP', 'TMP', 'TMPDIR', 'LC_ALL', 'TZ')}
        self.node_environment.update({'HOME': str(private_home), 'USERPROFILE': str(private_home)})
        version = self.call([str(self.paths['node']), '--version'], ROOT, node=True, seconds=30).strip()
        if version != ('v' + NODE_VERSION).encode():
            raise SnapshotError('Angular Node version differs from its pin')
        self.profile = self.cli('package', 'renderer-profile')
        if self.profile.get('profile') != 'angular-ssr-component-v1':
            raise SnapshotError('package assembler lacks the approved renderer profile')

    def call(self, command: list[str], cwd: Path, *, node=False, seconds=300, maximum=4 * 1024 * 1024) -> bytes:
        self.cancellation.check()
        remaining = min(seconds, self.deadline - time.monotonic())
        if remaining <= 0:
            raise SnapshotError('Angular build deadline exceeded')
        return run_bounded(command, cwd=cwd, env=self.node_environment if node else self.environment,
                           timeout_seconds=remaining, max_output_bytes=maximum).stdout

    def cli(self, *arguments: str) -> dict:
        result = decode(self.call([str(self.paths['package-assembler']), '--output', 'json', *arguments], ROOT))
        if result.get('category') != 'success' or not isinstance(result.get('data'), dict):
            raise SnapshotError('Angular package assembler failed')
        return result['data']

    def verify(self) -> None:
        self.cancellation.check()
        if self.fixed != fixed_materials() or self.tree != npm_tree(self.toolchain / 'node_modules', self.cancellation):
            raise SnapshotError('Angular recipe or installed tools changed during build')
        if self.npm_lock != file_identity(self.toolchain / 'package-lock.json', 'npm-lock', 4 * 1024 * 1024):
            raise SnapshotError('Angular npm lock changed during build')
        for material in self.executables:
            if material != file_identity(self.paths[material['name']], material['name']):
                raise SnapshotError('Angular executable changed during build')

    def materials(self):
        return [*self.fixed, self.npm_lock, self.tree, *self.executables]
