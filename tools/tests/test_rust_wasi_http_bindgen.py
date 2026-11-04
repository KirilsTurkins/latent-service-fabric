"""Select only the captured direct HTTP compiler-root bindgen dependency."""
import tempfile
from pathlib import Path
import tomllib
import unittest

from tools import rust_wasi_http_root as root
from tools import rust_wasi_http_compose as compose
from tools.rust_capsule_project import digest
from tools.tests.test_rust_wasi_http_profile import value_graph


MANIFEST = b'''[package]
name = "outside-app"
version = "1.0.0"
[target.'cfg(target_arch = "wasm32")'.dependencies]
wit-bindgen = "=0.63.0"
'''
SDK = b'''{"toolchain":{"rust":{"dependencies":{"wit-bindgen":"0.63.0"}}}}'''
LOCK = b'''version = 4
[[package]]
name = "outside-app"
version = "1.0.0"
dependencies = ["wit-bindgen 0.63.0"]
[[package]]
name = "wit-bindgen"
version = "0.34.0"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
dependencies = ["old-macro"]
[[package]]
name = "old-macro"
version = "1.0.0"
[[package]]
name = "wit-bindgen"
version = "0.57.1"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
[[package]]
name = "wit-bindgen"
version = "0.63.0"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
dependencies = ["new-macro"]
[[package]]
name = "new-macro"
version = "2.0.0"
'''
NAME = 'lsf-owned-http-root-' + 'a' * 16


