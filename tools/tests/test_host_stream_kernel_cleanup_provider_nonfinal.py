"""Atomic branch/interleaving source controls; no compiled/native execution."""
import unittest
from tools import host_stream_kernel_cleanup_provider_nonfinal as source


class CleanupProviderNonfinalSource(unittest.TestCase):
    def test_actual_original_release_cas_and_no_destructor(self):
        text = source.atomic_nonfinal()
        self.assertIn('atomic_read(&r->refs)', text)
        self.assertIn('atomic_try_cmpxchg_release(&r->refs, &val, new)', text)
        for token in ('kobject_release', 'put_device(', 'kfree(', 'kmalloc(', 'WARN', 'lsf_device_finish('):
            self.assertNotIn(token, text)
        self.assertLess(text.index('val == 1'), text.index('atomic_try_cmpxchg_release'))
        self.assertIn('return -EOPNOTSUPP', text)
        self.assertIn('return -EOVERFLOW', text)
        self.assertIn('return -EIO', text)
        self.assertFalse(source.preimages()['actualAtomicExecution'])

    def test_callback_retains_real_borrow_on_failure_and_clears_after_success(self):
        # Parent callback bytes and whole originals are fixture-bound. Inspect
        # the exact emitted branch strings without using external derived files.
        from pathlib import Path
        tool = Path(source.__file__).read_text()
        self.assertIn("owned->put_error = put_error;", tool)
        self.assertIn('goto poison; /* Actual reference/descriptor/PCI/native charge retained. */', tool)
        self.assertLess(tool.index('if (put_error)'), tool.index('LAST companion field access'))
        self.assertIn('owned->companion = NULL;', tool)
        self.assertNotIn('kref_put(', source.atomic_nonfinal())

    def test_release_cas_race_linearizations_source_model_only(self):
        # One deterministic CAS attempt/retry of the source algorithm. This
        # checks the required cases, not Linux atomic execution or destruction.
        saturated = 0xc0000000
        def put(value, external_before_cas=0):
            observed = value
            while True:
                if observed == saturated:
                    return 'overflow', value, False
                if observed == 1:
                    return 'unsupported', value, False
                new = (observed - 1) & 0xffffffff
                if new > observed:
                    return 'invalid', value, False
                if external_before_cas:
                    value -= external_before_cas
                    external_before_cas = 0
                if value != observed:
                    observed = value
                    continue
                return 'consumed', new, True
        self.assertEqual(put(1), ('unsupported', 1, False))
        self.assertEqual(put(2, 1), ('unsupported', 1, False))
        self.assertEqual(put(2), ('consumed', 1, True))
        self.assertEqual(put(3, 1), ('consumed', 1, True))
        self.assertEqual(put(0), ('invalid', 0, False))
        self.assertEqual(put(saturated), ('overflow', saturated, False))
        # An external get after our read-of-one does not retrospectively
        # consume our retained borrow. Get-before-read permits normal 2->1.
        self.assertEqual(put(1)[2], False)
        self.assertEqual(put(2)[2], True)


if __name__ == '__main__':
    unittest.main()
