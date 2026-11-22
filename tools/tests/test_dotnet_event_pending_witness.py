"""Receipt controls for the pending event witness; not signed guest execution."""
import copy
import unittest

from tools.rust_capsule_project import digest


class PendingEventWitnessReceiptTests(unittest.TestCase):
    def test_pending_event_receipt_cannot_reuse_the_eager_or_unretired_result(self):
        from tools import dotnet_task_runtime_fixture as fixture
        from tools.phase2_operator_process import WorkflowError
        from tools.qualify_dotnet_task_runtime import require_reset_notification_receipt
        source, cases = fixture.selected_fixture(reset_notification=True)
        expected = 'ordinary-tasks:manual-reset-sibling|pending=1|same-thread=1|setter=1|fresh=1'
        self.assertEqual(fixture.expected(fixture.EVENT_WAIT_MODE), expected)
        captured = {'cases': list(cases), 'originalFiles': {'Library.cs': digest(source.encode('utf-8'))}}
        receipt = {'dotnetTaskRuntime': {'cases': [
            {'mode': mode, 'invocation': {'processReaped': True, 'exitCode': 0,
                'response': {'outcomeKnown': True}, 'decoded': [{'ok': fixture.expected(mode)}]},
             'retirement': {'phase': 'dotnet-ordinary-tasks-' + mode + '-retired'}}
            for mode in cases]}}
        require_reset_notification_receipt(captured, receipt)
        for mutation in ('legacy', 'not-pending', 'other-thread', 'duplicate-setter', 'exception',
                         'unreaped', 'unknown', 'exit', 'retirement', 'source'):
            inputs, wrong = copy.deepcopy(captured), copy.deepcopy(receipt)
            event = wrong['dotnetTaskRuntime']['cases'][cases.index(fixture.EVENT_WAIT_MODE)]
            observed = event['invocation']
            if mutation == 'legacy': observed['decoded'] = [{'ok': 'ordinary-tasks:manual-reset-sibling|fresh=1'}]
            elif mutation == 'not-pending': observed['decoded'] = [{'ok': expected.replace('pending=1', 'pending=0')}]
            elif mutation == 'other-thread': observed['decoded'] = [{'ok': expected.replace('same-thread=1', 'same-thread=0')}]
            elif mutation == 'duplicate-setter': observed['decoded'] = [{'ok': expected.replace('setter=1', 'setter=2')}]
            elif mutation == 'exception': observed['decoded'] = [{'err': 'ordinary-task-failure:event-wait:unknown'}]
            elif mutation == 'unreaped': observed['processReaped'] = False
            elif mutation == 'unknown': observed['response']['outcomeKnown'] = False
            elif mutation == 'exit': observed['exitCode'] = 4
            elif mutation == 'retirement': event['retirement']['phase'] += '-wrong'
            else:
                # Even a claimed new result cannot qualify an eager-only source.
                eager = source.replace('phase = 1;\n                signal.Wait();',
                                       'phase = 1;\n                signal.Set();')
                self.assertNotEqual(eager, source)
                inputs['originalFiles']['Library.cs'] = digest(eager.encode('utf-8'))
            with self.subTest(mutation=mutation), self.assertRaises(WorkflowError):
                require_reset_notification_receipt(inputs, wrong)


if __name__ == '__main__':
    unittest.main()
