"""Pin the existing guest export exception without opening other unsafe code."""
from pathlib import Path
import tempfile
import tomllib
import unittest

from tools import native_loader_boundary as boundary

ROOT = Path(__file__).resolve().parents[2]
CLIPPY = tomllib.loads((ROOT / 'Cargo.toml').read_text(encoding='utf-8'))['workspace']['lints']['clippy']


class StandardStdioBoundary(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.crate = self.root / boundary.STANDARD_STDIO
        (self.crate / 'src').mkdir(parents=True)
        for name in ('Cargo.toml', 'src/lib.rs'):
            (self.crate / name).write_bytes((ROOT / boundary.STANDARD_STDIO / name).read_bytes())

    def test_actual_reviewed_guest_and_whole_workspace_pass(self):
        self.assertEqual(boundary.validate_standard_stdio(ROOT, CLIPPY), [])
        self.assertEqual(boundary.validate(ROOT), [])

    def test_lint_allowance_cannot_expand_or_drop_workspace_clippy(self):
        path = self.crate / 'Cargo.toml'
        original = path.read_text(encoding='utf-8')
        for changed in (original.replace('unsafe_code = "deny"', 'unsafe_code = "allow"'),
                        original.replace('pedantic = { level = "warn", priority = -1 }', ''),
                        original.replace('priority = -1', 'priority = 1')):
            with self.subTest(manifest=changed):
                path.write_bytes(changed.encode())
                self.assertTrue(boundary.validate_standard_stdio(self.root, CLIPPY))

    def test_bridge_identity_export_or_additional_unsafe_body_requires_review(self):
        path = self.crate / 'src/lib.rs'
        original = path.read_text(encoding='utf-8')
        for before, after in (('#![cfg(target_arch = "wasm32")]', ''),
                              ('__lsf_std_log_write_v1', '__lsf_unreviewed_export'),
                              ('log::write', 'unreviewed::write'),
                              ('#[allow(unsafe_code)]', '#![allow(unsafe_code)]')):
            self.assertIn(before, original)
            with self.subTest(change=before):
                path.write_bytes(original.replace(before, after).encode())
                self.assertTrue(boundary.validate_standard_stdio(self.root, CLIPPY))
        path.write_bytes((original + '\nunsafe fn extra() {}\n').encode())
        self.assertTrue(boundary.validate_standard_stdio(self.root, CLIPPY))

    def test_another_source_file_cannot_join_the_reviewed_bridge(self):
        self.assertEqual(boundary.validate_standard_stdio(self.root, CLIPPY), [])
        (self.crate / 'src/extra.rs').write_bytes(b'unsafe fn extra() {}\n')
        self.assertTrue(boundary.validate_standard_stdio(self.root, CLIPPY))
