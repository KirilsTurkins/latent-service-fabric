"""Source/collector controls only; Linux FD execution is a separate programme."""
import re
import unittest
from pathlib import Path
from tools import host_stream_kernel_cleanup_native as source
from tools import qualify_host_stream_native as native
from tools.host_stream_kernel_device_security import function


class CleanupNativeSource(unittest.TestCase):
    def test_candidate_projection_changes_only_one_exact_body(self):
        text = ('static inline const struct lsf_factory_consumer *lsf_factory_selected_consumer(void)\n'
            '{\n    return NULL;\n}\n'+source.QUALIFICATION_OFF)
        original = {'net/factory-private.h':text.encode(),'other':b'unchanged'}
        projected = source.qualification_projection(original)
        self.assertEqual(projected['other'],original['other'])
        self.assertIn(source.QUALIFICATION_ON.encode(),projected['net/factory-private.h'])
        self.assertIn(b'return NULL;',projected['net/factory-private.h'])
        with self.assertRaises(ValueError):
            source.qualification_projection(projected)
        with self.assertRaises(ValueError):
            source.qualification_projection({'net/factory-private.h':text.replace('NULL','selected').encode()})

    def test_pending_and_one_expiry_precede_real_unlocked_constructor(self):
        text = (source.OWNED/'factory-cleanup-native-bootstrap.c').read_text()
        body = function(text,'static ssize_t lsf_factory_bootstrap_write(')
        self.assertLess(body.index('bootstrap_expires_ns = expires'),body.index('mutex_unlock(&factory_lock)'))
        self.assertLess(body.index('bootstrap_busy = 1u'),body.index('mutex_unlock(&factory_lock)'))
        self.assertIn('expires != root->bootstrap_expires_ns',body)
        self.assertIn('120ULL * NSEC_PER_SEC',body)
        self.assertIn('error == -EINPROGRESS',body)
        self.assertLess(body.index('factory.device != root'),body.index('root->bootstrap_busy = 0'))
        self.assertIn('lsf_cleanup_admission_close()',body)
        self.assertNotIn('__free_pages',body)

    def test_both_status_snapshots_hold_original_locks_and_no_free_certificate(self):
        text = (source.OWNED/'factory-cleanup-native-bootstrap.c').read_text()
        for signature in ('static ssize_t lsf_factory_bootstrap_read(',
                'static ssize_t lsf_factory_bootstrap_diagnostic_read('):
            body = function(text,signature)
            self.assertLess(body.index('mutex_lock(&factory_lock)'),body.index('lsf_factory_actor(file)'))
            self.assertLess(body.index('spin_lock_irqsave(&pool_lock'),body.index('cpu_to_le32('))
            self.assertLess(body.index('spin_unlock_irqrestore'),body.index('copy_to_user('))
            self.assertNotIn('lsf_device_finish(',body)
        self.assertIn('sizeof(struct lsf_factory_bootstrap_diagnostic) == 104',text)

    def test_full_dispatch_authenticates_real_role_before_request_reads(self):
        text = (source.OWNED/'factory-cleanup-native-bootstrap.c').read_text()
        body = function(text,'int lsf_factory_cleanup_provider_creator_request(')
        self.assertLess(body.index('current != kthreadd_task'),body.index('spin_lock_irqsave'))
        self.assertLess(body.index('lsf_factory_cleanup_constructor_request('),body.index('spin_lock_irqsave'))
        self.assertIn('cleanup_physical_role == LSF_CLEANUP_PHYSICAL_PROVIDER',body)
        self.assertIn('cleanup_provider_submitted',body)
        self.assertIn('lsf_cleanup_provider_held_record_locked',body)
        self.assertNotIn('->create',body)
        for key in ('actualLinuxExecution','consumerSelected','completeAllocationClosure','productionInstallation'):
            self.assertFalse(source.preimages()[key])

    def test_safe_native_source_prepays_before_open_and_retains_on_failed_transfer(self):
        root = source.OWNED.parents[2]
        text = (root/'crates/latent-streams/src/kernel/native.rs').read_text()
        self.assertNotIn('unsafe',text)
        self.assertIn('clock_gettime(rustix::time::ClockId::Monotonic)',text)
        self.assertLess(text.index('reserve_stream_kernel_backing()?'),text.index('control_blocking_before('))
        self.assertLess(text.index('attempt.entered = true'),text.index('Some(open()?)'))
        self.assertIn('connected_retaining_on_error(resource)',text)
        self.assertIn('cleanup_stream_kernel_blocking_quarantined(connection',text)
        self.assertNotIn('.connected(resource)',text)
        self.assertNotIn('std::mem::forget',text)

    def test_exact_ten_real_descriptor_controls_have_no_ignored_case(self):
        path = native.ROOT/'crates/latent-streams/src/kernel/native/tests.rs'
        text = path.read_text()
        names = set(native.PREFIX+name for name in re.findall(
            r'#\[(?:tokio::test[^\n]*|test)\]\s*(?:async )?fn ([a-z0-9_]+)\(',text))
        self.assertEqual(names,native.CASES)
        self.assertEqual(len(names),13)
        self.assertNotIn('#[ignore',text)
        self.assertIn('/proc/self/fd/',text)
        self.assertIn('recv_timeout',text)

    def test_missing_failed_ignored_or_extra_outcome_refuses(self):
        raw=('\n'.join('test '+name+' ... ok' for name in sorted(native.CASES))+
            '\ntest result: ok. 13 passed; 0 failed; 0 ignored; 0 measured; 31 filtered out; finished in 1s\n').encode()
        self.assertEqual(native.outcomes(raw),sorted(native.CASES))
        for changed in (raw.replace(b'13 passed',b'12 passed'),raw.replace(b'0 ignored',b'1 ignored'),
                raw.replace(b'31 filtered',b'32 filtered'),raw.replace(b'... ok',b'... FAILED',1),
                raw+b'test extra ... ok\n'):
            with self.assertRaises(ValueError):
                native.outcomes(changed)


if __name__ == '__main__':
    unittest.main()
