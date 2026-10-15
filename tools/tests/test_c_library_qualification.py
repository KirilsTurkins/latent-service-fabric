"""Retained input drift cannot reach compilation, signing or a real node."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import qualify_c_library_ingestion as qualification
from tools.c_capsule_project import create
from tools.dev_workflow.common import DevError
from tools.rust_capsule_project import TEMPLATES, write_json


class CapturedCLibraryInputs(unittest.TestCase):
    def setUp(self):
        owned = tempfile.TemporaryDirectory()
        self.addCleanup(owned.cleanup)
        self.root = Path(owned.name)
        self.inputs = self.root / 'captured'
        (self.inputs / 'projects').mkdir(parents=True)
        for name in TEMPLATES:
            create(self.inputs / 'projects' / name, name)
        self.record = {'schemaVersion': 'latent.c-library-capture.v1', 'status': 'passed',
                       'projects': qualification.project_identities(self.inputs),
                       'library': {'scope': 'source-control-only'}}
        write_json(self.inputs / 'capture.json', self.record)

    def test_changed_application_or_sdk_is_rejected_before_native_selection_or_dispatch(self):
        self.assertEqual(qualification.captured(self.inputs), self.record)
        for path in (self.inputs / 'projects/greeting/src/main.c',
                     self.inputs / 'projects/greeting/vendor/lsf/tools/toolchain.toml'):
            with self.subTest(path=path.relative_to(self.inputs).as_posix()):
                original = path.read_bytes()
                path.write_bytes(original + b'\n')
                output = self.root / 'uncreated-output'
                with patch.object(qualification, 'ordinary_tuple') as native, \
                        patch.object(qualification.c_capsule_build, 'build') as compiler:
                    with self.assertRaisesRegex(DevError, 'c-library-captured-project-changed'):
                        qualification.execute(self.inputs, output, self.root / 'native', self.root / 'tuple.json', {})
                    native.assert_not_called()
                    compiler.assert_not_called()
                self.assertFalse(output.exists())
                path.write_bytes(original)

    def test_incomplete_capture_is_rejected_before_reading_or_creating_execution_inputs(self):
        for change in ({'status': 'failed'}, {'projects': {}}, {'schemaVersion': 'unrecognized'}):
            with self.subTest(change=change):
                current = {**copy.deepcopy(self.record), **change}
                (self.inputs / 'capture.json').unlink()
                write_json(self.inputs / 'capture.json', current)
                with patch.object(qualification, 'project_identities') as read:
                    with self.assertRaisesRegex(DevError, 'c-library-complete-capture-required'):
                        qualification.captured(self.inputs)
                    read.assert_not_called()


if __name__ == '__main__': unittest.main()
