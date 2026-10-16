"""Owned original Rust crate fixtures retain exact source/resource/version scope."""
from pathlib import Path
import tempfile
import tomllib
import unittest

from tools import rust_dependency_watch_fixture as fixture


class RustDependencyWatchFixture(unittest.TestCase):
    def test_two_real_crates_preserve_primary_api_and_resource_across_update(self):
        with tempfile.TemporaryDirectory() as temporary:
            application = Path(temporary) / 'application'; application.mkdir()
            observed = fixture.create(application)
            primary, child = Path(observed['primary']), Path(observed['child'])
            v1 = tomllib.loads((primary / 'Cargo.toml').read_text())
            self.assertEqual(v1['package']['name'], fixture.PRIMARY)
            self.assertEqual(v1['dependencies'][fixture.CHILD], {'path': '../child', 'version': '=0.1.0'})
            self.assertEqual((primary / 'src/badge.txt').read_bytes(), fixture.RESOURCE)
            original_api = (primary / 'src/lib.rs').read_bytes()
            self.assertIn(b'value+39', (child / 'src/lib.rs').read_bytes())
            fixture.remove_original(observed, 'primary'); fixture.remove_original(observed, 'child')
            self.assertFalse(primary.exists() or child.exists())
            fixture.restore_revision(observed, 2)
            self.assertEqual(tomllib.loads((primary / 'Cargo.toml').read_text())['package']['version'], '0.1.1')
            self.assertEqual((primary / 'src/lib.rs').read_bytes(), original_api)
            self.assertIn(b'value+40', (child / 'src/lib.rs').read_bytes())
            self.assertNotEqual(observed['inputDigests']['child-v1'], observed['inputDigests']['child-v2'])
            self.assertFalse((application / 'app').exists())

    def test_cleanup_and_restore_refuse_unknown_roots_without_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            application = Path(temporary) / 'application'; application.mkdir()
            observed = fixture.create(application)
            primary = Path(observed['primary'])
            before = (primary / 'Cargo.toml').read_bytes()
            with self.assertRaisesRegex(ValueError, 'fresh'):
                fixture.restore_revision(observed, 2)
            with self.assertRaisesRegex(ValueError, 'unknown'):
                fixture.remove_original(observed, '../application')
            changed = {**observed, 'ownedRoot': str(application.resolve())}
            with self.assertRaisesRegex(ValueError, 'escaped'):
                fixture.remove_original(changed, 'primary')
            self.assertEqual((primary / 'Cargo.toml').read_bytes(), before)
            self.assertTrue(application.is_dir())

    def test_removal_entry_has_no_library_reference_and_keeps_normal_wit(self):
        selected = fixture.application_source()
        removed = fixture.application_source(removed=True)
        self.assertIn('outside_watch_primary::answer()', selected)
        self.assertNotIn('outside_watch_primary', removed)
        self.assertIn('removed/{name}', removed)
        for source in (selected, removed):
            self.assertIn('path:"wit",world:"service"', source)
            self.assertIn('CALLS.fetch_add', source)
            self.assertNotIn('unsafe', source)
