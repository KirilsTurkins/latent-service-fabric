"""Native attribution cannot erase unowned allocations or invent retirement."""
import unittest

from tools.host_stream_tls_allocation import TlsAllocationReplay


class NativeTlsAllocationReplay(unittest.TestCase):
    def replay(self, events, *, finish=True):
        lines = [b"v 10400 3", b"X tls-allocation-fixture", b"I 1000 2000"]
        for value in (b"fixture.so", b"14latent_streams9transport", b"14latent_streams3tls9configure"):
            lines.append(f"s {len(value):x} ".encode() + value)
        lines += [b"i 1 1 2", b"i 2 1 3", b"i 3 1", b"t 1 0", b"t 2 0", b"t 3 0",
                  b"a 100 1", b"a 80 2", b"a 40 3", *events]
        if finish:
            lines += [b"c 1", b"# strings: 3", b"# ips: 3"]
        replay = TlsAllocationReplay()
        for line in lines:
            replay.record(line)
        return replay

    def test_shared_allocation_indices_preserve_real_highs_and_each_original_free(self):
        observed = self.replay([b"+ 0", b"+ 0", b"- 0", b"+ 1", b"- 0", b"- 1"]).observation()
        self.assertEqual(observed["transport"], {"peakBytes": 512, "remainingBytes": 0, "allocationCalls": 2})
        self.assertEqual(observed["trustConfiguration"], {"peakBytes": 128, "remainingBytes": 0, "allocationCalls": 1})
        self.assertEqual(observed["allAllocations"]["remaining_live_bytes"], "0")
        self.assertFalse(observed["fullAccountingQualified"])

    def test_unattributed_and_unretired_allocations_remain_visible(self):
        observed = self.replay([b"+ 0", b"+ 2"]).observation()
        self.assertEqual(observed["transport"]["remainingBytes"], 256)
        self.assertEqual(observed["allAllocations"]["remaining_live_bytes"], "320")
        self.assertNotIn("command", observed["allAllocations"])
        self.assertFalse(observed["fullAccountingQualified"])

    def test_bad_free_missing_completion_and_unknown_versions_never_produce_observation(self):
        with self.assertRaisesRegex(ValueError, "free-without-live"):
            self.replay([b"- 0"])
        with self.assertRaisesRegex(ValueError, "completion-footer"):
            self.replay([b"+ 0"], finish=False).observation()
        with self.assertRaisesRegex(ValueError, "unsupported-version"):
            TlsAllocationReplay().record(b"v 10500 3")
