"""Go compiler installation and immutable qualification boundaries; no guest credit."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.go_guest import standard_log as logging
from tools.go_guest import runtime
from tools.go_capsule_project import ROOT, create, snapshot, validate
from tools.go_capsule_build import RECIPE
from tools import qualify_go_standard_logging as qualification
from tools.rust_capsule_project import digest, write_json
from tools.phase2_operator_process import WorkflowError

RAW = '''package latent_log_log
//go:wasmimport latent:log/log@0.1.0 write
func Write()
type Field struct{}
type LogError struct{}
const (LevelInfo = 2; LevelError = 4; LogErrorBudgetExhausted = 0; LogErrorInvalidField = 1)
'''


class StandardLogging(unittest.TestCase):
    def module(self, parent, *, identity='latent_log_log'):
        module = parent / 'module'
        module.mkdir()
        (module / 'wit_exports.go').write_text('package main\n')
        raw = module / identity / 'wit_bindings.go'
        raw.parent.mkdir()
        raw.write_text(RAW.replace('latent_log_log', identity))
        return module, raw

    def test_no_import_keeps_source_and_selection_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            module = Path(directory)
            (module / 'wit_exports.go').write_text('package main\n')
            before = snapshot(module)
            self.assertEqual(logging.install(ROOT / 'sdk/go-guest', module, 'go-component-async-v1'), (False, []))
            self.assertEqual(snapshot(module), before)

    def test_actual_generated_namespace_is_used_and_source_identities_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            module, raw = self.module(Path(directory), identity='unseen_generated_log')
            before = raw.read_bytes()
            installed, transformations = logging.install(ROOT / 'sdk/go-guest', module, 'go-component-async-v1')
            self.assertTrue(installed)
            self.assertEqual(raw.read_bytes(), before)
            data = (module / 'lsf/standardlog/log.go').read_bytes()
            self.assertIn(b'raw "wit_component/unseen_generated_log"', data)
            self.assertNotIn(b'@raw@', data)
            self.assertEqual(transformations[0]['adaptedDigest'], digest(data))
            self.assertTrue(transformations[0]['name'].startswith('go-standard-log/'))
            self.assertIn(b'import _ "wit_component/lsf/standardlog"',
                          (module / 'lsf_standard_log.go').read_bytes())

    def test_ambiguous_import_is_refused_before_writing_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            module, raw = self.module(Path(directory))
            second = module / 'another/wit_bindings.go'
            second.parent.mkdir()
            second.write_bytes(raw.read_bytes())
            with self.assertRaisesRegex(ValueError, 'ambiguous'):
                logging.install(ROOT / 'sdk/go-guest', module, 'go-component-async-v1')
            self.assertFalse((module / 'lsf').exists())

    def test_foreign_namespace_or_missing_canonical_types_is_refused(self):
        for source in (RAW.replace('package latent_log_log', 'package another'),
                       RAW.replace('type LogError struct{}', '')):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as directory:
                module, raw = self.module(Path(directory))
                raw.write_text(source)
                with self.assertRaisesRegex(ValueError, 'package|type-drift'):
                    logging.install(ROOT / 'sdk/go-guest', module, 'go-component-async-v1')
                self.assertFalse((module / 'lsf').exists())

    def test_foreign_entry_and_existing_generated_output_are_refused(self):
        for entry in ('package other\n', 'package main\n'):
            with self.subTest(entry=entry), tempfile.TemporaryDirectory() as directory:
                module, _ = self.module(Path(directory))
                (module / 'wit_exports.go').write_text(entry)
                if entry == 'package main\n':
                    (module / 'lsf_standard_log.go').write_bytes(b'owned application data')
                before = snapshot(module)
                with self.assertRaisesRegex(ValueError, 'entry-drift|output-collision'):
                    logging.install(ROOT / 'sdk/go-guest', module, 'go-component-async-v1')
                self.assertEqual(snapshot(module), before)

    def test_syscall_write_preserves_non_stdio_path_and_unselected_failure(self):
        source = logging.syscall_source(logging.WRITE)
        self.assertIn('if fd == 1 || fd == 2', source)
        self.assertIn('if lsfStandardWrite == nil { return 0, EBADF }', source)
        self.assertIn('errno := fd_write(int32(fd), makeIOVec(b), 1, &nwritten)', source)
        self.assertIn('runtime.KeepAlive(b)', source)
        with self.assertRaisesRegex(ValueError, 'contract-drift'):
            logging.syscall_source(logging.WRITE + '\n' + logging.WRITE)

    def test_hook_is_installed_before_runtime_and_application_initializers(self):
        source = 'func main() {\n\tdoInit(runtime_inittasks) // Must be before defer.\n}\n'
        adapted = logging.runtime_source(source)
        self.assertLess(adapted.index('lsfInstallStandardLog()'), adapted.index('doInit(runtime_inittasks)'))
        self.assertIn('//go:linkname lsfInstallStandardLog', adapted)
        with self.assertRaisesRegex(ValueError, 'contract-drift'):
            logging.runtime_source('func main() {}')

    def test_runtime_selection_rejects_non_boolean_before_materializing_overlay(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for value in (0, 1, 'true', None):
                with self.subTest(value=value), patch.object(runtime, 'checked_sources', return_value={}):
                    with self.assertRaisesRegex(ValueError, 'must-be-boolean'):
                        runtime.overlay(root / 'goroot', root / 'overlay', standard_log=value)
                    self.assertFalse((root / 'overlay').exists())

    def test_independent_projects_capture_the_new_bridge_without_implicit_log_grant(self):
        with tempfile.TemporaryDirectory() as directory:
            project = create(Path(directory) / 'application', 'greeting')
            files = snapshot(project)
            document, _, _ = validate(files)
            self.assertIn('vendor/lsf/sdk/go-guest/runtime/standard_log.go.in', files)
            self.assertNotIn(b'latent:log/log', files['wit/world.wit'])
            self.assertEqual(document['limits']['logBytes'], 0)
            self.assertIn('tools/go_guest/standard_log.py', RECIPE)

    def test_frozen_qualification_requires_current_source_and_companion_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            native = Path(directory)
            source = {'current': True}
            write_json(native / 'source-inputs.json', source)
            from tools.qualify_go_standard_http import NATIVE_NAMES
            products = native / 'native-binaries'
            products.mkdir()
            identities = {}
            for name, key in NATIVE_NAMES.items():
                path = products / key.replace('/', '-')
                path.write_bytes(name.encode())
                identities[key] = qualification.file_identity(path)
            builds = {}
            for name in sorted(set(qualification.TEMPLATES) - {'greeting'}):
                path = native / 'builds' / name
                path.mkdir(parents=True)
                builds[name] = {'identity': name}
                write_json(path / 'BUILD-COMPLETE.json', builds[name])
            receipt = {'schemaVersion': 'latent.go-capsule.qualification.v1', 'status': 'passed',
                'sourceIdentityDigest': digest((native / 'source-inputs.json').read_bytes()),
                'binaries': identities, 'builds': builds}
            write_json(native / 'qualification.json', receipt)
            with patch.object(qualification, 'inputs', return_value=source):
                self.assertEqual(qualification.frozen(native)[0], receipt)
                path = native / 'builds' / next(iter(builds)) / 'BUILD-COMPLETE.json'
                path.write_text(json.dumps({'identity': 'foreign'}))
                with self.assertRaisesRegex(WorkflowError, 'companion-build-mismatch'):
                    qualification.frozen(native)
                path.write_text(json.dumps(next(iter(builds.values()))))
                (products / 'latentd').write_bytes(b'foreign native product')
                with self.assertRaisesRegex(WorkflowError, 'native-product-mismatch'):
                    qualification.frozen(native)
            with patch.object(qualification, 'inputs', return_value={'stale': True}):
                with self.assertRaisesRegex(WorkflowError, 'current-normal'):
                    qualification.frozen(native)

    def test_wrong_language_cannot_enable_signed_logging_programme(self):
        from tools.run_rust_capsule_workflow import run
        for language, selection in (('rust', True), ('go', 1)):
            with self.subTest(language=language, selection=selection):
                with self.assertRaisesRegex(WorkflowError, 'Go-standard-logging-language'):
                    run(None, None, None, None, language=language, go_standard_logging=selection)


if __name__ == '__main__':
    unittest.main()
