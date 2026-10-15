"""Actual capture/review operations for the finite installed C watch inputs."""
import json
from pathlib import Path
import tempfile
import unittest

from tools import c_capsule_project, c_dependency_authoring as author
from tools import c_dependency_watch_fixture as fixture
from tools import application_dependencies as dependencies
from tools.application_dependency_store import DependencyError
from tools.build_snapshot import digest
from tools.c_application_dependencies import selected


class WatchInputs(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = c_capsule_project.create(self.root / 'application', 'greeting')
        self.inputs = fixture.create(self.project)
        self.sdk = (self.project / 'sdk-lock.json').read_bytes()

    def add(self):
        declarations = self.inputs['declarations']
        author.edit(self.project, 'add', [json.loads(declarations[name].read_bytes())
                                        for name in ('child-v1', 'primary')], [])

    def review(self, label):
        candidate = self.root / (label + '.json')
        author.resolve(self.project, candidate)
        author.review(self.project, candidate, digest(candidate.read_bytes()))
        self.assertEqual((self.project / 'sdk-lock.json').read_bytes(), self.sdk)
        return candidate.read_bytes()

    def test_both_revisions_capture_offline_without_changing_sdk_or_adding_catalogue_entries(self):
        self.add(); initial = self.review('initial')
        fixture.remove_original(self.inputs, 'primary'); fixture.remove_original(self.inputs, 'child-v1')
        self.assertEqual(author.status(self.project)['status'], 'verified')
        changed = json.loads(self.inputs['declarations']['child-v2'].read_bytes())
        author.edit(self.project, 'update', [changed], [fixture.CHILD])
        with self.assertRaisesRegex(DependencyError, 'lock-drift'):
            author.status(self.project)
        self.assertEqual((self.project / dependencies.LOCK).read_bytes(), initial)
        fixture.restore_primary(self.inputs)
        updated = self.review('updated')
        self.assertNotEqual(updated, initial)
        fixture.remove_original(self.inputs, 'primary'); fixture.remove_original(self.inputs, 'child-v2')
        work, output = self.root / 'work', self.root / 'output'
        work.mkdir(); output.mkdir()
        closure = dependencies.prepare(self.project, work, output, 'c')
        choice = selected(closure, compiler_digest=digest(b'compiler'), runtime_digest=digest(b'runtime'))
        self.assertEqual(len(choice.sources), 1)
        headers = [path / 'child.h' for path in choice.includes if (path / 'child.h').exists()]
        self.assertEqual(len(headers), 1)
        self.assertIn(b'value + 40', headers[0].read_bytes())
        self.assertNotIn(b'latent_', choice.sources[0].read_bytes())
        closure.check_unchanged()

    def test_closed_remove_requires_new_review_and_retains_sdk_bytes(self):
        self.add(); initial = self.review('initial')
        author.edit(self.project, 'remove', [], [fixture.PRIMARY, fixture.CHILD])
        with self.assertRaisesRegex(DependencyError, 'lock-drift'):
            author.status(self.project)
        self.assertEqual((self.project / dependencies.LOCK).read_bytes(), initial)
        removed = self.review('removed')
        self.assertEqual(json.loads(removed)['artifacts'], [])
        self.assertEqual(author.status(self.project)['status'], 'verified')
        source = fixture.application_source(removed=True)
        self.assertNotIn('owned_api.h', source)
        self.assertIn('removed/%.*s', source)

    def test_unexpected_original_input_is_preserved_instead_of_removed(self):
        path = self.inputs['root'] / 'primary/owned.c'
        path.write_bytes(b'changed outside library')
        with self.assertRaisesRegex(ValueError, 'input-bytes-changed'):
            fixture.remove_original(self.inputs, 'primary')
        self.assertEqual(path.read_bytes(), b'changed outside library')
        self.assertTrue((path.parent / 'owned_api.h').exists())


if __name__ == '__main__':
    unittest.main()
