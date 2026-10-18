"""Private CoreLib selection/binding fences; real execution is a native gate."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from tools.dotnet_guest import async_exports, http_errors, runtime, task_wait
from tools.rust_capsule_project import ROOT, digest, write_json


class TaskWaitPortTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='lsf-task-wait-control-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sdk, self.tools, self.packages, self.project, self.output, self.evidence = [
            self.root / name for name in ('sdk', 'tools', 'packages', 'project', 'output', 'evidence')]
        for directory in (self.tools, self.packages, self.project, self.output, self.evidence):
            directory.mkdir()
        shutil.copytree(ROOT / 'sdk/dotnet-guest/tools/http-errors', self.sdk / 'tools/http-errors')
        self.project.joinpath('Capsule.csproj').write_text('<Project />')
        self.original = task_wait.source_path(self.packages)
        self.original.parent.mkdir(parents=True)
        self.original.write_bytes(b'original-control')
        self.receipt = json.loads((ROOT / 'sdk/dotnet-guest/tests/fixtures/task-wait-rewrite.json').read_text())
        # Mocked tool output only: the historical c41 receipt above stays intact.
        self.receipt.update({'generatedHelperCount': 9, 'unchangedOriginalMethods': 44741,
            'timerDriver': 'TimerQueue.SetNextTimer-only', 'timerDriverIdle': 'Timer.ActiveCount==0',
            'timerDriverCancellation': 'original-CancellationTokenSource-CancelAndDispose',
            'timerDriverIdentity': 'original-task-reference-and-epoch',
            'timerDriverCallbacks': 'original-queued-user-callbacks-preserved',
            'timerDriverScheduledToFire': 'untouched', 'timerDriverCacheCleanup': False,
            'timerDriverModifiedOriginalMethods': 3,
            'timerDriverRegistrationContext': 'no-new-capture-original-flow-restored',
            'zeroCacheLifetime': 'CheckPollables-original-Poll-call-only', 'zeroCacheDetach': 'before-original-Poll',
            'zeroCacheDispose': 'original-owned-Pollable-finally', 'zeroCacheForeignHolders': 'untouched',
            'zeroCacheModifiedOriginalMethods': 1, 'zeroCacheOriginalBodies': {
                'System.Void System.Threading.WasiEventLoop::CheckPollables(System.Object)': 'd' * 64},
            'timerDriverOriginalBodies': {name: 'e' * 64 for name in (
                'System.Void System.Threading.TimerQueue::SetNextTimer(System.Int64,System.Int64)',
                'System.Void System.Threading.TimerQueue::TimerHandler(System.Object)',
                'System.Void System.Threading.TimerQueue::DeleteTimer(System.Threading.TimerQueueTimer)')}})
        self.bridge = {'profile': async_exports.PROFILE, 'exports': 1}
        self.declared = [runtime.CLOCK, runtime.HTTP, runtime.ACTIVATION]
        self.stages = []
        self.addCleanup(patch.stopall)
        patch.object(http_errors, 'verify_installed', return_value={'digest': digest(b'controlled-tool'), 'size': 15}).start()
        def original(path):
            if path.read_bytes() != b'original-control':
                raise ValueError('changed-controlled-original')
            return {'digest': task_wait.SOURCE, 'size': 5694976}
        patch.object(task_wait, 'original', side_effect=original).start()

    def run_tool(self, stage, *arguments):
        self.stages.append(stage)
        self.assertEqual(arguments[2], '--task-wait')
        assembly, receipt = arguments[-2:]
        assembly.write_bytes(b'derived-control')
        result = copy.deepcopy(self.receipt)
        result['outputDigest'] = digest(b'derived-control')
        write_json(receipt, result)

    def prepare(self, **keywords):
        return task_wait.prepare(self.sdk, self.tools, self.packages, self.root / 'dotnet', self.declared,
            self.bridge, self.project, self.output, self.evidence, self.run_tool, **keywords)

    def references(self, port):
        port.references.write_text(str(port.assembly) + '\n')
        (self.project / 'obj').mkdir()
        (self.project / 'obj/compiler.rsp').write_text('-r:' + str(port.assembly) + '\n')

    def test_missing_declaration_or_async_root_never_reads_tools_or_starts_rewrite(self):
        for missing in self.declared:
            imports = [name for name in self.declared if name != missing]
            self.assertIsNone(task_wait.prepare(Path('missing'), Path('missing'), Path('missing'), Path('missing'),
                imports, self.bridge, self.project, self.output, self.evidence,
                lambda *args: self.fail('undeclared-rewrite')))
        self.assertFalse(task_wait.selected(self.declared, None))
        self.assertEqual(self.stages, [])
        self.assertEqual(list(self.output.iterdir()), [])

    def test_wrong_bridge_and_noninteger_or_excess_export_counts_fail_before_tool(self):
        for bridge in ({'profile': 'other', 'exports': 1}, {'profile': async_exports.PROFILE, 'exports': True},
                       {'profile': async_exports.PROFILE, 'exports': 0}, {'profile': async_exports.PROFILE, 'exports': 65}):
            with self.assertRaisesRegex(ValueError, 'authenticated-async-root'):
                task_wait.selected(self.declared, bridge)
        self.assertEqual(self.stages, [])

    def test_derived_assembly_and_targets_are_protected_before_project_import(self):
        observed = []
        def protect(*paths):
            self.assertEqual(self.stages, ['task-wait-rewrite'])
            self.assertNotIn('LsfTaskWaitAssembly', self.project.joinpath('Capsule.csproj').read_text())
            self.assertTrue(all(path.is_file() for path in paths))
            observed.extend(paths)
        port = self.prepare(protect_inputs=protect)
        self.assertEqual(observed, [port.assembly, port.targets])
        self.references(port)
        record = port.finish(self.project, self.evidence)
        self.assertIsNotNone(record['nativeAotReferenceBinding'])
        self.assertFalse(record['defaultClientComponentQualified'])

    def test_wrong_original_reference_cannot_survive_native_binding(self):
        port = self.prepare()
        self.references(port)
        port.references.write_text(str(port.assembly) + '\n' + str(self.original) + '\n')
        with self.assertRaisesRegex(ValueError, 'reference-binding'):
            port.finish(self.project, self.evidence)

    def test_duplicate_native_response_files_cannot_claim_a_single_binding(self):
        port = self.prepare()
        self.references(port)
        shutil.copyfile(self.project / 'obj/compiler.rsp', self.project / 'obj/duplicate.rsp')
        with self.assertRaisesRegex(ValueError, 'reference-not-observed'):
            port.finish(self.project, self.evidence)

    def test_original_source_drift_is_rejected_after_rewrite(self):
        port = self.prepare()
        self.original.write_bytes(b'changed-original')
        with self.assertRaisesRegex(ValueError, 'changed-controlled-original'):
            port.recheck()

    def test_captured_tool_source_drift_is_rejected_after_rewrite(self):
        port = self.prepare()
        with (self.sdk / 'tools/http-errors/TaskWait.cs').open('ab') as stream:
            stream.write(b'\n// changed\n')
        with self.assertRaisesRegex(ValueError, 'source-or-target-changed'):
            port.recheck()

    def test_target_drift_is_rejected_after_rewrite(self):
        port = self.prepare()
        with port.targets.open('ab') as stream:
            stream.write(b'\n<!-- changed -->\n')
        with self.assertRaisesRegex(ValueError, 'source-or-target-changed'):
            port.recheck()

    def test_equal_size_derived_or_retained_assembly_mutation_is_rejected(self):
        port = self.prepare()
        expected = port.assembly.read_bytes()
        for path in (port.assembly, port.retained):
            changed = bytearray(expected)
            changed[-1] ^= 1
            path.write_bytes(changed)
            with self.assertRaisesRegex(ValueError, 'derived-CoreLib-changed'):
                port.recheck()
            path.write_bytes(expected)

    def test_receipt_cannot_promote_completion_or_weaken_original_method_checks(self):
        for key, value in (('completion', 'synthetic'), ('defaultClientComponentQualified', True),
                           ('maximumNestedWaits', 33), ('completeOriginalWaitRemainderPreserved', False),
                           ('originalDispatchBodyDigest', digest(b'changed')), ('unchangedOriginalMethods', 0)):
            changed = {**self.receipt, key: value}
            with self.assertRaisesRegex(ValueError, 'rewrite-receipt'):
                task_wait.validate_receipt(changed)

    def test_receipt_cannot_drop_real_context_notifications_or_use_capture_only(self):
        for key, value in (('callerContexts', 'Capture-only'), ('contextNotifications', 'none'),
                           ('generatedHelperCount', 1), ('contextCallback', 'outside-assembly'),
                           ('originalContextBodyDigest', digest(b'changed')),
                           ('originalContextRestoreBodyDigest', digest(b'changed'))):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'rewrite-receipt'):
                task_wait.validate_receipt({**self.receipt, key: value})


    def test_historical_rewrite_receipt_cannot_claim_idle_driver_repair(self):
        old = json.loads((ROOT / 'sdk/dotnet-guest/tests/fixtures/task-wait-rewrite.json').read_text())
        with self.assertRaisesRegex(ValueError, 'rewrite-receipt'):
            task_wait.validate_receipt(old)
        task_wait.validate_receipt(self.receipt)

    def test_idle_driver_receipt_cannot_claim_live_timer_or_foreign_holder_cancellation(self):
        for key, value in (('timerDriver', 'all-pollables'), ('timerDriverIdle', 'root-return'),
                           ('timerDriverIdentity', 'epoch-only'), ('timerDriverCallbacks', 'cleared'),
                           ('timerDriverScheduledToFire', 'cleared'), ('timerDriverCacheCleanup', True),
                           ('timerDriverRegistrationContext', 'captured-user-context'),
                           ('timerDriverModifiedOriginalMethods', 4), ('zeroCacheLifetime', 'root-return'),
                           ('zeroCacheDetach', 'after-Poll'), ('zeroCacheDispose', 'clear-host-counts'),
                           ('zeroCacheForeignHolders', 'cancelled'), ('zeroCacheModifiedOriginalMethods', 2),
                           ('generatedHelperCount', 8)):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'rewrite-receipt'):
                task_wait.validate_receipt({**self.receipt, key: value})

    def test_idle_driver_original_method_identity_set_is_closed_and_digest_shaped(self):
        for key in ('timerDriverOriginalBodies', 'zeroCacheOriginalBodies'):
            bodies = self.receipt[key]
            for changed in (None, [], {}, {**bodies, 'foreign': 'e' * 64},
                            {**bodies, next(iter(bodies)): 'not-a-digest'}):
                with self.subTest(key=key, bodies=changed), self.assertRaisesRegex(ValueError, 'rewrite-receipt'):
                    task_wait.validate_receipt({**self.receipt, key: changed})

    def test_new_idle_driver_source_is_in_the_actual_captured_tool_fence(self):
        port = self.prepare()
        with (self.sdk / 'tools/http-errors/IdleTimerDriver.cs').open('ab') as stream:
            stream.write(b'\n// changed idle-driver control\n')
        with self.assertRaisesRegex(ValueError, 'source-or-target-changed'):
            port.recheck()


if __name__ == '__main__':
    unittest.main()
