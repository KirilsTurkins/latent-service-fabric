"""Current managed Task final-binding and signing-order controls; no guest execution."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.dotnet_guest import runtime, task_wait
from tools.rust_capsule_project import ROOT, write_json
from tools.tests import test_dotnet_task_wait as controls


def current_port():
    from tools.dotnet_guest import aggregate_task_wait, managed_work
    port = json.loads((ROOT / 'sdk/dotnet-guest/tests/fixtures/aggregate-task-wait-v2-controlled.json').read_bytes())
    port.update(profile=task_wait.PROFILE,
        managedAcceptedWork=copy.deepcopy(managed_work.INLINE_PRIMARY_REWRITE_RECEIPT),
        aggregateTaskWait=copy.deepcopy(aggregate_task_wait.PREFETCH_POLL_EXPECTED),
        generatedHelperCount=113, unchangedOriginalMethods=44706,
        finiteWaitObservation=task_wait.FINITE_OBSERVATION,
        selection={'requiredDeclarations': sorted((runtime.CLOCK, runtime.ACTIVATION, runtime.WALL, runtime.RANDOM))},
        nativeAotReferenceBinding={'responseFiles': [{'controlled': 'no-native-execution'}]})
    return port


class TaskRuntimeFinalBindingTests(unittest.TestCase):
    """Receipt and orchestration controls, not NativeAOT or signed execution."""

    def test_current_final_binding_uses_the_shared_receipt_and_rejects_downgrades(self):
        from tools.dotnet_guest import aggregate_task_wait
        from tools.phase2_operator_process import WorkflowError
        from tools.qualify_dotnet_task_runtime import require_current_task_wait_binding
        current = current_port()
        before = copy.deepcopy(current)
        require_current_task_wait_binding(current)
        for mutation in ('v6', 'body', 'helpers', 'profile', 'authority', 'selection-type',
                         'missing-native', 'response-type', 'missing-response', 'duplicate-response'):
            wrong = copy.deepcopy(current)
            if mutation == 'v6':
                wrong['aggregateTaskWait'] = copy.deepcopy(aggregate_task_wait.EVENT_WAIT_EXPECTED)
                wrong['generatedHelperCount'] = 109
            elif mutation == 'body':
                bodies = wrong['aggregateTaskWait']['rewrittenBodies']
                bodies[next(name for name in bodies if 'LsfAggregateEventContext' in name)] = '0' * 64
            elif mutation == 'helpers': wrong['generatedHelperCount'] = 109
            elif mutation == 'profile': wrong['profile'] = 'unrelated'
            elif mutation == 'authority': wrong['selection']['requiredDeclarations'].remove(runtime.ACTIVATION)
            elif mutation == 'selection-type': wrong['selection'] = []
            elif mutation == 'missing-native': del wrong['nativeAotReferenceBinding']
            elif mutation == 'response-type': wrong['nativeAotReferenceBinding']['responseFiles'] = {'0': {}}
            elif mutation == 'missing-response': wrong['nativeAotReferenceBinding']['responseFiles'] = []
            else: wrong['nativeAotReferenceBinding']['responseFiles'] *= 2
            with self.subTest(mutation=mutation), self.assertRaises((ValueError, WorkflowError)):
                require_current_task_wait_binding(wrong)
        # A valid nonaggregate receipt is still not proof of managed event waits.
        from tools.tests.test_dotnet_finite_task_wait import FINITE
        control = controls.TaskWaitPortTests(); control.setUp(); self.addCleanup(control.doCleanups)
        finite = {**control.receipt, **FINITE, 'profile': current['profile'],
                  'selection': current['selection'], 'nativeAotReferenceBinding': current['nativeAotReferenceBinding']}
        task_wait.validate_current_receipt({**control.receipt, **FINITE}, finite=True, require_finite_observation=True)
        with self.assertRaisesRegex(WorkflowError, 'final-corelib-binding'):
            require_current_task_wait_binding(finite)
        self.assertEqual(current, before)

    def test_qualifier_reaches_signing_only_after_current_final_binding(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from tools import qualify_dotnet_task_runtime as qualification
        from tools.phase2_operator_process import WorkflowError
        class BeforeSigning(Exception):
            pass
        for accepted in (True, False):
            with self.subTest(accepted=accepted), tempfile.TemporaryDirectory() as directory:
                parent = Path(directory)
                source = parent / 'source'; source.mkdir()
                (source / 'control.py').write_text('# orchestration input only\n')
                application = parent / 'application'; application.mkdir()
                (application / 'source.txt').write_text('captured source double')
                output = parent / 'output'
                port = current_port()
                if not accepted: port['nativeAotReferenceBinding']['responseFiles'] = []
                def built(app, target, *args, **kwargs):
                    target.mkdir()
                    (target / 'source-inputs.json').write_bytes(qualification.inventory(qualification.snapshot(app)))
                    write_json(target / 'BUILD-COMPLETE.json', {'controlled': True})
                    write_json(target / 'task-wait-port.json', port)
                    return target
                commands = Mock(records=[])
                commands.run.side_effect = BeforeSigning
                binaries = {name: parent / name for name in ('latent', 'latentd', 'capsule_contracts', 'package', 'capsule_authoring')}
                companions = {name: parent / name for name in qualification.TEMPLATES if name != 'greeting'}
                with patch.object(qualification, 'ROOT', source), \
                        patch.object(qualification, 'HELPERS', ('control.py',)), \
                        patch.object(qualification, 'sys', SimpleNamespace(platform='linux', version_info=(3, 13))), \
                        patch.object(qualification.subprocess, 'run', return_value=SimpleNamespace(stdout=b'')), \
                        patch.object(qualification.subprocess, 'check_output', return_value=b'controlled-revision\n'), \
                        patch.object(qualification, 'runtime_inputs', return_value=b'controlled-runtime'), \
                        patch.object(qualification, 'Commands', return_value=commands), \
                        patch.object(qualification, 'inherited', return_value=(binaries, companions, {})), \
                        patch.object(qualification, 'prepare', return_value=(application, {'originalLibraryAndFeedRemoved': True})), \
                        patch.object(qualification, 'build', side_effect=built), \
                        patch.object(qualification, 'run') as node:
                    with self.assertRaises(BeforeSigning if accepted else WorkflowError):
                        qualification.qualify(output, parent / 'tools', parent / 'prerequisites')
                node.assert_not_called()
                failed = json.loads((output / 'FAILED.json').read_bytes())
                self.assertEqual(failed['stage'], 'sign' if accepted else 'offline-native-aot-component')
                self.assertFalse((output / 'qualified.json').exists())
                if accepted:
                    self.assertEqual(commands.run.call_count, 1)
                    self.assertEqual(commands.run.call_args.args[0], 'demo-sign')
                    self.assertEqual(failed['taskWaitPort'], port)
                else:
                    commands.run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
