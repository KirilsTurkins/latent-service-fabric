"""Host-only graph/lock guards; no Rust or C++ build."""
from pathlib import Path
import tempfile
import unittest
from tools.typescript_guest import borrow_support as support


class BorrowSupportTests(unittest.TestCase):
    def fixture(self, root):
        (root / 'cmake').mkdir()
        (root / 'cmake/build-crates.cmake').write_text(
            'add_rust_lib(rust-encoding "${CMAKE_CURRENT_SOURCE_DIR}/crates/rust-encoding")\n'
            'add_rust_lib(rust-hooks "${CMAKE_CURRENT_SOURCE_DIR}/crates/rust-hooks")\n'
            'add_rust_lib(rust-url "${CMAKE_CURRENT_SOURCE_DIR}/crates/rust-url")\n'
            'add_rust_lib(multipart "${CMAKE_CURRENT_SOURCE_DIR}/crates/rust-multipart" "\\"capi\\", \\"simd\\"\")\n')
        cmake = root / 'cmake/build-crates.cmake'
        cmake.write_bytes(cmake.read_bytes().replace(b'\r\n', b'\n'))
        template = root / 'runtime/crates/staticlib-template'; template.mkdir(parents=True)
        (template / 'Cargo.toml.in').write_bytes(b'[lib]\ncrate-type = ["staticlib"]\n[dependencies]\n')
        (template / 'rust-staticlib.rs.in').write_bytes(b'// maintained template\n')
        (template / 'Cargo.lock').write_bytes(b'# exact original lock bytes\nversion = 3\n')
        for _name, directory, _features in support.CRATES:
            (root / 'crates' / directory).mkdir(parents=True)
        return template

    def test_exact_four_crates_preserve_original_lock_and_features(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root / 'source'; source.mkdir()
            template = self.fixture(source); output = root / 'generated'
            original = (template / 'Cargo.lock').read_bytes()
            identity = support.manifest(source, output)
            self.assertEqual((output / 'Cargo.lock').read_bytes(), original)
            self.assertEqual((template / 'Cargo.lock').read_bytes(), original)
            self.assertIn('features = ["capi", "simd"]', (output / 'Cargo.toml').read_text())
            self.assertEqual(set(identity), {'Cargo.toml', 'rust-staticlib.rs', 'Cargo.lock'})
            with self.assertRaisesRegex(ValueError, 'fresh-manifest'):
                support.manifest(source, output)

    def test_missing_changed_or_extra_crate_refuses_before_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root / 'source'; source.mkdir()
            self.fixture(source); cmake = source / 'cmake/build-crates.cmake'; original = cmake.read_text()
            for changed in [original.replace('rust-encoding', 'other-encoding'),
                            original.splitlines()[0] + '\n',
                            original + 'add_rust_lib(other "${CMAKE_CURRENT_SOURCE_DIR}/crates/other")\n']:
                cmake.write_text(changed); output = root / 'not-created'
                with self.assertRaisesRegex(ValueError, 'crate-graph-changed'):
                    support.manifest(source, output)
                self.assertFalse(output.exists())
