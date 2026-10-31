"""Numeric diagnostic bounds and private stderr exclusion; no guest execution."""
from pathlib import Path
import unittest

from tools.phase2_operator_process import WorkflowError
from tools.rust_thread_fault_frames import frames


class RustThreadFaultFramesTests(unittest.TestCase):
    def test_workflow_fetches_current_native_and_retained_failure_sources(self):
        workflow = (Path(__file__).resolve().parents[2] / '.github' / 'workflows'
                    / 'rust-thread-fault-diagnostic.yml').read_text(encoding='utf-8')
        prefix = 'git fetch --no-tags --depth=1 origin '
        self.assertEqual(workflow.count(prefix +
                         'e3f0edf822c10e84bbeede276174ac3217542afc'), 1)
        for source in ('b422af24d86344ac7abb8b8fa56c3782aab63915',
                       '28059f343bbd954e3e6614c5a24593897cc0c294',
                       '2259601ab19702eafd56c39bcb43f769cdb47fa5',
                       '9106147f83a2e19c8b1be16b9eb5d55e39512bde'):
            self.assertIn(prefix + source, workflow)
        for obsolete in ('deb654086a6e9ca85c1c96c7e3485babbc6557d9',
                         'ef841ed1d5691b4bf25db48b9980a776b4b56bc5',
                         '79911762b366381d7dc61da12d1b5e9aba2b3222'):
            self.assertNotIn(prefix + obsolete, workflow)

    def test_diagnostic_consumer_accepts_only_the_bound_numeric_unreachable_fault(self):
        runtime = (Path(__file__).resolve().parents[2] / 'tools'
                   / 'rust_thread_runtime_node.py').read_text(encoding='utf-8')
        programme = (Path(__file__).resolve().parents[2] / 'tools'
                     / 'diagnose_rust_thread_fault.py').read_text(encoding='utf-8')
        self.assertIn("row['exitCode'] == 4 and row['decoded'] is None", runtime)
        self.assertIn("{'kind': 'guest-fault'}", runtime)
        self.assertNotIn("'unreachable-code'", runtime)
        self.assertIn("'rust-thread-exact-numeric-original-fault-observation'", runtime)
        self.assertIn("status='diagnostic-fault-observed'", runtime)
        self.assertIn("'completed-with-fault'", programme)
        self.assertIn("runtimeQualification=False", programme)

    def test_numeric_rows_are_finite_sequential_and_exclude_private_text(self):
        rows = b'private error and guest-name\n' + b''.join(
            f'LSF-RUST40-FAULT:{i}:123:456:789\n'.encode() for i in range(8))
        observed = frames(rows)
        self.assertEqual(len(observed), 8)
        self.assertEqual(observed[0], {'ordinal': 0, 'function': 123,
                                     'moduleOffset': 456, 'functionOffset': 789})
        from tools.rust_thread_fault_frames import capture, trap_code
        self.assertEqual(trap_code(b'private guest-name\n'), None)
        self.assertEqual(trap_code(b'LSF-RUST40-TRAP:17\n' + rows), 17)
        self.assertEqual(frames(b'LSF-RUST40-TRAP:17\n' + rows), observed)
        for invalid in (b'LSF-RUST40-TRAP:0\nLSF-RUST40-TRAP:17\n',
                        b'LSF-RUST40-TRAP:50\n', b'LSF-RUST40-TRAP:00\n',
                        b'LSF-RUST40-TRAP:-1\n', b'LSF-RUST40-TRAP:private\n',
                        b'LSF-RUST40-TRAP\n', b'LSF-RUST40-TRAP:1:2\n',
                        b'x' * 262145):
            with self.subTest(bytes=len(invalid)), self.assertRaises(WorkflowError):
                trap_code(invalid)

        import json
        import tempfile

        class Node:
            buffers = (b'', b'LSF-RUST40-TRAP:17\n')

            def drain(self):
                pass
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            capture(Node(), {'fixture': 'node'}, {'fixture': 'component'}, output)
            scalar = json.loads((output / 'numeric-original-trap-code.json').read_bytes())
            self.assertEqual(scalar['originalTrapCode'], 17)
            self.assertIs(scalar['runtimeQualification'], False)
            self.assertTrue(scalar['frameObservationRequiredSeparately'])
            self.assertFalse((output / 'numeric-fault-frames.json').exists())
        from tools.rust_thread_fault_frames import scheduler_snapshot
        scheduler = b'LSF-RUST40-SCHED:12:14:1:2:3:1:1:0:1:66:2\n'
        self.assertIsNone(scheduler_snapshot(b'private guest-name\n'))
        snapshot = scheduler_snapshot(b'private guest-name\n' + scheduler)
        self.assertEqual(snapshot['physicalSlotsScanned'], 12)
        self.assertFalse(snapshot['prefixTruncated'])
        self.assertEqual(snapshot['prefixThreadStateCounts']['running'], 3)
        self.assertEqual(snapshot['prefixHostRootCount'], 1)
        self.assertEqual(snapshot['prefixRootFlagsOr'], 66)
        self.assertEqual(snapshot['prefixWaitingThreadCount'], 2)
        self.assertTrue(snapshot['hostFutureStreamExhaustedBeforeFinalRootPoll'])
        self.assertTrue(scheduler_snapshot(
            b'LSF-RUST40-SCHED:64:15:0:0:0:1:0:0:1:66:2\n')['prefixTruncated'])
        for invalid in (scheduler + scheduler,
                        scheduler.replace(b':12:', b':012:', 1),
                        scheduler.replace(b':12:', b':65:', 1),
                        scheduler.replace(b':14:', b':32:', 1),
                        scheduler.replace(b':14:', b':6:', 1),
                        scheduler.replace(b':14:', b':15:', 1),
                        scheduler.replace(b':14:', b':30:', 1),
                        scheduler.replace(b':12:', b':1:', 1),
                        scheduler.replace(b':66:', b':256:', 1),
                        scheduler.replace(b':2\n', b':65536\n'),
                        b'LSF-RUST40-SCHED\n',
                        scheduler[:-1] + b':0\n',
                        b'LSF-RUST40-SCHED:private\n', b'x' * 262145):
            with self.subTest(schedulerBytes=len(invalid)), self.assertRaises(WorkflowError):
                scheduler_snapshot(invalid)
        Node.buffers = (b'', b'LSF-RUST40-TRAP:22\n' + scheduler)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            capture(Node(), {'fixture': 'node'}, {'fixture': 'component'}, output)
            observed = json.loads((output / 'numeric-original-scheduler-snapshot.json').read_bytes())
            self.assertEqual(observed['originalTrapCode'], 22)
            self.assertEqual(observed['snapshot'], snapshot)
            self.assertIs(observed['runtimeQualification'], False)
            self.assertTrue(observed['frameObservationRequiredSeparately'])
            self.assertFalse((output / 'numeric-fault-frames.json').exists())
            Node.buffers = (b'', b'LSF-RUST40-TRAP:17\n' + scheduler)
            mismatch = output / 'mismatch'
            mismatch.mkdir()
            with self.assertRaises(WorkflowError):
                capture(Node(), {'fixture': 'node'}, {'fixture': 'component'}, mismatch)
        from tools.rust_thread_fault_frames import root_suspension
        suspension = b'LSF-RUST40-SUSP:3:64:8:8\n' + b''.join(
            f'LSF-RUST40-SUSP-FRAME:{i}:{i % 2}:123:456:789\n'.encode() for i in range(8))
        observed_wait = root_suspension(b'private guest-name\n' + suspension)
        self.assertEqual(len(observed_wait['frames']), 8)
        self.assertEqual(observed_wait['rawTraversalSteps'], 64)
        self.assertTrue(observed_wait['framesMayBeTruncated'])
        self.assertIsNone(root_suspension(b'private guest-name\n'))
        unavailable = root_suspension(b'LSF-RUST40-SUSP:32:0:0:0\n')
        self.assertTrue(unavailable['lastTransferUnavailable'])
        self.assertEqual(unavailable['frames'], [])
        for invalid in (suspension + b'LSF-RUST40-SUSP:0:1:0:0\n',
                        suspension.replace(b':64:', b':65:', 1),
                        suspension.replace(b':3:64:', b':3:63:', 1),
                        suspension.replace(b':8:8\n', b':9:8\n', 1),
                        suspension.replace(b':8:8\n', b':8:7\n', 1),
                        suspension.replace(b':0:0:123:', b':0:2:123:', 1),
                        suspension.replace(b':123:', b':4294967296:', 1),
                        suspension.replace(b':456:', b':4294967295:', 1),
                        suspension.replace(b':0:0:123:', b':00:0:123:', 1),
                        suspension.replace(b':123:', b':private:', 1),
                        suspension + b'LSF-RUST40-SUSP-FRAME:8:0:1:2:3\n',
                        b'LSF-RUST40-SUSP-FRAME:0:0:1:2:3\n',
                        b'LSF-RUST40-SUSP:32:1:0:0:0\n',
                        b'LSF-RUST40-SUSP:128:0:0:0\n',
                        b'LSF-RUST40-SUSP:private\n', b'x' * 262145):
            with self.subTest(suspensionBytes=len(invalid)), self.assertRaises(WorkflowError):
                root_suspension(invalid)
        # Header-first is part of the emitted record, not merely a set of rows.
        # In particular, a later valid header cannot adopt an earlier orphan.
        header, _, emitted_frames = suspension.partition(b'\n')
        first, _, remaining = emitted_frames.partition(b'\n')
        for invalid in (emitted_frames + header + b'\n',
                        first + b'\n' + header + b'\n' + remaining):
            with self.subTest(order=invalid[:32]), self.assertRaises(WorkflowError):
                root_suspension(invalid)

        # Numeric coordinates retained by diagnostic run 41211537571. This is
        # parser coverage of an observation, NOT replay or runtime qualification.
        actual_frames = ((288, 76700, 500), (449, 132337, 44),
                         (240, 58505, 284), (357, 89350, 104),
                         (376, 93025, 63), (63, 16666, 176))
        actual = b'LSF-RUST40-SUSP:0:5:6:6\n' + b''.join(
            f'LSF-RUST40-SUSP-FRAME:{i}:0:{function}:{instruction}:{offset}\n'.encode()
            for i, (function, instruction, offset) in enumerate(actual_frames))
        actual_wait = root_suspension(actual)
        self.assertEqual(actual_wait['rawTraversalSteps'], 5)
        self.assertEqual(actual_wait['rawFrameVisits'], 6)
        self.assertEqual([(row['function'], row['moduleOffset'], row['functionOffset'])
                          for row in actual_wait['frames']], list(actual_frames))
        for flag in ('traversalMayBeTruncated', 'framesMayBeTruncated',
                     'missingSourceCoordinates', 'unmappedFrames', 'traceUnavailable',
                     'lastTransferUnavailable', 'noCaptureSaved'):
            self.assertFalse(actual_wait[flag])
        self.assertEqual(root_suspension(actual.replace(b'\n', b'\r\n')), actual_wait)
        Node.buffers = (b'', b'private guest-name\nLSF-RUST40-TRAP:22\n' + actual)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            capture(Node(), {'fixture': 'node'}, {'fixture': 'component'}, output)
            kept = json.loads((output / 'numeric-original-root-suspension.json').read_bytes())
            self.assertEqual(kept['suspension'], actual_wait)
            self.assertFalse(kept['runtimeQualification'])
            self.assertTrue(kept['frameObservationRequiredSeparately'])
            self.assertFalse((output / 'numeric-fault-frames.json').exists())
            self.assertNotIn('private guest-name', json.dumps(kept))
        Node.buffers = (b'', b'LSF-RUST40-TRAP:22\n' + scheduler + suspension)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            capture(Node(), {'fixture': 'node'}, {'fixture': 'component'}, output)
            kept = json.loads((output / 'numeric-original-root-suspension.json').read_bytes())
            self.assertEqual(kept['suspension'], observed_wait)
            self.assertFalse(kept['runtimeQualification'])
            self.assertTrue(kept['frameObservationRequiredSeparately'])
            self.assertFalse((output / 'numeric-fault-frames.json').exists())
        self.assertEqual(frames(b'private guest-name\nLSF-RUST40-FAULT:0:private:2:3\n'), [])
        for invalid in (rows + b'LSF-RUST40-FAULT:8:1:2:3\n',
                        b'LSF-RUST40-FAULT:1:1:2:3\n',
                        b'LSF-RUST40-FAULT:0:4294967296:2:3\n',
                        b'x' * 262145):
            with self.subTest(bytes=len(invalid)), self.assertRaises(WorkflowError):
                frames(invalid)


if __name__ == '__main__':
    unittest.main()
