"""Fail-closed selection of host-source controls, not guest execution proof."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from tools import qualify_java_fibers as owner


class FutureTaskMonitorOwner(unittest.TestCase):
    reference = 'FUTURE_TASK_MONITOR_REFERENCE PASS run;cancel;completed-get;executor;scheduled-cancel'
    ownership = 'FUTURE_TASK_MONITOR_OWNER PASS managed;active-owners;scheduled;retired-under-public-monitor'

    def run_owner(self, missing=None):
        calls = []
        receipts = {'future-task-monitor-reference-jdk': self.reference,
                    'future-queue-source-control': 'FUTURE_QUEUE_OWNER PASS checks=48',
                    'future-task-monitor-source': self.reference,
                    'future-task-monitor-owner': self.ownership}
        def run(stage, *arguments):
            calls.append(stage)
            if stage == missing: return 'SKIPPED'
            return receipts.get(stage, '')
        compiler = SimpleNamespace(sdk=owner.ROOT/'sdk/java-guest', run=run)
        with TemporaryDirectory() as directory:
            result = owner.future_queue_source_control(compiler, Path(directory)/'control')
        return result, calls

    def test_existing_and_new_controls_are_selected(self):
        result, calls = self.run_owner()
        self.assertEqual(result['ownershipChecks'],48)
        self.assertEqual(result['futureMonitor'],'JDK-and-SDK-source-controls-passed')
        self.assertFalse(result['componentExecutionPerformed'])
        self.assertEqual(calls, ['future-task-monitor-reference-compile','future-task-monitor-reference-jdk',
            'future-queue-source-compile','future-queue-source-control',
            'future-task-monitor-source','future-task-monitor-owner'])

    def test_missing_reference_source_or_ownership_receipt_is_refused(self):
        for stage in ('future-task-monitor-reference-jdk','future-queue-source-control',
                      'future-task-monitor-source','future-task-monitor-owner'):
            with self.subTest(stage=stage), self.assertRaises(ValueError):
                self.run_owner(stage)


if __name__ == '__main__':
    unittest.main()