class CapturedBindgenSelection(unittest.TestCase):
    def test_root_edge_selects_exact_pin_and_only_its_unchanged_closure(self):
        self.assertEqual(root.selected_bindgen(LOCK, manifest=MANIFEST, sdk_lock=SDK), '0.63.0')
        projection = root.compiler_lock(LOCK, NAME, manifest=MANIFEST, sdk_lock=SDK)
        source = tomllib.loads(LOCK.decode())['package']
        projected = tomllib.loads(projection.decode())['package']
        originals = {(row['name'], row['version']): row for row in source}
        retained = {(row['name'], row['version']): row for row in projected}
        self.assertEqual(set(retained), {('wit-bindgen', '0.63.0'), ('new-macro', '2.0.0'), (NAME, '0.0.0')})
        for identity in set(retained) - {(NAME, '0.0.0')}:
            self.assertEqual(retained[identity], originals[identity])
        self.assertEqual(root.normalized_lock(projection, projection, NAME)['newPackageIdentities'], 0)
        self.assertNotIn(b'old-macro', projection)
        self.assertNotIn(b'outside-app', projection)

    def test_forwarding_root_preserves_proof_schema_and_uses_selected_generator(self):
        graph = value_graph()
        canonical = 'package root:component;\nworld root {\n  export outside:varied-client/api@1.2.3;\n}\n'
        with tempfile.TemporaryDirectory() as temp:
            _, record, files = root.prepare_project(Path(temp) / 'source', canonical, graph, LOCK,
                                                     manifest=MANIFEST, sdk_lock=SDK)
        self.assertEqual(record['originalCapturedCargoLock'], digest(LOCK))
        self.assertEqual(set(record), {'schemaVersion', 'name', 'files', 'originalCapturedCargoLock', 'calls',
            'publicResultPreserved', 'applicationSourceRewritten', 'rustBindingsAsync',
            'publicContractKindsPreserved', 'privateCallingConvention', 'executionQualification'})
        self.assertIn(b'wit-bindgen="=0.63.0"', files['Cargo.toml'])
        self.assertIn(b'sync: true', files['src/lib.rs'])
        self.assertFalse(record['executionQualification'])

    def test_composer_preserves_the_old_single_version_route_without_extra_files(self):
        historical = b'''version=4
[[package]]
name="wit-bindgen"
version="0.62.0"
'''
        graph = value_graph()
        canonical = 'package root:component;\nworld root {\n  export outside:varied-client/api@1.2.3;\n}\n'
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            work = directory / 'work'
            work.mkdir()
            (work / 'Cargo.lock').write_bytes(historical)
            _, actual, actual_files = compose.prepare_root_project(directory / 'via-composer', canonical, graph, work)
            _, expected, expected_files = root.prepare_project(directory / 'historical', canonical, graph, historical)
            self.assertEqual(actual, expected)
            self.assertEqual(actual_files, expected_files)
            self.assertEqual((directory / 'via-composer' / 'source-proof.json').read_bytes(),
                             (directory / 'historical' / 'source-proof.json').read_bytes())
            self.assertEqual({p.name for p in work.iterdir()}, {'Cargo.lock'})

    def test_composer_reads_the_extra_proof_only_for_multiple_versions(self):
        graph = value_graph()
        canonical = 'package root:component;\nworld root {\n  export outside:varied-client/api@1.2.3;\n}\n'
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            work = directory / 'work'
            work.mkdir()
            (work / 'Cargo.lock').write_bytes(LOCK)
            (work / 'Cargo.toml').write_bytes(MANIFEST)
            with self.assertRaises(FileNotFoundError):
                compose.prepare_root_project(directory / 'without-sdk', canonical, graph, work)
            (work / 'sdk-lock.json').write_bytes(SDK)
            _, record, files = compose.prepare_root_project(directory / 'captured-root', canonical, graph, work)
            self.assertEqual(record['originalCapturedCargoLock'], digest(LOCK))
            self.assertIn(b'wit-bindgen="=0.63.0"', files['Cargo.toml'])
            self.assertNotIn(b'old-macro', files['Cargo.lock'])

    def test_wrong_missing_aliased_or_ambiguous_identity_refuses(self):
        controls = (
            (LOCK, MANIFEST.replace(b'=0.63.0', b'=0.62.0'), SDK),
            (LOCK, MANIFEST, SDK.replace(b'0.63.0', b'0.62.0')),
            (LOCK, MANIFEST, SDK.replace(b'0.63.0', b'0.64.0')),
            (LOCK, MANIFEST + b'\n[dependencies]\nalias={package="wit-bindgen",version="=0.63.0"}\n', SDK),
            (LOCK, MANIFEST + b'\n[dependencies]\nwit-bindgen="=0.63.0"\n', SDK),
            (LOCK.replace(b'name = "outside-app"', b'name = "other-app"', 1), MANIFEST, SDK),
            (LOCK.replace(b'version = "1.0.0"\ndependencies', b'version = "2.0.0"\ndependencies', 1), MANIFEST, SDK),
            (LOCK.replace(b'version = "1.0.0"\ndependencies', b'version = "1.0.0"\nsource = "registry+x"\ndependencies', 1), MANIFEST, SDK),
            (LOCK + b'\n[[package]]\nname="outside-app"\nversion="1.0.0"\n', MANIFEST, SDK),
            (LOCK + b'\n[[package]]\nname="wit-bindgen"\nversion="0.63.0"\n', MANIFEST, SDK),
            (LOCK.replace(b'"wit-bindgen 0.63.0"', b'"wit-bindgen 0.34.0"', 1), MANIFEST, SDK),
            (LOCK.replace(b'"wit-bindgen 0.63.0"', b'"wit-bindgen"', 1), MANIFEST, SDK),
            (LOCK.replace(b'"wit-bindgen 0.63.0"', b'"wit-bindgen 0.63.0", "wit-bindgen 0.34.0"', 1), MANIFEST, SDK),
            (LOCK.replace(b'"wit-bindgen 0.63.0"', b'"new-macro"', 1), MANIFEST, SDK),
            (LOCK.replace(b'"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"', b'"changed"'), MANIFEST, SDK),
            (LOCK.replace(b'version = "0.63.0"\nsource = "registry+https://github.com/rust-lang/crates.io-index"',
                          b'version = "0.63.0"\nsource = "registry+https://other.invalid/index"'), MANIFEST, SDK),
        )
        for lock, manifest, sdk in controls:
            with self.subTest(lock=lock, manifest=manifest, sdk=sdk), self.assertRaises(ValueError):
                root.selected_bindgen(lock, manifest=manifest, sdk_lock=sdk)

    def test_historical_single_version_path_is_preserved_and_multi_version_refuses(self):
        historical = b'''version=4
[[package]]
name="wit-bindgen"
version="0.62.0"
'''
        self.assertEqual(root.selected_bindgen(historical), '0.62.0')
        self.assertEqual(root.selected_bindgen(root.compiler_lock(historical, NAME)), '0.62.0')
        with self.assertRaisesRegex(ValueError, 'captured-bindgen'):
            root.selected_bindgen(LOCK)
        for manifest, sdk in ((MANIFEST, None), (None, SDK)):
            with self.subTest(manifest=manifest, sdk=sdk), self.assertRaises(ValueError):
                root.selected_bindgen(LOCK, manifest=manifest, sdk_lock=sdk)

    def test_malformed_bounded_and_unclosed_inputs_refuse(self):
        for lock, manifest, sdk in (
            (LOCK, MANIFEST, b'{"toolchain":{},"toolchain":{}}'),
            (LOCK, MANIFEST[:-5], SDK),
            (LOCK, MANIFEST, SDK[:-1]),
            (LOCK, b'x' * (4 * 1024 * 1024 + 1), SDK),
            (LOCK, MANIFEST, b'x' * (4 * 1024 * 1024 + 1)),
            (b'x' * (8 * 1024 * 1024 + 1), MANIFEST, SDK),
        ):
            with self.subTest(lock_len=len(lock), manifest_len=len(manifest), sdk_len=len(sdk)), self.assertRaises(ValueError):
                root.selected_bindgen(lock, manifest=manifest, sdk_lock=sdk)
        changed = LOCK.replace(b'dependencies = ["new-macro"]', b'dependencies = ["missing-macro"]')
        with self.assertRaisesRegex(ValueError, 'missing-or-ambiguous'):
            root.compiler_lock(changed, NAME, manifest=MANIFEST, sdk_lock=SDK)


if __name__ == '__main__':
    unittest.main()
