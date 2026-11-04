"""Source, refusal, and public-evidence controls for the paired diagnostic."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import admit_dotnet_poll_prefetch_evidence as admission
from tools import dotnet_poll_prefetch_node as node
from tools import qualify_dotnet_poll_prefetch as qualification
from tools import run_dotnet_poll_prefetch_pair as owner
from tools.phase2_operator_process import WorkflowError
from tools.phase3_resource_identity import file_identity


class DotnetPollPrefetchTests(unittest.TestCase):
    def test_deployment_budget_refuses_extra_authority_and_changed_limits(self):
        target = {'budget': dict(node.ORIGINAL_BUDGET)}
        self.assertEqual(node.original_budget(target), node.ORIGINAL_BUDGET)
        for key, value in (('cpuFuel', 1000000001), ('memoryBytes', 134217729),
                ('wallTimeLimitMillis', 120001), ('outboundRequests', 1), ('effectCount', 1), ('logBytes', False)):
            changed = {'budget': dict(node.ORIGINAL_BUDGET)}; changed['budget'][key] = value
            with self.subTest(key=key), self.assertRaises(WorkflowError): node.original_budget(changed)

    def test_fixture_observes_real_slot_and_holder_and_roots_metadata(self):
        source = (Path(__file__).resolve().parents[1] / 'fixtures/dotnet-poll-prefetch/Library.cs').read_text()
        self.assertEqual(source.count('[DynamicDependency('), 12)
        for control in ('ReferenceEquals(itemState.GetValue(item), Marker)',
                'ThreadPool.PendingWorkItemCount == 0', 'ThreadPool.PendingWorkItemCount == 1',
                'ThreadPool.PendingWorkItemCount == 2', 'ReferenceEquals(MainTask.GetValue(null), Sibling.Task)',
                'AggregateTarget.GetValue(null) is null', 'Driver is not null && !Driver.IsCompleted',
                'Driver!.IsCompletedSuccessfully ? 1 : 0', 'return NoHandles;',
                'probe.HookStop.Cancel(); probe.TimerStop.Cancel();'):
            self.assertIn(control, source)
        self.assertNotIn('Thread.Sleep(', source)
        self.assertNotIn('new Thread(', source)

    def test_hosted_owner_is_branch_scoped_bounded_and_preserves_both_variants(self):
        from tools import ci_lane_inventory
        root = Path(__file__).resolve().parents[2]
        path = root / '.github/workflows/dotnet-poll-prefetch-diagnostic.yml'
        workflow = ci_lane_inventory.workflow_model(path.read_text(encoding='utf-8'))
        self.assertEqual(workflow['on']['push']['branches'], ['diag/dotnet-poll-prefetch-20261104'])
        self.assertEqual(workflow['permissions'], {'contents': 'read', 'actions': 'read'})
        self.assertEqual(workflow['jobs']['diagnostic']['timeout-minutes'], 70)
        commands = '\n'.join(step.get('run', '') for step in workflow['jobs']['diagnostic']['steps'])
        self.assertIn('3000s python3 -B tools/run_dotnet_poll_prefetch_pair.py', commands)
        self.assertIn('--baseline "$RUNNER_TEMP/dotnet-prefetch-baseline"', commands)
        self.assertIn('--fixed "$GITHUB_WORKSPACE"', commands)
        self.assertIn('--expected-head "$GITHUB_SHA"', commands)
        self.assertIn('from tools.wasmtime_48_0_8_678b_native_products import SOURCE', commands)
        self.assertNotIn('60c71d86079318fcc0326c756e1643c32571f1fc', commands)
        self.assertIn('180s python3 -B tools/wasmtime_48_0_8_678b_native_products.py', commands)
        self.assertEqual(qualification.VARIANTS['baseline'][0], 'latent.dotnet.wait-all.v2')
        self.assertEqual(qualification.VARIANTS['fixed'][0], 'latent.dotnet.wait-all.v3')
        self.assertNotEqual(qualification.VARIANTS['baseline'][1], qualification.VARIANTS['fixed'][1])

    def test_ordinary_finite_fixture_retains_its_original_default_cases(self):
        import inspect
        from tools import dotnet_finite_wait_fixture
        self.assertEqual(len(dotnet_finite_wait_fixture.CASES), 14)
        self.assertNotIn('poll-prefetch', dotnet_finite_wait_fixture.CASES)
        self.assertIs(inspect.signature(dotnet_finite_wait_fixture.prepare).parameters[
            'poll_prefetch_diagnostic'].default, False)

    def test_evidence_admission_copies_only_closed_public_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'pair/baseline/node').mkdir(parents=True)
            (root / 'pair/baseline/node/progress.json').write_text('{}')
            (root / 'pair/baseline/project').mkdir(); (root / 'pair/baseline/project/private-key.txt').write_text('not-public')
            result = admission.admit(root)
            self.assertEqual(set(result['files']), {'pair/baseline/node/progress.json'})
            self.assertTrue((root / 'public/pair/baseline/node/progress.json').is_file())
            self.assertFalse((root / 'public/pair/baseline/project/private-key.txt').exists())

    def test_evidence_overflow_refuses_before_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'pair').mkdir(); (root / 'pair/qualified.json').write_bytes(b'12345')
            with patch.object(admission, 'MAX_FILE', 4), self.assertRaises((ValueError, WorkflowError)):
                admission.admit(root)
            self.assertEqual(json.loads((root / 'evidence-admission.json').read_text())['status'], 'failed')
            self.assertFalse((root / 'public').exists())

    def test_native_materials_reject_missing_or_changed_current_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); native = root / 'native'; native.mkdir(); rows = {}
            for i in range(135):
                path = root / ('source' + str(i)); path.write_text(str(i)); rows[path.name] = file_identity(path)
            (native / 'native-products.json').write_text(json.dumps({'materials': rows}))
            with patch.object(qualification, 'ROOT', root):
                self.assertEqual(qualification.current_materials(native), rows)
                (root / 'source0').write_text('changed')
                with self.assertRaises(WorkflowError): qualification.current_materials(native)
                del rows['source1']; (native / 'native-products.json').write_text(json.dumps({'materials': rows}))
                with self.assertRaises(WorkflowError): qualification.current_materials(native)

    def test_node_refuses_unknown_expected_result_before_any_execution(self):
        with self.assertRaises(WorkflowError):
            node.run(Path('unused-component'), {}, Path('unused-output'), expected='unexpected')

    def test_only_known_reaped_mismatch_with_clean_shutdown_allows_second_variant(self):
        value = {'schemaVersion': 'latent.dotnet.poll-prefetch.node.v1', 'status': 'failed',
            'stage': 'one-actual-prefetch-observation', 'resultMatched': False,
            'attempts': [{'invocation': {'processReaped': True, 'response': {'outcomeKnown': True}}}],
            'retirement': {'provider': {}, 'physical': {}}, 'afterDeletes': {},
            'nodeShutdown': {'reaped': True, 'record': {'clean': True}},
            'peerShutdown': {'reaped': True, 'closed': True, 'exitCode': 0}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); receipt = root / 'node/FAILED.json'; receipt.parent.mkdir()
            def check(expected):
                receipt.write_text(json.dumps(value), encoding='utf-8')
                self.assertIs(owner.failed_variant_cleaned(root), expected)
            check(True)
            for obj, key, bad in ((value, 'resultMatched', True),
                    (value['attempts'][0]['invocation']['response'], 'outcomeKnown', False),
                    (value['nodeShutdown'], 'reaped', False),
                    (value['peerShutdown'], 'closed', False)):
                previous = obj[key]; obj[key] = bad; check(False); obj[key] = previous
            del value['retirement']; check(False)

    def test_pair_does_not_run_fixed_after_unconfirmed_baseline_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); fixed = root / 'fixed'; fixed.mkdir()
            env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GIT_NO_LAZY_FETCH='1')
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=fixed, env=env, stderr=subprocess.DEVNULL).decode().strip()
            git('init', '-q')
            (fixed / 'base').write_text('base'); git('add', '.')
            git('-c', 'user.name=Diagnostic Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'base')
            base = git('rev-parse', 'HEAD')
            for name in (owner.FIXTURE, *owner.FIX_PATHS):
                path = fixed / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('before')
            git('add', '.'); git('-c', 'user.name=Diagnostic Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'baseline')
            baseline = root / 'baseline'; git('worktree', 'add', '-q', '--detach', str(baseline), 'HEAD')
            for name in owner.FIX_PATHS: (fixed / name).write_text('after')
            git('add', '.'); git('-c', 'user.name=Diagnostic Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixed')
            native, tools = root / 'native', root / 'tools'; native.mkdir(); tools.mkdir()
            with patch.object(owner.sys, 'platform', 'linux'), patch.object(owner, 'Commands') as commands:
                commands.return_value.run.side_effect = RuntimeError('incomplete owner')
                commands.return_value.records = []
                with self.assertRaisesRegex(WorkflowError, 'baseline-cleanup-required'):
                    owner.pair(baseline, fixed, native, tools, root / 'output',
                        expected_base=base, expected_head=git('rev-parse', 'HEAD'))
                self.assertEqual(commands.return_value.run.call_count, 1)

    def test_pair_rejects_an_unreviewed_difference_before_host_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); fixed = root / 'fixed'; fixed.mkdir()
            env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GIT_NO_LAZY_FETCH='1')
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=fixed, env=env, stderr=subprocess.DEVNULL).decode().strip()
            git('init', '-q')
            fixture = fixed / owner.FIXTURE; fixture.parent.mkdir(parents=True); fixture.write_text('same')
            git('add', '.'); git('-c', 'user.name=Diagnostic Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'base')
            base = git('rev-parse', 'HEAD')
            git('-c', 'user.name=Diagnostic Test', '-c', 'user.email=test@example.invalid', 'commit', '--allow-empty', '-qm', 'baseline')
            baseline = root / 'baseline'; git('worktree', 'add', '-q', '--detach', str(baseline), 'HEAD')
            (fixed / 'unreviewed.txt').write_text('changed'); git('add', '.')
            git('-c', 'user.name=Diagnostic Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'unreviewed')
            native, tools = root / 'native', root / 'tools'; native.mkdir(); tools.mkdir()
            with patch.object(owner.sys, 'platform', 'linux'), self.assertRaisesRegex(WorkflowError, 'only-reviewed-fix'):
                owner.pair(baseline, fixed, native, tools, root / 'output', expected_base=base, expected_head=git('rev-parse', 'HEAD'))


if __name__ == '__main__':
    unittest.main()
