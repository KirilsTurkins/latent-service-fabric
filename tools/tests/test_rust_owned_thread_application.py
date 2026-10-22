import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from tools.compile_rust_owned_thread_application import emitted_core, source_archive


class OwnedThreadApplication(unittest.TestCase):
    def test_executor_object_requires_the_actual_captured_package_manifest_and_target_emission(self):
        from tools.compile_rust_owned_thread_application import emitted_executor
        from tools.rust_capsule_project import digest
        from tools import rust_standard_thread_profile as profile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); work = root / 'work'; target = root / 'target'
            mount = 'dependencies/cargo-vendor/futures-executor-0.3.31'
            manifest = work / mount / 'Cargo.toml'; manifest.parent.mkdir(parents=True)
            manifest.write_bytes(b'captured source manifest')
            source = manifest.parent / 'src/lib.rs'; source.parent.mkdir(); source.write_bytes(b'original capture')
            native = 'registry+https://github.com/rust-lang/crates.io-index#futures-executor@0.3.31'
            features = ['default', 'num_cpus', 'std', 'thread-pool']
            package = {'format': 'directory', 'mount': mount, 'metadata': {
                'package': profile.EXECUTOR, 'version': profile.EXECUTOR_VERSION,
                'vendorChecksum': {'package': profile.EXECUTOR_ARCHIVE_SHA256},
                'nativeIdDigest': digest(native.encode()), 'features': features}}
            output = target / 'wasm32-unknown-unknown/release/deps'; output.mkdir(parents=True)
            library = output / 'libfutures_executor-current.rlib'; library.write_bytes(b'!<arch>\n')
            metadata = output / 'libfutures_executor-current.rmeta'; metadata.write_bytes(b'compiler metadata')
            artifact = {'reason': 'compiler-artifact', 'package_id': native,
                'manifest_path': str(manifest), 'target': {'kind': ['lib'], 'crate_types': ['lib'],
                    'name': 'futures_executor', 'src_path': str(source), 'edition': '2018'},
                'features': features, 'profile': {'test': False}, 'fresh': False, 'executable': None,
                'filenames': [str(library), str(metadata)]}
            finished = {'reason': 'build-finished', 'success': True}
            def raw(*items):
                return b'\n'.join(json.dumps(row).encode() for row in items) + b'\n'
            self.assertEqual(emitted_executor(raw(artifact, finished), work, target, package),
                             (library, artifact))
            foreign = root / 'foreign.rlib'; foreign.write_bytes(b'filename alone is not attribution')
            variants = [
                {**artifact, 'package_id': native.replace('0.3.31', '0.3.34')},
                {**artifact, 'manifest_path': str(root / 'foreign/Cargo.toml')},
                {**artifact, 'target': {**artifact['target'], 'src_path': str(root / 'foreign/lib.rs')}},
                {**artifact, 'target': {**artifact['target'], 'edition': '2024'}},
                {**artifact, 'target': {**artifact['target'], 'kind': ['proc-macro']}},
                {**artifact, 'features': ['std']},
                {**artifact, 'profile': {'test': True}},
                {**artifact, 'fresh': True},
                {**artifact, 'filenames': [str(foreign)]},
                {**artifact, 'filenames': [str(metadata)]},
            ]
            for selected in variants:
                with self.subTest(selected=selected), self.assertRaises(ValueError):
                    emitted_executor(raw(selected, finished), work, target, package)
            for items in ((artifact,), (artifact, artifact, finished),
                          (artifact, {**finished, 'success': False}), (artifact, finished, artifact)):
                with self.assertRaises(ValueError):
                    emitted_executor(raw(*items), work, target, package)

    def test_actual_emission_selection_refuses_replay_and_foreign_or_failed_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            work, target = root / 'work', root / 'target'
            work.mkdir(); target.mkdir()
            module = target / 'original.wasm'
            module.write_bytes(b'original compiler output selected by Cargo')
            artifact = {'reason': 'compiler-artifact', 'manifest_path': str(work / 'Cargo.toml'),
                'target': {'name': 'ordinary', 'crate_types': ['cdylib']},
                'profile': {'test': False}, 'filenames': [str(module)]}
            finished = {'reason': 'build-finished', 'success': True}
            def raw(*items):
                return b'\n'.join(json.dumps(row).encode() for row in items) + b'\n'
            self.assertEqual(emitted_core(raw(artifact, finished), work, target, 'ordinary'), module)
            for rows in ((artifact,), (artifact, {**finished, 'success': False}),
                         (artifact, artifact, finished), (artifact, finished, artifact),
                         ({**artifact, 'manifest_path': str(root / 'foreign/Cargo.toml')}, finished),
                         ({**artifact, 'profile': {'test': True}}, finished),
                         ({**artifact, 'filenames': [str(root / 'foreign.wasm')]}, finished),
                         ({**artifact, 'target': {'name': 'ordinary', 'crate_types': ['bin']}}, finished)):
                with self.assertRaises(ValueError):
                    emitted_core(raw(*rows), work, target, 'ordinary')

    def test_source_archive_retains_hidden_cargo_and_cas_bytes_without_compiler_outputs(self):
        from tools.rust_capsule_project import digest
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); app = root / 'app'; app.mkdir()
            contents = {'Cargo.toml': b'[package]\nname="ordinary"\n',
                '.cargo/config.toml': b'[net]\noffline=true\n',
                'dependency-inputs/objects/00/original': b'authenticated original bytes',
                'src/lib.rs': b'pub fn value() -> u32 { 42 }\n'}
            for name, raw in {**contents, 'target/ignored.exe': b'compiled output'}.items():
                path = app / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
            output = root / 'source.tar.gz'; identity = source_archive(app, output)
            self.assertEqual(identity['size'], output.stat().st_size)
            with tarfile.open(output, 'r:gz') as archive:
                actual = {member.name: archive.extractfile(member).read() for member in archive}
            self.assertEqual(actual, contents)
            retained = json.loads((root / 'source.tar.gz.files.json').read_text())
            self.assertTrue(retained['digestsComplete'])
            self.assertEqual(retained['expandedBytes'], sum(map(len, contents.values())))
            self.assertEqual(retained['files'], [
                {'path': name, 'size': len(raw), 'digest': digest(raw)}
                for name, raw in sorted(contents.items())])
            (app / 'too-large').write_bytes(b'x' * (4 * 1024 * 1024 + 1))
            with self.assertRaises(ValueError):
                source_archive(app, root / 'refused.tar.gz')
            refused = json.loads((root / 'refused.tar.gz.sizes.json').read_text())
            self.assertFalse(refused['digestsComplete'])
            self.assertEqual(refused['expandedBytes'], sum(map(len, contents.values())) + 4 * 1024 * 1024 + 1)
            self.assertEqual(next(row['size'] for row in refused['files'] if row['path'] == 'too-large'),
                             4 * 1024 * 1024 + 1)


if __name__ == '__main__':
    unittest.main()
