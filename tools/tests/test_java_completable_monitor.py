"""Fail-closed selection of the maintained CompletableFuture source controls."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import json
import unittest

from tools import qualify_java_fibers as owner


class CompletableMonitorOwner(unittest.TestCase):
    monitor = 'COMPLETABLE_FUTURE_MONITOR_REFERENCE PASS completion;exception-callbacks=7;cause-once=6'
    custody = ('COMPLETABLE_FUTURE_MONITOR_OWNER PASS callback-retirement;'
               'cancelled-queued-retirement;subscribe-race')
    existing = 'COMPLETABLE_FUTURE_SOURCE_CONTROL PASS observables=82'
    existing_owner = 'COMPLETABLE_FUTURE_OWNER_CONTROL PASS observables=419;raceRounds=32'

    def run_owner(self, missing=None):
        calls = []
        executor_cases = '\n'.join(json.dumps({'case': i}) for i in range(6))
        receipts = {'completable-reference-run': self.existing,
                    'completable-executor-reference-run': executor_cases,
                    'completable-monitor-reference-jdk': self.monitor,
                    'completable-source-run': self.existing + '\n' + self.existing_owner,
                    'completable-executor-source-run': executor_cases,
                    'completable-executor-owners-run': 'COMPLETABLE_FUTURE_EXECUTOR_ACCEPTANCE_OWNER PASS observables=49',
                    'completable-executor-uncertain-run': ('COMPLETABLE_FUTURE_EXECUTOR_UNCERTAIN_OWNER PASS '
                        'observables=30;queued=8;results=8;cleanup-denied;activation-retirement-unqualified'),
                    'completable-monitor-source': self.monitor,
                    'completable-monitor-owner': self.custody}

        def run(stage, *arguments):
            calls.append(stage)
            if stage == missing: return 'SKIPPED'
            return receipts.get(stage, '')

        compiler = SimpleNamespace(sdk=owner.ROOT / 'sdk/java-guest', run=run)
        with TemporaryDirectory() as directory:
            result = owner.completable_source_control(compiler, Path(directory) / 'source')
        return result, calls

    def test_existing_and_monitor_controls_are_selected(self):
        result, calls = self.run_owner()
        self.assertEqual(result['referenceObservables'], 82)
        self.assertEqual(result['sourceOwnershipObservables'], 419)
        self.assertEqual(result['raceRounds'], 32)
        self.assertEqual(result['futureMonitor'], 'JDK-and-SDK-source-controls-passed')
        self.assertFalse(result['componentExecutionPerformed'])
        self.assertFalse(result['actualGuestBindingsUsed'])
        self.assertEqual(calls, ['completable-reference-compile', 'completable-reference-run',
            'completable-executor-reference-run', 'completable-monitor-reference-jdk',
            'completable-source-compile', 'completable-source-run', 'completable-executor-source-run',
            'completable-executor-owners-run', 'completable-executor-uncertain-run',
            'completable-monitor-source', 'completable-monitor-owner'])

    def test_missing_monitor_receipts_are_refused(self):
        for stage in ('completable-monitor-reference-jdk', 'completable-monitor-source', 'completable-monitor-owner'):
            with self.subTest(stage=stage), self.assertRaises(ValueError):
                self.run_owner(stage)


if __name__ == '__main__':
    unittest.main()
