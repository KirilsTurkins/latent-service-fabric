"""Evidence admission controls; real compiler observations are a separate gate."""
from pathlib import Path
import json
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import qualify_typescript_dependency_refusals as refusal
from tools.phase2_operator_process import WorkflowError


class DependencyRefusalEvidence(unittest.TestCase):
    def fixture(self, root, case):
        output = root / 'build'
        (output / 'logs').mkdir(parents=True)
        commands = [{'stage': 'contracts', 'exitCode': 0, 'seconds': 0.01},
                    {'stage': 'typecheck', 'exitCode': 0, 'seconds': 0.01}]
        if case[1] == 'componentize':
            commands.append({'stage': 'bundle', 'exitCode': 0, 'seconds': 0.01})
        commands.append({'stage': case[1], 'exitCode': 1, 'seconds': 0.01})
        failure = {'formatVersion': 1, 'stage': 'compile', 'commands': commands,
                   'reason': 'fixture diagnostic never becomes public'}
        (output / 'BUILD-FAILED.json').write_text(json.dumps(failure))
        (output / 'logs' / f'{len(commands)-1:02d}-{case[1]}.stderr.txt').write_bytes(case[2].encode())
        completed = subprocess.CompletedProcess(['not-executed'], 1, b'', b'')
        return output, completed, failure

    def test_all_five_fixed_cases_have_distinct_reachable_original_package_inputs(self):
        names = [row[0] for row in refusal.CASES]
        self.assertEqual(names, ['dynamic-import', 'eval', 'native-addon', 'snapshot-clock', 'snapshot-entropy'])
        sources = []
        for name in names:
            files = refusal.fixture_files(name)
            self.assertIn(b'throw new Error', files['forbidden.cjs'])
            manifest = json.loads(files['package.json'])
            self.assertEqual(manifest['exports'], {'types': './index.d.ts', 'import': './index.mjs'})
            self.assertEqual(manifest['scripts'], {'prepare': 'node forbidden.cjs'})
            sources.append(files['index.mjs'])
        self.assertEqual(len(set(sources)), 5)
        self.assertIn(b"import('./loaded.mjs')", sources[0])
        self.assertIn(b'globalThis.eval(', sources[1])
        self.assertIn('addon.node', refusal.fixture_files('native-addon'))
        self.assertTrue(sources[3].startswith(b'const observed = Date.now();'))
        self.assertTrue(sources[4].startswith(b'const observed = Math.random();'))

    def test_unknown_case_and_non_linux_execution_refuse_before_workspace_creation(self):
        with self.assertRaisesRegex(WorkflowError, 'case-unknown'):
            refusal.fixture_files('unreviewed')
        with tempfile.TemporaryDirectory() as temporary, patch.object(refusal.sys, 'platform', 'win32'):
            output = Path(temporary) / 'output'
            with self.assertRaisesRegex(WorkflowError, 'linux-compiler-required'):
                refusal.qualify(output, Path('tools'), Path('contracts'), Path('packager'))
            self.assertFalse(output.exists())

    def test_closed_evidence_distinguishes_bundle_from_actual_snapshot_refusals(self):
        for case in refusal.CASES:
            with self.subTest(case=case[0]), tempfile.TemporaryDirectory() as temporary:
                output, completed, _ = self.fixture(Path(temporary), case)
                row = refusal.observed_refusal(output, case, completed)
                self.assertEqual(row['case'], case[0])
                self.assertEqual(row['compilerCommand'], case[1])
                self.assertEqual(row['boundary'], 'actual-component-snapshot' if case[1] == 'componentize'
                                 else 'actual-bundle-before-componentize')
                self.assertIs(row['successfulComponentProduced'], False)
                self.assertIs(row['completedOwnedProcessCleanup'], True)

    def test_generic_error_missing_marker_or_wrong_build_stage_cannot_qualify(self):
        for mutate in ('marker', 'phase', 'earlier-failure', 'wrong-command'):
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as temporary:
                case = refusal.CASES[0]
                output, completed, failure = self.fixture(Path(temporary), case)
                if mutate == 'marker':
                    (output / 'logs/02-bundle.stderr.txt').write_bytes(b'unknown failure')
                elif mutate == 'phase':
                    failure['stage'] = 'compiler-inputs'
                elif mutate == 'earlier-failure':
                    failure['commands'][0]['exitCode'] = 1
                else:
                    failure['commands'][-1]['stage'] = 'typecheck'
                (output / 'BUILD-FAILED.json').write_text(json.dumps(failure))
                with self.assertRaises((WorkflowError, ValueError)):
                    refusal.observed_refusal(output, case, completed)

    def test_success_or_partial_publication_is_not_a_negative_even_with_the_expected_message(self):
        for artifact in ('BUILD-COMPLETE.json', 'component.wasm', 'package'):
            with self.subTest(artifact=artifact), tempfile.TemporaryDirectory() as temporary:
                case = refusal.CASES[0]
                output, completed, _ = self.fixture(Path(temporary), case)
                (output / artifact).write_bytes(b'produced')
                with self.assertRaisesRegex(WorkflowError, 'success-artifact-present'):
                    refusal.observed_refusal(output, case, completed)
        with tempfile.TemporaryDirectory() as temporary:
            case = refusal.CASES[0]
            output, completed, _ = self.fixture(Path(temporary), case)
            completed.returncode = 0
            with self.assertRaisesRegex(WorkflowError, 'completed-negative'):
                refusal.observed_refusal(output, case, completed)

    def test_compiler_advance_or_malformed_nonfinite_timing_cannot_masquerade_as_early_refusal(self):
        for change in ('advanced', 'nan', 'bool', 'extra', 'count'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                case = refusal.CASES[0]
                output, completed, failure = self.fixture(Path(temporary), case)
                if change == 'advanced':
                    failure['commands'].insert(1, {'stage': 'componentize', 'exitCode': 0, 'seconds': 0.01})
                elif change == 'count':
                    failure['commands'] *= 50
                elif change == 'extra':
                    failure['commands'][0]['argv'] = ['private-value']
                else:
                    failure['commands'][0]['seconds'] = float('nan') if change == 'nan' else True
                (output / 'BUILD-FAILED.json').write_text(json.dumps(failure))
                with self.assertRaises((WorkflowError, ValueError)):
                    refusal.observed_refusal(output, case, completed)

    def test_private_streams_paths_and_exception_messages_are_not_projected(self):
        with tempfile.TemporaryDirectory() as temporary:
            case = refusal.CASES[0]
            output, completed, failure = self.fixture(Path(temporary), case)
            sentinel = 'credential-secret-path-token'
            completed.stdout = completed.stderr = sentinel.encode()
            failure['reason'] = sentinel
            (output / 'BUILD-FAILED.json').write_text(json.dumps(failure))
            (output / 'logs/02-bundle.stderr.txt').write_bytes(case[2].encode() + b'\n' + sentinel.encode())
            row = refusal.observed_refusal(output, case, completed)
            self.assertNotIn(sentinel, json.dumps(row))
            self.assertEqual(set(row), {'case', 'status', 'compilerCommand', 'boundary', 'reason',
                                       'successfulComponentProduced', 'completedOwnedProcessCleanup'})

    def test_original_template_hook_cannot_silently_disappear_before_capture(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = refusal.create(root / 'project', 'greeting')
            (project / 'src/main.ts').write_bytes(b'export const api = {};')
            commands = Mock()
            with self.assertRaisesRegex(WorkflowError, 'original-template-required'):
                refusal.install_case(project, root / 'outside', 'eval', commands)
            commands.run.assert_not_called()

    def test_normal_native_authoring_commands_precede_owned_original_removal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = refusal.create(root / 'project', 'greeting')
            outside = root / 'outside'
            commands = Mock()
            calls = []
            def run(stage, *args):
                self.assertTrue(outside.exists())
                calls.append((stage, args))
                if stage == 'eval-resolve':
                    candidate = project / 'target/refusal.candidate.json'
                    candidate.parent.mkdir()
                    candidate.write_bytes(b'{"captured":true}')
                if stage == 'eval-review':
                    (project / 'latent.dependencies.lock.json').write_bytes(b'{"accepted":true}')
            commands.run.side_effect = run
            before_sdk = (project / 'sdk-lock.json').read_bytes()
            with patch.object(refusal, 'verify_inputs', return_value=Mock(lock={
                    'selection': {'runtimeProfile': 'spidermonkey-public-sync-v1'}})):
                captured = refusal.install_case(project, outside, 'eval', commands)
            self.assertEqual([name for name, _ in calls], ['eval-add', 'eval-lock', 'eval-resolve', 'eval-review'])
            self.assertTrue(all(args[:3] == (refusal.sys.executable, '-B', refusal.CLI) for _, args in calls))
            self.assertEqual(calls[-1][1][-1], refusal.digest(b'{"captured":true}'))
            self.assertFalse(outside.exists())
            self.assertEqual(before_sdk, (project / 'sdk-lock.json').read_bytes())
            self.assertIs(captured['originalsRemovedBeforeBuild'], True)
            self.assertIn(b'return negative(clean);', (project / 'src/main.ts').read_bytes())

    def test_failed_observer_never_replaces_the_original_qualification_error(self):
        for observer in (RuntimeError('observer'), RecursionError('bounded JSON recursion')):
            with self.subTest(observer=type(observer).__name__), tempfile.TemporaryDirectory() as temporary:
                original = RuntimeError('original capture failure')
                with patch.object(refusal.sys, 'platform', 'linux'), \
                     patch.object(refusal.Compiler, 'identity', return_value={}), \
                     patch.object(refusal, 'install_case', side_effect=original), \
                     patch.object(refusal, 'write_json', side_effect=observer), \
                     self.assertRaises(RuntimeError) as raised:
                    refusal.qualify(Path(temporary) / 'output', Path('never-started'),
                                    refusal.CLI, refusal.CLI)
                self.assertIs(raised.exception, original)


if __name__ == '__main__':
    unittest.main()
