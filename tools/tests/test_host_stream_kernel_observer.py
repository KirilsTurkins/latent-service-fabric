"""Closed socket snapshots never manufacture physical-retirement proof."""
import json
import unittest
from unittest.mock import patch
from tools import host_stream_kernel_observer as observer


class HostStreamKernelObserver(unittest.TestCase):
    RAW = b"ESTAB 0 0 127.0.0.1:1234 127.0.0.1:4321 ino:42 sk:a skmem:(r1024,rb65536,t0,tb32768,f3072,w966,o0,bl0,d0)\n"

    def test_live_memory_and_original_inode_are_projected_without_coordinates(self):
        result = observer.parse(self.RAW, 42)
        self.assertEqual(result["matchingRows"], 1)
        self.assertTrue(result["inodeMatched"])
        self.assertEqual(result["memory"]["receiveAllocatedBytes"], 1024)
        self.assertEqual(result["memory"]["receiveLimitBytes"] + result["memory"]["transmitLimitBytes"], 98304)
        self.assertFalse(result["retirementProven"])
        self.assertNotIn("127.0.0.1", json.dumps(result))
        self.assertNotIn("ino:", json.dumps(result))

    def test_tail_without_live_inode_and_absence_never_prove_retirement(self):
        raw = b"FIN-WAIT-2 0 0 127.0.0.1:1234 127.0.0.1:4321 ino:0 sk:a\n"
        tail = observer.parse(raw, 42)
        self.assertEqual(tail["state"], "FIN-WAIT-2")
        self.assertFalse(tail["inodeMatched"])
        self.assertIsNone(tail["memory"])
        for result in (tail, observer.parse(b"", 42)):
            self.assertFalse(result["retirementProven"])

    def test_unknown_duplicate_missing_private_and_unbounded_fields_refuse(self):
        for raw in (self.RAW * 2, self.RAW.replace(b"ESTAB", b"UNKNOWN"),
                    self.RAW.replace(b"ino:42", b"ino:43"),
                    self.RAW.replace(b"d0", b"unknown0"),
                    self.RAW.replace(b"d0", b"d0,d1"), self.RAW.replace(b",d0", b""),
                    self.RAW.replace(b"d0", b"d4294967296"),
                    self.RAW.replace(b"d0", b"private-secret"), b"x" * (observer.MAXIMUM + 1)):
            with self.subTest(raw=raw[:20]), self.assertRaises(ValueError):
                observer.parse(raw, 42)

    def test_unsupported_platform_refuses_before_process_or_tool_read(self):
        with patch.object(observer.sys, "platform", "unsupported"), \
                patch.object(observer, "run_owned", side_effect=AssertionError("no process")), \
                self.assertRaisesRegex(ValueError, "platform"):
            observer.observe(1234, 4321, 42)
