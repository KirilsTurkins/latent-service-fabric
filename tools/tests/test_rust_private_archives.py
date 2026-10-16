"""Actual offline Cargo metadata checks for published private archive semantics."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
import unittest

from tools import qualify_rust_private_dependencies as suite
from tools.application_dependency_store import archive_files
from tools.build_observation import build_environment
from tools.build_snapshot import digest


class RustPrivateArchives(unittest.TestCase):
    def test_private_manifest_records_transitive_registry_index(self):
        index = 'sparse+https://127.0.0.1:1/index/'
        payload = suite.archive(suite.MAIN, 'pub fn value()->u32 {42}\n', registry_index=index)
        files = archive_files(payload, 'tar')
        manifest = tomllib.loads(files[suite.MAIN + '-' + suite.VERSION + '/Cargo.toml'].decode())
        self.assertEqual(manifest['dependencies'][suite.CHILD], {'version': '=' + suite.VERSION, 'registry-index': index})

    def test_native_locked_offline_graph_retains_private_transitive_source(self):
        cargo = shutil.which('cargo')
        self.assertIsNotNone(cargo, 'Pinned Cargo is required for this native metadata control')
        with tempfile.TemporaryDirectory(prefix='private-Cargo-native-metadata-') as temporary:
            root = Path(temporary)
            if rustup := shutil.which('rustup'):
                selection_environment = build_environment(root)
                selection_environment['RUSTUP_AUTO_INSTALL'] = '0'
                located = subprocess.run([rustup, 'which', '--toolchain', '1.97.1', 'cargo'], cwd=root,
                    env=selection_environment, capture_output=True, timeout=10)
                self.assertEqual(located.returncode, 0, located.stderr.decode(errors='replace'))
                cargo = located.stdout.decode().strip()
            environment = build_environment(root)
            environment.update(CARGO_HOME=str(root / 'home'), HOME=str(root / 'home'), USERPROFILE=str(root / 'home'),
                RUSTUP_TOOLCHAIN='1.97.1', RUSTUP_AUTO_INSTALL='0', CARGO_NET_OFFLINE='true')
            version = subprocess.run([cargo, '--version'], cwd=root, env=environment, capture_output=True, timeout=10)
            self.assertEqual(version.returncode, 0, version.stderr.decode(errors='replace'))
            self.assertIn('1.97.1', version.stdout.decode().split())
            app = root / 'app'; (app / 'src').mkdir(parents=True)
            (app / 'src/lib.rs').write_bytes(b'pub fn value()->u32 {42}\n')
            (app / 'Cargo.toml').write_text('[package]\nname="private-lock-control"\nversion="0.1.0"\nedition="2021"\n'
                '[dependencies]\n' + suite.MAIN + '={version="=' + suite.VERSION + '",registry="team"}\n', encoding='utf-8')
            index = 'sparse+https://127.0.0.1:1/index/'
            vendor = root / 'vendor'; vendor.mkdir()
            home = root / 'home'; home.mkdir()
            (home / 'config.toml').write_text('[registries.team]\nindex=' + json.dumps(index) +
                '\n[source.crates-io]\nreplace-with="captured"\n[source.private]\nregistry=' + json.dumps(index) +
                '\nreplace-with="captured"\n[source.captured]\ndirectory=' + json.dumps(str(vendor)) + '\n[net]\noffline=true\n', encoding='utf-8')
            for normalized in (False, True):
                payloads = {suite.MAIN: suite.archive(suite.MAIN, 'pub fn value()->u32 {42}\n',
                    registry_index=index if normalized else None),
                    suite.CHILD: suite.archive(suite.CHILD, 'pub fn value()->u32 {42}\n')}
                for name, raw in payloads.items():
                    directory = vendor / name; directory.mkdir(exist_ok=True)
                    prefix = name + '-' + suite.VERSION + '/'
                    files = {name.removeprefix(prefix): data for name, data in archive_files(raw, 'tar').items()}
                    for name, data in files.items():
                        target = directory / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
                    (directory / '.cargo-checksum.json').write_text(json.dumps({'package': digest(raw)[7:],
                        'files': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}), encoding='utf-8')
                lock = 'version=4\n[[package]]\nname="private-lock-control"\nversion="0.1.0"\ndependencies=["' + suite.MAIN + '"]\n'
                for name, raw in payloads.items():
                    lock += '\n[[package]]\nname=' + json.dumps(name) + '\nversion=' + json.dumps(suite.VERSION) + '\nsource=' + json.dumps(index) + '\nchecksum=' + json.dumps(digest(raw)[7:]) + '\n'
                    if name == suite.MAIN:
                        lock += 'dependencies=[' + json.dumps(suite.CHILD) + ']\n'
                (app / 'Cargo.lock').write_text(lock, encoding='utf-8')
                before = (app / 'Cargo.lock').read_bytes()
                command = [cargo, 'metadata', '--manifest-path', str(app / 'Cargo.toml'), '--locked', '--offline', '--format-version', '1']
                result = subprocess.run(command, cwd=root, env=environment, capture_output=True, timeout=30)
                if normalized:
                    self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
                    graph = json.loads(result.stdout)
                    sources = {row['name']: row.get('source') for row in graph['packages']}
                    self.assertEqual(sources[suite.MAIN], index)
                    self.assertEqual(sources[suite.CHILD], index)
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('lock file', result.stderr.decode(errors='replace'))
                self.assertEqual((app / 'Cargo.lock').read_bytes(), before)
