"""Qualification ownership seams; these mocked child results are not compiler proof."""
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile
from tools import qualify_typescript_standard_clocks as qualification
from tools.rust_capsule_project import inventory, snapshot


class ClockQualification(unittest.TestCase):
    def test_clock_job_requires_same_user_namespace_setup_as_original_isolated_compiler(self):
        from tools.ci_lane_inventory import workflow_model
        from tools.rust_capsule_project import ROOT
        jobs = workflow_model((ROOT/'.github/workflows/typescript-guest.yml').read_text(encoding='utf-8'))['jobs']
        original = next(step['run'] for step in jobs['boundary']['steps']
                        if step.get('name') == 'Install captured JavaScript compiler namespace').splitlines()
        selected = next(step['run'] for step in jobs['standard-clocks']['steps']
                        if step.get('name') == 'Install original isolated compiler prerequisites').splitlines()
        self.assertEqual(selected[:len(original)], original)
        self.assertIn('sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0', original)

    def engine_entries(self):
        entries = []
        for name, (_target, size) in qualification.ENGINE_MEMBERS.items():
            entry = zipfile.ZipInfo(name)
            entry.file_size = size
            entry.external_attr = 0o100600 << 16
            entries.append(entry)
        return entries

    def test_engine_acquisition_selects_only_two_original_pinned_members(self):
        entries = self.engine_entries()
        unrelated = zipfile.ZipInfo('_temp/typescript-promise-library/private-build.log')
        self.assertEqual(qualification.engine_selection([unrelated, *entries]), entries)
        self.assertEqual({name for name, _size in qualification.ENGINE_MEMBERS.values()}, {'engine.wasm', 'engine-input.json'})
        for changed in (entries[:1], [*entries, entries[0]]):
            with self.subTest(count=len(changed)), self.assertRaises(RuntimeError):
                qualification.engine_selection(changed)

    def test_engine_acquisition_rejects_alias_encryption_and_size_drift(self):
        for field, value in (('external_attr', 0o120777 << 16), ('flag_bits', 1), ('file_size', 1)):
            entries = self.engine_entries()
            setattr(entries[0], field, value)
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, 'engine-member-shape'):
                qualification.engine_selection(entries)

    def test_wrong_engine_core_refuses_before_any_current_SDK_validation_or_compilation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'engine.wasm').write_bytes(b'changed public fixture core')
            (root/'engine-input.json').write_bytes(b'{}')
            with self.assertRaisesRegex(RuntimeError, 'authenticated-original-engine'):
                qualification.engine_inputs(root)

    def test_owned_child_failure_restores_exact_original_application_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);project = root/'app';(project/'src').mkdir(parents=True)
            original = b'export const api = {};\n';source = project/'src/main.ts';source.write_bytes(original)
            output = root/'out';output.mkdir()
            with patch('tools.qualify_typescript_standard_clocks.run_bounded_result',
                       side_effect=subprocess.TimeoutExpired('owned-clock-fixture', 300)):
                with self.assertRaises(subprocess.TimeoutExpired):
                    qualification.snapshot_controls(project, root/'engine.wasm', root/'engine-input.json',
                        {'examples/capsule_contracts': root/'contracts', 'examples/package': root/'package'}, root/'tools', output)
            self.assertEqual(source.read_bytes(), original)

    def test_both_snapshot_forms_bind_same_engine_and_preserve_source_without_treating_them_as_passed_components(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);project = root/'app';(project/'src').mkdir(parents=True)
            source = project/'src/main.ts';source.write_bytes(b'export const api = {};\n')
            before = inventory(snapshot(project));output = root/'out';output.mkdir()
            calls = []
            def child(arguments, **options):
                calls.append((arguments, options, source.read_bytes()))
                artifact = Path(arguments[arguments.index('--output')+1]);artifact.mkdir()
                (artifact/'source-inputs.json').write_bytes(inventory(snapshot(project)))
                (artifact/'BUILD-FAILED.json').write_bytes(b'{}\n')
                return SimpleNamespace(returncode=1, stdout=b'', stderr=b'bounded public fixture')
            with patch('tools.qualify_typescript_standard_clocks.run_bounded_result', side_effect=child), \
                    patch('tools.qualify_typescript_dependency_refusals.observed_refusal', return_value={'status': 'refused', 'successfulComponentProduced': False}):
                rows = qualification.snapshot_controls(project, root/'engine.wasm', root/'engine-input.json',
                    {'examples/capsule_contracts': root/'contracts', 'examples/package': root/'package'}, root/'tools', output)
            self.assertEqual(inventory(snapshot(project)), before)
            self.assertEqual([r['observationForm'] for r in rows], ['direct', 'reference'])
            self.assertTrue(all(r['successfulComponentProduced'] is False for r in rows))
            for arguments, options, body in calls:
                self.assertEqual(arguments[arguments.index('--runtime-engine')+1], str(root/'engine.wasm'))
                self.assertEqual(arguments[arguments.index('--runtime-engine-receipt')+1], str(root/'engine-input.json'))
                self.assertEqual(options['timeout_seconds'], 300)
                self.assertIn(b'Date.now', body)


if __name__ == '__main__':
    unittest.main()
