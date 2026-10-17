"""Captured logging profile authority and ordinary outside-library ownership."""
import json
from pathlib import Path
import tempfile
import unittest

from tools import application_dependencies as dependencies, c_capsule_project as project
from tools.build_snapshot import digest
from tools.c_application_dependencies import selected
from tools.c_guest import standard_facilities as facilities
from tools.c_standard_logging_probe import prepare


class StandardLogging(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_profile_derives_only_logging_without_granting_clock_entropy_or_files(self):
        root = project.create(self.root / 'project', 'greeting')
        original = project.snapshot(root / 'wit')
        destination = self.root / 'derived'
        facilities.stage(root / 'wit', 'examples:greeting/service@1.0.0', destination,
                         project.ROOT / 'wit/platform', profile=facilities.LOGGING_PROFILE)
        text = (destination / 'world.wit').read_text()
        self.assertEqual(text.count('import latent:log/log@0.1.0;'), 1)
        self.assertNotIn('latent:clock', text)
        self.assertNotIn('latent:random', text)
        self.assertNotIn('wasi:filesystem', text)
        self.assertEqual({path.name for path in (destination / 'deps').iterdir()}, {'log'})
        self.assertEqual(project.snapshot(root / 'wit'), original)

    def test_outside_ordinary_stdio_is_captured_offline_with_sdk_and_other_limits_unchanged(self):
        root = project.create(self.root / 'project', 'greeting')
        sdk = (root / 'sdk-lock.json').read_bytes()
        before = json.loads((root / 'capsule-project.json').read_bytes())
        proof = prepare(root)
        self.assertTrue(proof['originalLibraryRemoved'])
        self.assertEqual((root / 'sdk-lock.json').read_bytes(), sdk)
        files = project.snapshot(root)
        value, _, _ = project.validate(files)
        self.assertEqual(value['runtimeProfile'], facilities.LOGGING_PROFILE)
        self.assertEqual(value['limits'], {**before['limits'], 'logBytes': 16384})
        output, work = self.root / 'output', self.root / 'work'
        output.mkdir(); work.mkdir()
        closure = dependencies.prepare(root, work, output, 'c')
        inputs = selected(closure, compiler_digest=digest(b'compiler'), runtime_digest=digest(b'runtime'),
                          runtime_profile=facilities.LOGGING_PROFILE)
        self.assertEqual(len(inputs.sources), 1)
        actual = inputs.sources[0].read_bytes()
        self.assertIn(b'printf("ordinary dependency:', actual)
        self.assertIn(b'fprintf(stderr,', actual)
        self.assertNotIn(b'latent_', actual)
        self.assertEqual(inputs.receipt['runtimeProfile'], facilities.LOGGING_PROFILE)
        closure.check_unchanged()

    def test_logging_dependency_cannot_borrow_clock_profile_or_ignore_adapter_tamper(self):
        root = project.create(self.root / 'project', 'greeting')
        prepare(root)
        graph = dependencies.verify_inputs(root, 'c').lock
        self.assertEqual(facilities.selected_profile({'runtimeProfile': facilities.LOGGING_PROFILE}, graph),
                         facilities.LOGGING_PROFILE)
        with self.assertRaisesRegex(ValueError, 'selection-mismatch'):
            facilities.selected_profile({'runtimeProfile': facilities.PROFILE}, graph)
        for name in ('standard-stdio.c', 'standard-stdio.wat'):
            path = root / 'vendor/lsf/sdk/c-guest/src' / name
            original = path.read_bytes()
            path.write_bytes(original + b'\n')
            with self.subTest(adapter=name), self.assertRaisesRegex(ValueError, 'vendored SDK changed'):
                project.validate(project.snapshot(root))
            path.write_bytes(original)
        project.validate(project.snapshot(root))

    def test_logging_execution_requires_explicit_c_only_selection(self):
        from tools.run_rust_capsule_workflow import run
        for language, logging, clocks in (('java', True, False), ('c', 1, False), ('c', True, True)):
            with self.subTest(language=language, logging=logging, clocks=clocks), self.assertRaisesRegex(
                    RuntimeError, 'c-standard-logging-language'):
                run(Path('missing'), Path('missing'), Path('missing'), self.root / 'must-not-exist',
                    language=language, c_standard_facilities=clocks, c_standard_logging=logging)
            self.assertFalse((self.root / 'must-not-exist').exists())


if __name__ == '__main__':
    unittest.main()
