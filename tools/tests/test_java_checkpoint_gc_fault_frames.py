"""Bounded extraction controls for the Java GC numeric diagnostic."""
import unittest

from tools.java_checkpoint_gc_fault_frames import frames
from tools.phase2_operator_process import WorkflowError


class JavaCheckpointGcFaultFrameTests(unittest.TestCase):
    def test_frames_are_bounded_sequenced_and_name_free(self):
        raw=(b'ignored private guest text\n'
            b'LSF-JAVA-GC-FAULT:0:42:100:7\nLSF-JAVA-GC-FAULT:1:43:110:8\n')
        self.assertEqual(frames(raw),[
            {'ordinal':0,'function':42,'moduleOffset':100,'functionOffset':7},
            {'ordinal':1,'function':43,'moduleOffset':110,'functionOffset':8},
        ])
        for refused in (
                b'LSF-JAVA-GC-FAULT:1:42:100:7\n',
                b''.join(f'LSF-JAVA-GC-FAULT:{index}:42:100:7\n'.encode() for index in range(9)),
                b'x'*262145):
            with self.subTest(size=len(refused)),self.assertRaises(WorkflowError):frames(refused)


if __name__ == '__main__':
    unittest.main()
