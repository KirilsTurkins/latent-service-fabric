"""Tamper controls for the explicit worker-library qualifier; no guest claims."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from tools import java_fiber_library_inputs as libraries
from tools.build_snapshot import digest
from tools.rust_capsule_project import inventory, snapshot


class WorkerLibraries(unittest.TestCase):
    def test_missing_extra_or_changed_original_cannot_reach_review_or_host_execution(self):
        rows = [{'id': name, 'role': 'application', 'metadata': {}, 'original': {'digest': value}}
                for name, value in libraries.LIBRARIES.items()]
        changed = deepcopy(rows)
        changed[0]['original']['digest'] = 'sha256:' + '0' * 64
        for artifacts in (rows[:1], changed, rows + [{**rows[0], 'id': 'unreviewed:extra:1.0'}]):
            with self.subTest(artifacts=artifacts), tempfile.TemporaryDirectory() as temporary:
                def create(path, _template):
                    path.mkdir()
                    (path / 'sdk-lock.json').write_bytes(b'captured sdk')
                    return path
                with patch.object(libraries, 'create', side_effect=create), patch.object(libraries, 'edit'), \
                        patch.object(libraries, 'resolve', return_value={'artifacts': artifacts}), \
                        patch.object(libraries, 'review') as review:
                    with self.assertRaisesRegex(ValueError, 'exact reviewed original Maven'):
                        libraries.capture(Path(temporary) / 'capture', gradle='gradle')
                    review.assert_not_called()

    def fixture(self, root):
        app = root / 'application'
        app.mkdir()
        (app / 'source').write_bytes(b'captured application')
        receipts = root / 'receipts'
        receipts.mkdir()
        receipt = receipts / 'java-classpath.json'
        receipt.write_bytes(b'captured selected archive receipt')
        selected = root / 'selected-application-jars'
        selected.mkdir()
        jar = selected / '0000.jar'
        jar.write_bytes(b'normalized selected archive')
        report = {'applicationIdentity': digest(inventory(snapshot(app))),
                  'classpathDigest': digest(receipt.read_bytes()),
                  'selectedJars': [{'selectedDigest': digest(jar.read_bytes())}]}
        return app, receipt, jar, report

    def test_source_receipt_and_selected_bytes_are_independent_post_execution_fences(self):
        for changed in ('source', 'receipt', 'jar'):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                app, receipt, jar, report = self.fixture(root)
                with patch.object(libraries, 'verify_inputs', return_value=SimpleNamespace(lock={'artifacts': []})):
                    libraries.check(root, report)
                    target = {'source': app / 'source', 'receipt': receipt, 'jar': jar}[changed]
                    target.write_bytes(target.read_bytes() + b' changed after execution')
                    with self.assertRaisesRegex(ValueError, 'changed'):
                        libraries.check(root, report)

    def test_original_reference_archive_cannot_change_after_native_materialization(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _app, _receipt, _jar, report = self.fixture(root)
            original = root / 'offline-inputs/selected/original.jar'
            original.parent.mkdir(parents=True)
            original.write_bytes(b'forged original')
            artifact = {'id': next(iter(libraries.LIBRARIES)), 'mount': 'selected/original.jar'}
            with patch.object(libraries, 'verify_inputs', return_value=SimpleNamespace(lock={'artifacts': [artifact]})):
                with self.assertRaisesRegex(ValueError, 'original archive changed'):
                    libraries.check(root, report)

    def test_removed_reviewed_closure_cannot_be_replaced_by_a_classpath_receipt(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(libraries, 'verify_inputs', return_value=None):
            with self.assertRaisesRegex(ValueError, 'closure disappeared'):
                libraries.check(Path(temporary), {})


if __name__ == '__main__': unittest.main()
