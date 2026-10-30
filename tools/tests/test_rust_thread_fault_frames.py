"""Numeric diagnostic bounds and private stderr exclusion; no guest execution."""
from pathlib import Path
import unittest

from tools.phase2_operator_process import WorkflowError
from tools.rust_thread_fault_frames import frames


class RustThreadFaultFramesTests(unittest.TestCase):
    def test_workflow_fetches_current_native_and_retained_failure_sources(self):
        workflow = (Path(__file__).resolve().parents[2] / '.github' / 'workflows'
                    / 'rust-thread-fault-diagnostic.yml').read_text(encoding='utf-8')
        self.assertIn('git fetch --no-tags --depth=1 origin '
                      '9c0097fc4dee24c57e0cffbdf1963e47772b2ffc', workflow)
        self.assertIn('git fetch --no-tags --depth=1 origin '
                      '79911762b366381d7dc61da12d1b5e9aba2b3222', workflow)

    def test_numeric_rows_are_finite_sequential_and_exclude_private_text(self):
        rows = b'private error and guest-name\n' + b''.join(
            f'LSF-RUST40-FAULT:{i}:123:456:789\n'.encode() for i in range(8))
        observed = frames(rows)
        self.assertEqual(len(observed), 8)
        self.assertEqual(observed[0], {'ordinal': 0, 'function': 123,
                                     'moduleOffset': 456, 'functionOffset': 789})
        self.assertEqual(frames(b'private guest-name\nLSF-RUST40-FAULT:0:private:2:3\n'), [])
        for invalid in (rows + b'LSF-RUST40-FAULT:8:1:2:3\n',
                        b'LSF-RUST40-FAULT:1:1:2:3\n',
                        b'LSF-RUST40-FAULT:0:4294967296:2:3\n',
                        b'x' * 262145):
            with self.subTest(bytes=len(invalid)), self.assertRaises(WorkflowError):
                frames(invalid)


if __name__ == '__main__':
    unittest.main()
