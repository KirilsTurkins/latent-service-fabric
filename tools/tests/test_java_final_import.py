"""Preparation controls use command doubles; hosted execution uses the real tool."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from tools import ci_lane_inventory as lanes
from tools import ci_suite_discovery as discovery, ci_suite_inventory as suites
from tools import guest_final_import_control as control
from tools import qualify_java_final_import as owner
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import digest
from tools.tests.test_guest_final_import_control import TEMPLATE


class JavaFinalImportVersion(unittest.TestCase):
    def test_only_the_two_exact_pinned_validator_reports_are_accepted(self):
        for report in (b'wasm-tools 1.254.0\n',
                       b'wasm-tools 1.254.0 (bb58fdf91 2026-07-20)\n'):
            with self.subTest(report=report):
                self.assertTrue(owner.pinned_validator_report(report))
        for report in (b'wasm-tools 1.254.1\n', b'wasm-tools 1.254.0-extra\n',
                       b'wasm-tools 1.254.0 (000000000 2026-07-20)\n',
                       b'wasm-tools 1.254.0 (bb58fdf91 2026-07-20) extra\n'):
            with self.subTest(report=report):
                self.assertFalse(owner.pinned_validator_report(report))


class JavaFinalImportSelection(unittest.TestCase):
    def test_workflow_selects_and_retains_the_control(self):
        path = owner.ROOT / '.github/workflows/java-guest-feasibility.yml'
        model = lanes.structural_workflow(lanes.workflow_model(path.read_text(encoding='utf8')))
        job = model['jobs']['compiler-component']
        steps = job['steps']
        by_id = {step['id']: step for step in steps if 'id' in step}
        timer = by_id['signed-java-standard-timers']
        prepare = by_id['prepare-java-final-import']
        signed = by_id['signed-java-final-import']
        self.assertLess(steps.index(timer), steps.index(prepare))
        self.assertLess(steps.index(prepare), steps.index(signed))
        for step in (prepare, signed):
            self.assertNotIn('continue-on-error', step)
        self.assertIn('tools/qualify_java_final_import.py', prepare['run'])
        self.assertIn('--fixture "$RUNNER_TEMP/java-standard-timers"', prepare['run'])
        self.assertIn('--output "$RUNNER_TEMP/java-standard-timers/final-import"', prepare['run'])
        self.assertIn('--wasm-tools "$(command -v wasm-tools)"', prepare['run'])
        self.assertEqual(signed['env']['LSF_GUEST_SDK_LANGUAGE'], 'java')
        self.assertEqual(signed['env']['LSF_JAVA_TIMER_FIXTURE'], '${{ runner.temp }}/java-standard-timers')
        self.assertEqual(signed['env']['LSF_SDK694_FINAL_IMPORT_CONTROL'],
                         '${{ runner.temp }}/java-standard-timers/final-import')
        self.assertIn('runtime::unknown_import::signed_unknown_final_import_is_refused_before_execution_and_fresh_tenant_succeeds',
                      signed['run'])
        self.assertIn('--ignored --exact', signed['run'])
        retained = [step for step in steps if 'java-standard-timers/final-import/**'
                    in step.get('with', {}).get('path', '')]
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0]['if'], 'always()')
        contract = json.loads((owner.ROOT / 'tools/ci/contracts/workflows/java-guest-feasibility.yml/jobs/compiler-component.json').read_text())
        self.assertEqual(contract['definition'], job)

    def test_ignored_case_is_registered_without_weakening_discovery(self):
        inventory = suites.load()
        row, = (suite for suite in inventory['suites'] if suite['id'] == 'latent-wasmtime.test.local-service')
        name = 'runtime::unknown_import::signed_unknown_final_import_is_refused_before_execution_and_fresh_tenant_succeeds'
        self.assertIn(name, row['expectedIgnored'])
        self.assertIn(name.rsplit('::', 1)[1], row['ignoredLeaves'])
        ignored = frozenset(row['expectedIgnored'])
        available = ignored | {'ordinary::case'}
        discovery.validate_cases(row, available, ignored, {})
        with self.assertRaisesRegex(ValueError, 'changed-test-ignore-state'):
            discovery.validate_cases(row, available, ignored - {name}, {})
        with self.assertRaisesRegex(ValueError, 'unexpectedly-ignored-case'):
            discovery.validate_cases(row, available | {'unexpected::case'}, ignored | {'unexpected::case'}, {})


class FixtureCommands:
    """Bounded command double; the hosted owner runs the real pinned validator."""

    def __init__(self, root, output, environment, **options):
        self.output = output
        self.records = []

    def run(self, stage, *command):
        self.records.append({'stage': stage, 'exitCode': 0})
        if stage == 'pinned-validator-version':
            return b'wasm-tools 1.254.0 (bb58fdf91 2026-07-20)\n'
        if stage == 'assemble-declaration-only-template':
            (self.output / 'unknown.wasm').write_bytes(TEMPLATE)
            return b''
        if stage.startswith('validate-'):
            control.sections(Path(command[-1]).read_bytes())
            return b''
        if stage in {'original-wit', 'appended-wit'}:
            raw = Path(command[-2]).read_bytes()
            name = None
            for candidate in ('final-import', 'final-imporx'):
                if ('diagnostic:unknown/' + candidate + '@0.1.0').encode() in raw:
                    name = candidate
            functions = {}
            if name:
                function = 'toucb' if b'toucb' in raw else 'touch'
                functions[function] = {'name': function, 'kind': 'freestanding', 'params': []}
            graph = {
                'worlds': [{'name': 'test', 'package': 0,
                            'imports': {'one': {'interface': {'id': 0}}} if name else {},
                            'exports': {}}],
                'interfaces': [{'name': name, 'package': 1, 'types': {}, 'functions': functions}] if name else [],
                'types': [],
                'packages': [{'name': 'test:fixture@0.1.0'}, {'name': 'diagnostic:unknown@0.1.0'}],
            }
            return json.dumps(graph).encode()
        raise AssertionError('unexpected preparation stage: ' + stage)


class JavaFinalImportPreparation(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.wasm = self.root / 'test-validator'
        self.wasm.write_bytes(b'test-only validator identity')
        self.fixture = self.root / 'fixture'
        for name in ('build', 'src', 'wit'):
            (self.fixture / name).mkdir(parents=True, exist_ok=True)
        self.source = (owner.ROOT / owner.SOURCE).read_bytes()
        (self.fixture / 'src/Capsule.java').write_bytes(self.source)
        (self.fixture / 'wit/service.wit').write_text('test-only WIT', encoding='utf8')
        self.component = self.fixture / 'build/component.wasm'
        self.component.write_bytes(control.COMPONENT)
        self.patch_commands = patch.object(owner, 'Commands', FixtureCommands)
        self.patch_commands.start()
        self.addCleanup(self.patch_commands.stop)
        self.write_receipt()

    def write_receipt(self, **overrides):
        receipt = {'fixture': 'timers', 'profile': 'teavm-activation-fibers-v1',
                   'status': 'component-built-unqualified', 'sourceDigest': digest(self.source),
                   'componentDigest': digest(self.component.read_bytes())}
        receipt.update(overrides)
        (self.fixture / 'FIBERS-COMPILE.json').write_text(json.dumps(receipt), encoding='utf8')

    def test_validated_mutant_is_bound_without_claiming_execution(self):
        result = owner.prepare(self.fixture, self.root / 'control', self.wasm)
        original = self.component.read_bytes()
        mutant = (self.root / 'control/component.wasm').read_bytes()
        self.assertTrue(mutant.startswith(original))
        self.assertEqual(result['mutantDigest'], digest(mutant))
        self.assertEqual(result['suffixDigest'], digest(mutant[len(original):]))
        self.assertEqual(result['unknownInterface'], control.UNKNOWN)
        self.assertEqual(result['runtimeOutcome'], 'not-executed')
        self.assertEqual([row['stage'] for row in result['commands']],
                         ['pinned-validator-version', 'assemble-declaration-only-template',
                          'validate-original', 'original-wit', 'validate-appended-import', 'appended-wit'])
        self.assertEqual(json.loads((self.root / 'control/PREPARED.json').read_bytes()), result)

    def test_changed_compile_receipt_is_refused_before_output(self):
        self.write_receipt(componentDigest='sha256:' + '0' * 64)
        with self.assertRaisesRegex(WorkflowError, 'java-final-import-source-and-compile-receipt'):
            owner.prepare(self.fixture, self.root / 'control', self.wasm)
        self.assertFalse((self.root / 'control').exists())

    def test_existing_unknown_import_is_refused(self):
        self.component.write_bytes(TEMPLATE)
        self.write_receipt()
        with self.assertRaisesRegex(WorkflowError, 'java-final-import-already-present'):
            owner.prepare(self.fixture, self.root / 'control', self.wasm)

    def test_missing_suffix_is_refused(self):
        with patch.object(control, 'append_unknown', side_effect=lambda raw, template: raw):
            with self.assertRaisesRegex(WorkflowError, 'java-final-import-complete-original-prefix'):
                owner.prepare(self.fixture, self.root / 'control', self.wasm)

    def test_different_import_is_refused(self):
        append = control.append_unknown
        def different(raw, template):
            mutant = append(raw, template)
            suffix = mutant[len(raw):].replace(b'final-import', b'final-imporx')
            return raw + suffix
        with patch.object(control, 'append_unknown', side_effect=different):
            with self.assertRaisesRegex(WorkflowError, 'java-final-import-exact-surface-change'):
                owner.prepare(self.fixture, self.root / 'control', self.wasm)

    def test_changed_callable_is_refused(self):
        append = control.append_unknown
        def different(raw, template):
            mutant = append(raw, template)
            return raw + mutant[len(raw):].replace(b'touch', b'toucb')
        with patch.object(control, 'append_unknown', side_effect=different):
            with self.assertRaisesRegex(WorkflowError, 'java-final-import-exact-callable-type'):
                owner.prepare(self.fixture, self.root / 'control', self.wasm)


if __name__ == '__main__':
    unittest.main()
