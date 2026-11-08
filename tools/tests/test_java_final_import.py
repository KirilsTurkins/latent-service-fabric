"""Preparation/selection controls; these do not claim signed guest execution."""
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import ci_lane_inventory as lanes
from tools import guest_final_import_control as control
from tools import qualify_java_final_import as owner
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import digest


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


@unittest.skipUnless(shutil.which('wasm-tools'), 'pinned wasm-tools is required for the tiny fixture')
class JavaFinalImportPreparation(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.wasm = Path(shutil.which('wasm-tools')).resolve()
        if subprocess.check_output([str(self.wasm), '--version']).strip() != b'wasm-tools 1.254.0':
            self.skipTest('requires wasm-tools 1.254.0')
        self.fixture = self.root / 'fixture'
        for name in ('build', 'src', 'wit'):
            (self.fixture / name).mkdir(parents=True, exist_ok=True)
        self.source = (owner.ROOT / owner.SOURCE).read_bytes()
        (self.fixture / 'src/Capsule.java').write_bytes(self.source)
        (self.fixture / 'wit/service.wit').write_text('test-only WIT', encoding='utf8')
        self.wat = self.root / 'original.wat'
        self.component = self.fixture / 'build/component.wasm'
        self.assemble(control.TEMPLATE.replace(control.UNKNOWN, 'example:original/entry@0.1.0'))
        self.write_receipt()

    def assemble(self, text):
        self.wat.write_text(text, encoding='utf8')
        subprocess.run([str(self.wasm), 'parse', str(self.wat), '-o', str(self.component)], check=True)

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
        self.assertEqual(json.loads((self.root / 'control/PREPARED.json').read_bytes()), result)

    def test_changed_compile_receipt_is_refused_before_output(self):
        self.write_receipt(componentDigest='sha256:' + '0' * 64)
        with self.assertRaisesRegex(WorkflowError, 'java-final-import-source-and-compile-receipt'):
            owner.prepare(self.fixture, self.root / 'control', self.wasm)
        self.assertFalse((self.root / 'control').exists())

    def test_existing_unknown_import_is_refused(self):
        self.assemble(control.TEMPLATE)
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
