"""Source, refusal, and public-evidence controls for the paired diagnostic."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from tools import admit_dotnet_poll_prefetch_evidence as admission
from tools import dotnet_poll_prefetch_node as node
from tools import qualify_dotnet_poll_prefetch as qualification
from tools import run_dotnet_poll_prefetch_pair as owner
from tools.phase2_operator_process import WorkflowError
from tools.phase3_resource_identity import file_identity


class DotnetPollPrefetchTests(unittest.TestCase):
    def make_package_hash_pair(self, root):
        baseline, fixed, old_tools, new_tools = (root / name for name in ('baseline', 'fixed', 'old-tools', 'new-tools'))
        for checkout in (baseline, fixed):
            source = checkout / owner.PACKAGE_HASH_SOURCE; source.mkdir(parents=True)
            (source / 'PackageHash.csproj').write_bytes(b'fixed source')
        for tools in (old_tools, new_tools):
            source = tools / 'package-hash-source'; source.mkdir(parents=True)
            (source / 'PackageHash.csproj').write_bytes(b'fixed source')
            output = tools / 'package-hash'; output.mkdir()
            for name, data in (('PackageHash.dll', b'baseline assembly'), ('PackageHash.pdb', b'baseline symbols'),
                    ('PackageHash.deps.json', b'deps'), ('PackageHash.runtimeconfig.json', b'config'),
                    ('NuGet.Packaging.dll', b'fixed dependency')):
                (output / name).write_bytes(data)
            helper = tools / 'http-errors'; helper.mkdir()
            (helper / 'HttpErrors.dll').write_bytes(tools.name.encode())
        (new_tools / 'package-hash/PackageHash.dll').write_bytes(b'fixed assembly')
        (new_tools / 'package-hash/PackageHash.pdb').write_bytes(b'fixed symbols')
        return baseline, fixed, old_tools, new_tools

    def test_shared_package_hash_selects_only_generated_outputs_after_source_and_dependency_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            baseline, fixed, old_tools, new_tools = self.make_package_hash_pair(Path(directory))
            record = {}
            owner.share_package_hash(baseline, fixed, old_tools, new_tools, record)
            self.assertEqual(record['status'], 'passed')
            self.assertEqual(set(record['selectedBaselineOutputs']), {'PackageHash.dll', 'PackageHash.pdb'})
            self.assertNotEqual(record['before']['baseline'], record['before']['fixed'])
            self.assertEqual(record['after']['baseline'], record['after']['fixed'])
            self.assertEqual((new_tools / 'package-hash/PackageHash.dll').read_bytes(), b'baseline assembly')
            self.assertEqual((new_tools / 'package-hash/NuGet.Packaging.dll').read_bytes(), b'fixed dependency')
            self.assertEqual((new_tools / 'http-errors/HttpErrors.dll').read_bytes(), b'new-tools')
            self.assertEqual((old_tools / 'http-errors/HttpErrors.dll').read_bytes(), b'old-tools')
            record2 = {}
            owner.share_package_hash(baseline, fixed, old_tools, new_tools, record2)
            self.assertEqual(record2['selectedBaselineOutputs'], {})

    def test_shared_package_hash_refuses_source_dependency_and_output_drift_before_mutation(self):
        for fault in ('checkout-source', 'installed-source', 'dependency', 'extra', 'missing', 'excluded'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                baseline, fixed, old_tools, new_tools = self.make_package_hash_pair(Path(directory))
                if fault == 'checkout-source':
                    (fixed / owner.PACKAGE_HASH_SOURCE / 'PackageHash.csproj').write_bytes(b'changed')
                elif fault == 'installed-source':
                    (new_tools / 'package-hash-source/PackageHash.csproj').write_bytes(b'changed')
                elif fault == 'dependency':
                    (new_tools / 'package-hash/NuGet.Packaging.dll').write_bytes(b'changed')
                elif fault == 'extra':
                    (new_tools / 'package-hash/unreviewed.dll').write_bytes(b'changed')
                elif fault == 'missing':
                    (new_tools / 'package-hash/PackageHash.runtimeconfig.json').unlink()
                else:
                    (new_tools / 'package-hash/target').mkdir()
                with self.assertRaises(WorkflowError):
                    owner.share_package_hash(baseline, fixed, old_tools, new_tools, {})
                self.assertEqual((new_tools / 'package-hash/PackageHash.dll').read_bytes(), b'fixed assembly')
                self.assertEqual((new_tools / 'package-hash/PackageHash.pdb').read_bytes(), b'fixed symbols')

    def test_shared_package_hash_rejects_symlink_output_before_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            baseline, fixed, old_tools, new_tools = self.make_package_hash_pair(Path(directory))
            dependency = new_tools / 'package-hash/NuGet.Packaging.dll'
            dependency.unlink()
            try:
                dependency.symlink_to(old_tools / 'package-hash/NuGet.Packaging.dll')
            except OSError:
                self.skipTest('platform cannot create symlinks')
            with self.assertRaises((OSError, ValueError, WorkflowError)):
                owner.share_package_hash(baseline, fixed, old_tools, new_tools, {})
            self.assertEqual((new_tools / 'package-hash/PackageHash.dll').read_bytes(), b'fixed assembly')

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
        self.assertIn('tools/dotnet_task_runtime_fixture.py', workflow['on']['push']['paths'])
        self.assertEqual(workflow['permissions'], {'contents': 'read', 'actions': 'read'})
        self.assertEqual(workflow['jobs']['diagnostic']['timeout-minutes'], 70)
        commands = '\n'.join(step.get('run', '') for step in workflow['jobs']['diagnostic']['steps'])
        self.assertIn('3000s python3 -B tools/run_dotnet_poll_prefetch_pair.py', commands)
        self.assertIn('--baseline "$RUNNER_TEMP/dotnet-prefetch-baseline"', commands)
        self.assertIn('--fixed "$GITHUB_WORKSPACE"', commands)
        self.assertIn('--baseline-tools "$RUNNER_TEMP/dotnet-prefetch/tools-baseline"', commands)
        self.assertIn('--fixed-tools "$RUNNER_TEMP/dotnet-prefetch/tools-fixed"', commands)
        self.assertIn('dotnet-prefetch-baseline/tools/dotnet_capsule.py', commands)
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

    def test_imported_task_fixture_is_captured_and_changes_invalidate_materials(self):
        helper = 'tools/dotnet_task_runtime_fixture.py'
        self.assertEqual(qualification.MATERIALS.count(helper), 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in qualification.MATERIALS:
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('input:' + name, encoding='utf-8')
            recorded = qualification.source_materials(root)
            self.assertEqual(recorded[helper], file_identity(root / helper))
            (root / helper).write_text('changed', encoding='utf-8')
            current = qualification.source_materials(root)
            self.assertNotEqual(recorded, current)
            self.assertEqual({name for name in recorded if recorded[name] != current[name]}, {helper})
            (root / helper).unlink()
            with self.assertRaises(WorkflowError): qualification.source_materials(root)

    def test_each_installed_helper_must_match_its_own_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sdk = root / 'checkout/sdk/dotnet-guest/tools/http-errors'
            old = root / 'tools-baseline/http-errors-source'
            new = root / 'tools-fixed/http-errors-source'
            for path in (sdk, old, new):
                path.mkdir(parents=True)
            (sdk / 'AggregateTaskWait.cs').write_text('baseline', encoding='utf-8')
            (old / 'AggregateTaskWait.cs').write_text('baseline', encoding='utf-8')
            (new / 'AggregateTaskWait.cs').write_text('fixed', encoding='utf-8')
            identity = qualification.selected_helper_source(root / 'checkout', root / 'tools-baseline')
            self.assertTrue(identity['sha256'].startswith('sha256:'))
            with self.assertRaisesRegex(WorkflowError, 'source-must-match-checkout'):
                qualification.selected_helper_source(root / 'checkout', root / 'tools-fixed')
            (sdk / 'AggregateTaskWait.cs').write_text('fixed', encoding='utf-8')
            self.assertNotEqual(identity, qualification.selected_helper_source(root / 'checkout', root / 'tools-fixed'))

    def test_shared_installation_fingerprints_refuse_different_adapter_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in ('baseline', 'fixed'):
                for name in qualification.COMMON_INSTALLATION:
                    path = root / folder / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('same:' + name, encoding='utf-8')
            before = qualification.common_installation(root / 'baseline')
            self.assertEqual(before, qualification.common_installation(root / 'fixed'))
            dependency = root / 'fixed/package-hash/NuGet.Packaging.dll'
            dependency.write_bytes(b'changed dependency')
            self.assertNotEqual(before, qualification.common_installation(root / 'fixed'))
            dependency.unlink()
            target = root / 'fixed' / 'managed-activation-runtime.wasm'
            target.write_text('changed', encoding='utf-8')
            self.assertNotEqual(before, qualification.common_installation(root / 'fixed'))

    def test_variant_binds_source_materials_before_attempting_fixture_capture(self):
        from tools import wasmtime_48_0_8_678b_native_products as products
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); root, native, tools, output = (base / name for name in
                ('checkout', 'native', 'tools', 'output'))
            root.mkdir(); native.mkdir(); tools.mkdir()
            for name in qualification.MATERIALS:
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(('source:' + name).encode())
            for name, data in (('runtime-inputs.json', b'runtime'), ('INSTALL-COMPLETE.json', b'{}'),
                    ('wasi-sdk.json', b'{}'), ('http-errors/HttpErrors.dll', b'helper')):
                path = tools / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
            binaries = {}
            for name in ('latent', 'latentd', 'package', 'capsule_contracts', 'capsule_authoring'):
                path = native / name; path.write_bytes(b'product'); binaries[name] = path
            head = 'a' * 40; native_identity = {'sha256': 'same'}
            with ExitStack() as stack:
                for target, name, replacement in (
                        (qualification, 'ROOT', root), (qualification.sys, 'platform', 'linux'),
                        (qualification.subprocess, 'check_output', unittest.mock.Mock(side_effect=[head.encode(), b''])),
                        (products, 'verify_prepared', unittest.mock.Mock(return_value={'products': 'verified'})),
                        (products, 'native_products', unittest.mock.Mock(return_value=binaries)),
                        (qualification, 'source_identity', unittest.mock.Mock(return_value=native_identity)),
                        (qualification, 'git_source_identity', unittest.mock.Mock(return_value=native_identity)),
                        (qualification, 'current_materials', unittest.mock.Mock(return_value={'native': 'material'})),
                        (qualification, 'runtime_inputs', unittest.mock.Mock(return_value=b'runtime')),
                        (qualification, 'common_installation', unittest.mock.Mock(return_value={'common': 'same'})),
                        (qualification, 'selected_helper_source', unittest.mock.Mock(return_value={'source': 'same'})),
                        (qualification.fixture, 'prepare', unittest.mock.Mock(side_effect=RuntimeError('stop after source binding')))):
                    stack.enter_context(patch.object(target, name, replacement))
                with self.assertRaisesRegex(RuntimeError, 'stop after source binding'):
                    qualification.qualify(native, tools, output, variant='baseline', expected_head=head)
            failed = json.loads((output / 'FAILED.json').read_text())
            self.assertEqual(failed['stage'], 'normal-capture-of-diagnostic-fixture')
            self.assertFalse(failed['nativeAotCompilationAttempted'])
            self.assertEqual(failed['materials'][qualification.FIXTURE], file_identity(root / qualification.FIXTURE))

    def test_both_installation_receipts_are_public_but_private_inputs_are_not(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for variant in ('baseline', 'fixed'):
                tools = root / ('tools-' + variant)
                tools.mkdir()
                (tools / 'INSTALL-COMPLETE.json').write_text('{}', encoding='utf-8')
                (tools / 'private-key.txt').write_text('not-public', encoding='utf-8')
            result = admission.admit(root)
            self.assertEqual(set(result['files']), {
                'tools-baseline/INSTALL-COMPLETE.json', 'tools-fixed/INSTALL-COMPLETE.json'})
            self.assertFalse((root / 'public/tools-baseline/private-key.txt').exists())

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
            native, baseline_tools, fixed_tools = root / 'native', root / 'tools-baseline', root / 'tools-fixed'
            native.mkdir(); baseline_tools.mkdir(); fixed_tools.mkdir()
            with patch.object(owner.sys, 'platform', 'linux'), patch.object(owner, 'common_installation', return_value={}), \
                    patch.object(owner, 'share_package_hash'), \
                    patch.object(owner, 'Commands') as commands:
                commands.return_value.run.side_effect = RuntimeError('incomplete owner')
                commands.return_value.records = []
                with self.assertRaisesRegex(WorkflowError, 'baseline-cleanup-required'):
                    owner.pair(baseline, fixed, native, baseline_tools, fixed_tools, root / 'output',
                        expected_base=base, expected_head=git('rev-parse', 'HEAD'))
                self.assertEqual(commands.return_value.run.call_count, 1)
            with patch.object(owner.sys, 'platform', 'linux'), \
                    patch.object(owner, 'common_installation', side_effect=[{'adapter': 'a'}, {'adapter': 'b'}]), \
                    patch.object(owner, 'Commands') as commands:
                commands.return_value.records = []
                with self.assertRaisesRegex(WorkflowError, 'shared-installation-drift'):
                    owner.pair(baseline, fixed, native, baseline_tools, fixed_tools, root / 'output-shared-refusal',
                        expected_base=base, expected_head=git('rev-parse', 'HEAD'))
                commands.return_value.run.assert_not_called()
                failure = json.loads((root / 'output-shared-refusal/FAILED.json').read_text())
                self.assertEqual(failure['attempts'], [])

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
            native, baseline_tools, fixed_tools = root / 'native', root / 'tools-baseline', root / 'tools-fixed'
            native.mkdir(); baseline_tools.mkdir(); fixed_tools.mkdir()
            with patch.object(owner.sys, 'platform', 'linux'), self.assertRaisesRegex(WorkflowError, 'only-reviewed-fix'):
                owner.pair(baseline, fixed, native, baseline_tools, fixed_tools, root / 'output', expected_base=base, expected_head=git('rev-parse', 'HEAD'))


if __name__ == '__main__':
    unittest.main()
