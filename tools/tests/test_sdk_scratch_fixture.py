"""Preparation invariants; actual component error categories remain a separate gate."""
from pathlib import Path
import tempfile
import unittest
from tools import sdk_scratch_fixture as fixture
from tools.rust_capsule_project import read_file, snapshot


class ScratchFixture(unittest.TestCase):
    def test_five_standard_creators_preserve_sdk_profile_wit_limits_and_greeting_cases(self):
        with tempfile.TemporaryDirectory() as temporary:
            for language in fixture.LANGUAGES:
                with self.subTest(language=language):
                    app, receipt = fixture.project(language, Path(temporary)/language)
                    source = read_file(app/fixture.SOURCES[language])
                    self.assertIn(b'Please enter a name.', source)
                    self.assertIn(b'Use a name of at most 100 bytes.', source)
                    self.assertIn(b'Hello, ', source)
                    self.assertIn(b'scratch-state-reused' if language in ('go', 'java', 'dotnet')
                                  else b'SCRATCH_CALLS' if language == 'rust' else b'scratch_calls', source)
                    self.assertIn(b'unexpected-success', source)
                    self.assertIn(b'scratch-explicit-fixture-trap' if language != 'c' else b'__builtin_trap', source)
                    self.assertFalse(receipt['sdkProfileAndLimitsChanged'])
                    self.assertFalse(receipt['filesystemGrantsAdded'])
                    self.assertFalse(receipt['compilerExecuted'])
                    self.assertEqual(receipt['signedQualification'], 'pending')
                    # No raw exception messages are used as a diagnostic label.
                    self.assertNotIn(b'getMessage()', source)
                    self.assertNotIn(b'.Message', source)

    def test_operations_are_genuine_standard_APIs_and_never_provider_or_application_filesystem_shims(self):
        for source, operations in ((fixture.RUST, ('std::fs::File::open', 'std::fs::OpenOptions', 'std::fs::create_dir')),
                (fixture.C, ('fopen(', 'tmpfile(')), (fixture.GO, ('os.Open(', 'os.OpenFile(', 'os.CreateTemp(')),
                (fixture.JAVA, ('java.io.FileInputStream(', 'java.io.FileOutputStream(', 'java.io.File.createTempFile(')),
                (fixture.DOTNET, ('System.IO.File.OpenRead(', 'System.IO.File.Open(', 'System.IO.Path.GetTempFileName('))):
            with self.subTest(operations=operations):
                self.assertTrue(all(value in source for value in operations))
                self.assertNotIn('latent:', source)
                self.assertNotIn('scratchStorage', source)
                self.assertNotIn('blob', source)

    def test_invalid_language_and_typescript_case_refuse_before_any_project_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(RuntimeError, 'scratch-language'):
                fixture.project('unknown', root/'project')
            with self.assertRaisesRegex(RuntimeError, 'scratch-typescript-case'):
                fixture.typescript_project(root/'project', root/'outside', 'unknown')
            self.assertEqual(snapshot(root), {})


if __name__ == '__main__': unittest.main()
