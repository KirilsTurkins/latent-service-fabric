"""Original PCI path preservation and actual cleanup/Root cache lifetimes."""
import unittest
from tools import host_stream_kernel_cleanup_security as source


class CleanupSecuritySource(unittest.TestCase):
    def test_fixed_source_and_unqualified_runtime_boundaries(self):
        value = source.preimages()
        self.assertEqual(len(value['source']), 1)
        self.assertEqual(len(value['parentDerived']), 10)
        for name in ('taskCreated', 'executorReady', 'enabledAuditTaskClosure',
                'perfInheritanceClosure', 'bootstrapQualified', 'fullConstructorClosure'):
            self.assertFalse(value[name])
        with self.assertRaisesRegex(ValueError, 'cleanup-security-whole-membership'):
            source.transform({}, {})

    def test_all_original_pci_helpers_stay_whole_and_dispatch_is_typed(self):
        original = (source.OWNED / 'factory-device-security.c').read_text()
        actual = source.dispatch_security(original)
        signatures = {'record': 'static struct lsf_prepaid_view *', 'allocate': 'static void *',
            'finish': 'static int ', 'phase': 'static int ', 'publish': 'static int ',
            'queue': 'static int ', 'lookup': 'static int '}
        for name, result in signatures.items():
            symbol = 'lsf_factory_device_security_' + name + '_locked'
            before = source.function(original, result + symbol + '(')
            after = source.function(actual, result + symbol + '_pci(')
            self.assertEqual(after.replace(symbol + '_pci(', symbol + '(', 1), before)
        dispatch = source.function(actual, 'static int lsf_factory_device_security_lookup_locked(')
        self.assertLess(dispatch.index('lsf_cleanup_security_lookup_locked('),
            dispatch.index('lsf_factory_device_security_lookup_locked_pci('))

    def test_root_carrier_never_relabels_pci_or_null_application_context(self):
        original = (source.OWNED / 'device-owner-carrier.h').read_text()
        actual = source.root_carrier(original)
        shape = source.function(actual, 'static inline int lsf_factory_blob_shape(')
        self.assertIn('source.domain == LSF_FACTORY_OWNER_CLEANUP', shape)
        self.assertIn('!source.device.pci_slot', shape)
        self.assertIn('lsf_root_security_shape(source.cleanup)', shape)
        self.assertIn('source.ticket.generation == source.cleanup.allocation.generation', shape)
        same = source.function(actual, 'static inline int lsf_factory_blob_same_owner(')
        for field in ('owner.slot', 'owner.generation', 'root.slot', 'root.generation'):
            self.assertIn('a.cleanup.' + field + ' == b.cleanup.' + field, same)

    def test_selinux_fork_retains_ordinary_permission_call_and_real_private_audit(self):
        original = source.preimages()['sections']['selinux_task_alloc']['text']
        actual = source.task_hook()
        begin = actual.index('#ifdef CONFIG_LSF_STREAM_FACTORY\n')
        end = actual.index('#endif\n', begin) + len('#endif\n')
        self.assertEqual(actual[:begin] + actual[end:], original)
        self.assertIn('lsf_prepaid_avc_has_perm(sid, sid, SECCLASS_PROCESS, PROCESS__FORK, NULL, &source)', actual)
        self.assertNotIn('lsf_prepaid_avc_has_perm_noaudit(', actual)
        self.assertIn('if (origin < 0)', actual)

    def test_real_zero_task_blob_does_not_require_a_nonexistent_child(self):
        # The selected SELinux module contributes a credential blob, but no
        # Task blob. Real composite lbs_task may therefore be zero.
        sizes = source.preimages()['sections']['selinux_blob_sizes']['text']
        self.assertIn('.lbs_cred = sizeof(struct task_security_struct)', sizes)
        self.assertNotIn('.lbs_task', sizes)
        text = (source.OWNED / 'factory-cleanup-security.c').read_text()
        mint = source.function(text, 'int lsf_factory_cleanup_task_constructor_blob(')
        self.assertIn('.ticket = source.task', mint)
        self.assertIn('source.task, task, LSF_ROOT_SECURITY_TASK_BIRTH', mint)
        self.assertNotIn('task->security', mint)
        self.assertNotIn('LSF_CLEANUP_TASK_SECURITY', mint)
        self.assertIn('LSF_ROOT_SECURITY_TASK_BIRTH == LSF_DEVICE_CLEANUP_TASK', text)

    def test_shared_cache_births_use_root_and_callbacks_do_not_need_task(self):
        text = (source.OWNED / 'factory-cleanup-security.c').read_text()
        allocate = source.function(text, 'static void *lsf_cleanup_security_allocate_locked(')
        self.assertIn('source.cleanup.root, &ticket, &offset', allocate)
        self.assertLess(allocate.index('lsf_device_allocate('), allocate.index('memset(result, 0, bytes)'))
        root = source.function(text, 'static int lsf_cleanup_security_root_locked(')
        for forbidden in ('task->', 'cleanup_task', 'current !=', 'READ_ONCE(factory.uncertain)'):
            self.assertNotIn(forbidden, root)
        self.assertIn('source.root.generation == factory.device->root.generation', root)
        record = source.function(text, 'static struct lsf_prepaid_view *lsf_cleanup_security_record_locked(')
        shared = record.split('if (!lsf_root_security_kind(source.kind)', 1)[1]
        for forbidden in ('task->', 'cleanup_task', 'cleanup_lifecycle', 'kthreadd_task'):
            self.assertNotIn(forbidden, shared)

    def test_drain_candidates_are_scalar_and_actual_recheck_precedes_address(self):
        text = (source.OWNED / 'factory-cleanup-security.c').read_text()
        candidate = source.function(text, 'int lsf_factory_cleanup_security_candidate(')
        self.assertIn('{slot, record->generation}, NULL, kind', candidate)
        current = source.function(text, 'int lsf_factory_cleanup_security_current(')
        assignment = current.index('candidate.address =')
        for check in ('record->generation != candidate.allocation.generation',
                'record->cache_anchor != candidate.root.generation',
                'record->security_cache_location != location',
                'record->security_cache_identity != identity'):
            self.assertLess(current.index(check), assignment)
        bounds = source.function(text, 'static struct lsf_prepaid_view *lsf_cleanup_security_drain_record_locked(')
        self.assertIn('record->security_cache_location > 512u', bounds)
        self.assertIn('!context->closed', bounds)


if __name__ == '__main__':
    unittest.main()
