"""Owned original Go module fixtures retain exact source/resource/version scope."""
from pathlib import Path
import tempfile
import unittest

from tools import go_dependency_watch_fixture as fixture


class GoDependencyWatchFixture(unittest.TestCase):
    def test_two_real_modules_preserve_primary_api_and_resource_across_update(self):
        with tempfile.TemporaryDirectory() as temporary:
            application = Path(temporary) / 'application'; application.mkdir()
            observed = fixture.create(application)
            primary, child = Path(observed['primary']), Path(observed['child'])
            v1 = (primary / 'go.mod').read_text()
            self.assertIn('module ' + fixture.PRIMARY, v1)
            self.assertIn('require ' + fixture.CHILD + ' v0.1.0', v1)
            self.assertIn('replace ' + fixture.CHILD + ' => ../child', v1)
            self.assertEqual((primary / 'badge.txt').read_bytes(), fixture.RESOURCE)
            original_api = (primary / 'primary.go').read_bytes()
            self.assertIn(b'value+39', (child / 'child.go').read_bytes())
            fixture.remove_original(observed, 'primary'); fixture.remove_original(observed, 'child')
            self.assertFalse(primary.exists() or child.exists())
            fixture.restore_revision(observed, 2)
            self.assertIn('require ' + fixture.CHILD + ' v0.1.1', (primary / 'go.mod').read_text())
            self.assertEqual((primary / 'primary.go').read_bytes(), original_api)
            self.assertIn(b'value+40', (child / 'child.go').read_bytes())
            self.assertNotEqual(observed['inputDigests']['child-v1'], observed['inputDigests']['child-v2'])
            self.assertFalse((application / 'app').exists())

    def test_cleanup_and_restore_refuse_unknown_roots_without_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            application = Path(temporary) / 'application'; application.mkdir()
            observed = fixture.create(application)
            primary = Path(observed['primary'])
            before = (primary / 'go.mod').read_bytes()
            with self.assertRaisesRegex(ValueError, 'fresh'):
                fixture.restore_revision(observed, 2)
            with self.assertRaisesRegex(ValueError, 'unknown'):
                fixture.remove_original(observed, '../application')
            changed = {**observed, 'ownedRoot': str(application.resolve())}
            with self.assertRaisesRegex(ValueError, 'escaped'):
                fixture.remove_original(changed, 'primary')
            self.assertEqual((primary / 'go.mod').read_bytes(), before)
            self.assertTrue(application.is_dir())

    def test_removal_entry_has_no_library_reference_and_keeps_generated_export_api(self):
        selected = fixture.application_source()
        removed = fixture.application_source(removed=True)
        self.assertIn('primary.Answer()', selected)
        self.assertIn('primary.Resource()', selected)
        self.assertNotIn(fixture.PRIMARY, removed)
        self.assertNotIn('strconv', removed)
        self.assertIn('"removed/"+name', removed)
        for source in (selected, removed):
            self.assertIn('package export_examples_greeting_api', source)
            self.assertIn('go.bytecodealliance.org/pkg/wit/types', source)
            self.assertIn('calls != 0', source)
            self.assertNotIn('unsafe', source)
