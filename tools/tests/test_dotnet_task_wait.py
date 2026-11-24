"""Private CoreLib selection/binding fences; real execution is a native gate."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from tools import dotnet_task_runtime_context as event_context
from tools import dotnet_task_runtime_fixture as task_fixture
from tools import dotnet_task_runtime_probe as task_probe
from tools.phase2_operator_process import WorkflowError
from tools.qualify_dotnet_task_runtime import HELPERS, require_reset_notification_receipt
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
        for missing in (runtime.CLOCK, runtime.ACTIVATION):
            imports = [name for name in self.declared if name != missing]
            self.assertIsNone(task_wait.prepare(Path('missing'), Path('missing'), Path('missing'), Path('missing'),
                imports, self.bridge, self.project, self.output, self.evidence,
                lambda *args: self.fail('undeclared-rewrite')))
        self.assertFalse(task_wait.selected(self.declared, None))
        self.assertEqual(self.stages, [])
        self.assertEqual(list(self.output.iterdir()), [])

    def test_clock_and_activation_async_root_rewrites_without_http_authority(self):
        self.declared = [runtime.CLOCK, runtime.ACTIVATION]
        port = self.prepare()
        self.references(port)
        result = port.finish(self.project, self.evidence)
        self.assertEqual(result['selection']['requiredDeclarations'], sorted(self.declared))
        self.assertNotIn(runtime.HTTP, result['selection']['requiredDeclarations'])
        self.assertEqual(self.stages, ['task-wait-rewrite'])
        self.assertEqual(runtime.select(self.declared, ['wasi:io/poll@0.2.6']), 'runtime')
        self.assertEqual(result['completion'], 'actual-task-only')
        self.assertFalse(result['defaultClientComponentQualified'])

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

class TaskRuntimeResetWitnessTests(unittest.TestCase):
    def test_runtime_witnesses_extend_only_the_selected_ordinary_fixture(self):
        from tools import dotnet_task_runtime_fixture as fixture
        from tools.phase2_operator_process import WorkflowError
        legacy, legacy_cases = fixture.selected_fixture()
        source, cases = fixture.selected_fixture(reset_notification=True)
        self.assertEqual(legacy_cases, fixture.CASES)
        self.assertEqual(cases, legacy_cases + (fixture.EVENT_WAIT_MODE,)
                         + fixture.event_context.CASES + fixture.TIMER_CHANGE_CASES
                         + (fixture.RESET_NOTIFICATION_MODE,))
        self.assertEqual(source.count(fixture.RESET_NOTIFICATION_CASE), 1)
        self.assertEqual(source.count(fixture.EVENT_WAIT_CASE), 1)
        self.assertEqual(source.replace(fixture.RESET_NOTIFICATION_CASE, '').replace(fixture.EVENT_WAIT_CASE, '')
                         .replace(fixture.event_context.SOURCE, '').replace(fixture.TIMER_CHANGE_SOURCE, ''), legacy)
        self.assertNotIn('case "reset-notification-refusal"', legacy)
        self.assertNotIn('case "manual-reset-sibling"', legacy)
        for mode in fixture.TIMER_CHANGE_CASES:
            self.assertNotIn(f'case "{mode}"', legacy)
        with self.assertRaises(WorkflowError):
            fixture.selected_fixture(reset_notification=1)
        with self.assertRaises(WorkflowError):
            fixture.selected_fixture(True, reset_notification=True)

    def test_runtime_selector_adds_the_selected_bounded_probes(self):
        from tools import dotnet_task_runtime_fixture as fixture, dotnet_task_runtime_probe as probe
        from tools.phase2_operator_process import WorkflowError
        from tools.run_rust_capsule_workflow import run
        for keywords in ({'dotnet_task_reset_witness': True},
                         {'dotnet_task_runtime': True, 'dotnet_task_reset_witness': 1},
                         {'dotnet_task_runtime': 1, 'dotnet_task_reset_witness': True}):
            with self.subTest(keywords=keywords), self.assertRaises(WorkflowError):
                run(Path('missing'), Path('missing'), Path('missing'), Path('missing'), **keywords)
        target = {'budget': {'cpuFuel': 1000, 'memoryBytes': 10000}}
        row = {'processReaped': True, 'response': {'outcomeKnown': True, 'data': {
            'consumption': {'cpuFuel': '17', 'peakMemoryBytes': '100', 'outboundRequests': '0',
                            'logBytes': '0', 'effectCount': '0'}}}}
        result = {'invocations': [], 'providerIdle': [], 'samples': []}
        with patch('tools.rust_capsule_node.call', return_value=row) as calls, \
                patch('tools.rust_capsule_node.assert_value') as values, \
                patch('tools.rust_capsule_node.provider_idle', return_value={}), \
                patch('tools.rust_capsule_node.sample', side_effect=lambda *args: {'phase': args[2]}):
            with self.assertRaises(WorkflowError):
                probe.probe(None, target, None, result, 0, reset_notification=1)
            calls.assert_not_called()
            probe.probe(None, target, None, result, 0, reset_notification=True)
        self.assertEqual(calls.call_count, len(fixture.QUALIFICATION_CASES))
        self.assertEqual([row['mode'] for row in result['dotnetTaskRuntime']['cases']],
                         list(fixture.QUALIFICATION_CASES))
        self.assertEqual(values.call_args_list[-1].args[2],
                         [{'ok': fixture.expected(fixture.RESET_NOTIFICATION_MODE)}])
        self.assertEqual(values.call_args_list[fixture.QUALIFICATION_CASES.index(fixture.EVENT_WAIT_MODE)].args[2],
                         [{'ok': fixture.expected(fixture.EVENT_WAIT_MODE)}])
        self.assertEqual(result['samples'][-1]['phase'],
                         'dotnet-ordinary-tasks-reset-notification-refusal-retired')

    def test_reset_receipt_requires_the_exact_observed_case_and_result(self):
        from tools import dotnet_task_runtime_fixture as fixture
        from tools.phase2_operator_process import WorkflowError
        from tools.qualify_dotnet_task_runtime import require_reset_notification_receipt
        library, _ = fixture.selected_fixture(reset_notification=True)
        captured = {'cases': list(fixture.QUALIFICATION_CASES), 'originalFiles': {'Library.cs': digest(library.encode('utf-8'))}}
        invocation = {'processReaped': True, 'exitCode': 0, 'response': {'outcomeKnown': True}}
        observed = {'dotnetTaskRuntime': {'cases': [
            {'mode': mode, 'invocation': {**copy.deepcopy(invocation), 'decoded': [{'ok': fixture.expected(mode)}]},
             'retirement': {'phase': 'dotnet-ordinary-tasks-' + mode + '-retired'}}
            for mode in fixture.QUALIFICATION_CASES]}}
        require_reset_notification_receipt(captured, observed)
        for mode in fixture.TIMER_CHANGE_CASES:
            index = fixture.QUALIFICATION_CASES.index(mode)
            for field in ('changed', 'pending', 'callbacks', 'drained'):
                wrong = copy.deepcopy(observed)
                value = wrong['dotnetTaskRuntime']['cases'][index]['invocation']['decoded'][0]
                value['ok'] = value['ok'].replace(field+'=', field+'=wrong-')
                with self.subTest(mode=mode, field=field), self.assertRaises(WorkflowError):
                    require_reset_notification_receipt(captured, wrong)
        wrong_event = copy.deepcopy(observed)
        wrong_event['dotnetTaskRuntime']['cases'][fixture.QUALIFICATION_CASES.index(fixture.EVENT_WAIT_MODE)]['invocation']['decoded'] = [{'ok': 'wrong'}]
        with self.assertRaises(WorkflowError): require_reset_notification_receipt(captured, wrong_event)
        for mutation in ('captured', 'source', 'missing', 'duplicate', 'result', 'exit', 'unknown', 'unreaped', 'retirement'):
            inputs, receipt = copy.deepcopy(captured), copy.deepcopy(observed)
            rows = receipt['dotnetTaskRuntime']['cases']
            if mutation == 'captured': inputs['cases'].pop()
            elif mutation == 'source': inputs['originalFiles']['Library.cs'] = digest(b'unrelated')
            elif mutation == 'missing': rows.pop()
            elif mutation == 'duplicate': rows[-1]['mode'] = rows[-2]['mode']
            elif mutation == 'result': rows[-1]['invocation']['decoded'] = [{'ok': 'fabricated'}]
            elif mutation == 'exit': rows[-1]['invocation']['exitCode'] = 1
            elif mutation == 'unknown': rows[-1]['invocation']['response']['outcomeKnown'] = False
            elif mutation == 'unreaped': rows[-1]['invocation']['processReaped'] = False
            else: rows[-1].pop('retirement')
            with self.subTest(mutation=mutation), self.assertRaises(WorkflowError):
                require_reset_notification_receipt(inputs, receipt)


EVENT_CONTEXT_EXPECTED = {
    'manual-reset-context': 'ordinary-tasks:manual-reset-context|pending=1|same-thread=1|setter=1'
        '|notifications=none|worker=0|caller=7|flow-suppressed=0|fresh=1',
    'manual-reset-suppressed-context': 'ordinary-tasks:manual-reset-suppressed-context|pending=1|same-thread=1|setter=1'
        '|notifications=none|worker=0|caller=7|flow-suppressed=1|fresh=1',
    'manual-reset-captured-context': 'ordinary-tasks:manual-reset-captured-context|pending=1|same-thread=1|setter=1'
        '|notifications=0>13,14>0|worker=13|caller=7|flow-suppressed=0|fresh=1',
}


def _context_invocation(mode):
    return {'processReaped': True, 'exitCode': 0,
        'decoded': [{'ok': EVENT_CONTEXT_EXPECTED[mode] if mode in EVENT_CONTEXT_EXPECTED else task_fixture.expected(mode)}],
        'response': {'outcomeKnown': True, 'data': {'consumption': {
            'cpuFuel': '17', 'peakMemoryBytes': '100', 'outboundRequests': '0',
            'logBytes': '0', 'effectCount': '0'}}}}


class EventContextWitnessTests(unittest.TestCase):
    def evidence(self):
        source, cases = task_fixture.selected_fixture(reset_notification=True)
        captured = {'cases': list(cases), 'originalFiles': {'Library.cs': digest(source.encode('utf-8'))}}
        observed = {'dotnetTaskRuntime': {'cases': [
            {'mode': mode, 'invocation': _context_invocation(mode),
             'retirement': {'phase': 'dotnet-ordinary-tasks-' + mode + '-retired'}}
            for mode in cases]}}
        return source, captured, observed

    def test_context_witnesses_are_selected_and_source_bound_without_changing_the_baseline(self):
        source, captured, observed = self.evidence()
        legacy, legacy_cases = task_fixture.selected_fixture()
        self.assertEqual(legacy_cases, task_fixture.CASES)
        self.assertEqual(source.count(event_context.SOURCE), 1)
        self.assertNotIn(event_context.SOURCE, legacy)
        self.assertIn('tools/dotnet_task_runtime_context.py', HELPERS)
        for mode, expected in EVENT_CONTEXT_EXPECTED.items():
            with self.subTest(mode=mode):
                self.assertIn(mode, captured['cases'])
                self.assertNotIn(mode, legacy_cases)
                self.assertEqual(event_context.expected(mode), expected)
                self.assertEqual(task_fixture.expected(mode), expected)
        require_reset_notification_receipt(captured, observed)
        # A new claimed result may not qualify a source with the observer removed.
        changed = source.replace('notifications++;', '/* observer removed */')
        self.assertNotEqual(changed, source)
        captured['originalFiles']['Library.cs'] = digest(changed.encode('utf-8'))
        with self.assertRaisesRegex(WorkflowError, 'exact-case-inventory'):
            require_reset_notification_receipt(captured, observed)
        with self.assertRaises(WorkflowError):
            event_context.expected('unknown')

    def test_every_context_receipt_requires_its_exact_trace_and_retirement(self):
        _, captured, observed = self.evidence()
        for mode, expected in EVENT_CONTEXT_EXPECTED.items():
            for mutation in ('missing', 'duplicate', 'legacy', 'notification', 'worker', 'caller',
                             'flow', 'eager', 'thread', 'exception', 'unreaped', 'unknown', 'exit', 'retirement'):
                wrong = copy.deepcopy(observed)
                rows = wrong['dotnetTaskRuntime']['cases']
                index = task_fixture.QUALIFICATION_CASES.index(mode)
                row = rows[index]
                value = row['invocation']
                if mutation == 'missing': rows.pop(index)
                elif mutation == 'duplicate': rows.insert(index, copy.deepcopy(row))
                elif mutation == 'legacy': value['decoded'] = [{'ok': 'ordinary-tasks:' + mode + '|fresh=1'}]
                elif mutation in ('notification', 'worker', 'caller', 'flow', 'eager', 'thread'):
                    key = {'notification': 'notifications', 'worker': 'worker', 'caller': 'caller',
                           'flow': 'flow-suppressed', 'eager': 'pending', 'thread': 'same-thread'}[mutation]
                    pieces = expected.split('|')
                    # Nonempty but wrong evidence must not be accepted as presence.
                    pieces = [key + '=wrong' if part.startswith(key + '=') else part for part in pieces]
                    value['decoded'] = [{'ok': '|'.join(pieces)}]
                elif mutation == 'exception': value['decoded'] = [{'err': 'ordinary-task-failure:event-context-notifications:invalid-operation'}]
                elif mutation == 'unreaped': value['processReaped'] = False
                elif mutation == 'unknown': value['response']['outcomeKnown'] = False
                elif mutation == 'exit': value['exitCode'] = 4
                else: row['retirement']['phase'] += '-wrong'
                with self.subTest(mode=mode, mutation=mutation), self.assertRaises(WorkflowError):
                    require_reset_notification_receipt(captured, wrong)

    def run_probe(self, wrong_mode=None):
        result = {'invocations': [], 'providerIdle': [], 'samples': []}
        called = []
        def call(client, target, template, function, arguments, label):
            mode = arguments[0].removeprefix('task:')
            called.append(mode)
            value = _context_invocation(mode)
            if mode == wrong_mode:
                # This is the old defect: a waiter transition appears in the trace.
                value['decoded'][0]['ok'] = value['decoded'][0]['ok'].replace(
                    '|notifications=', '|notifications=7>0,0>7,')
            return value
        with patch('tools.rust_capsule_node.call', side_effect=call), \
                patch('tools.rust_capsule_node.provider_idle', return_value={}), \
                patch('tools.rust_capsule_node.sample', side_effect=lambda *args: {'phase': args[2]}), \
                patch('tools.capsule_invocation_diagnostics.capture'):
            # Keep the actual assert_value and probe consumption/retirement gates.
            try:
                task_probe.probe(None, {'budget': {'cpuFuel': 1000, 'memoryBytes': 10000}},
                            None, result, 0, reset_notification=True)
            except WorkflowError:
                if wrong_mode is None:
                    raise
                self.assertNotIn('dotnetTaskRuntime', result)
                self.assertEqual(called[-1], wrong_mode)
                self.assertEqual(len(result['samples']), len(called) - 1)
                return result, called
        self.assertIsNone(wrong_mode, 'wrong context result unexpectedly qualified')
        return result, called

    def test_node_probe_requires_the_context_cases_and_keeps_full_qualification_false(self):
        result, called = self.run_probe()
        self.assertEqual(called, list(task_fixture.QUALIFICATION_CASES))
        self.assertFalse(result['dotnetTaskRuntime']['fullRuntimeQualification'])
        self.assertFalse(result['dotnetTaskRuntime']['applicationSchedulerReplacement'])
        _, captured, _ = self.evidence()
        require_reset_notification_receipt(captured, result)

    def test_real_result_gate_stops_each_bad_context_case_before_retirement_or_success(self):
        for mode in EVENT_CONTEXT_EXPECTED:
            with self.subTest(mode=mode):
                self.run_probe(mode)


if __name__ == '__main__':
    unittest.main()
