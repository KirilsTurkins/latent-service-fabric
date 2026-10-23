"""Actual maintained statement/ref/drop boundaries; no runtime qualification."""
import copy
import unittest
from tools import host_stream_kernel_cleanup_descendants as source


class CleanupDescendantSource(unittest.TestCase):
    def test_exact_whole_origins_and_unqualified_runtime_gates(self):
        value = source.preimages()
        self.assertEqual(len(value['source']), 7)
        self.assertEqual(len(value['sections']), 17)
        for name in ('taskCreated', 'executorReady', 'fullConstructorClosure',
                'lsmCallbackAllocationClosure', 'actualRcuExecution',
                'completeAllocationClosure', 'productionInstallation'):
            self.assertFalse(value[name])
        with self.assertRaisesRegex(ValueError, 'cleanup-descendants-whole-membership'):
            source.transform({}, {})

    def test_private_credentials_retain_every_original_reference_and_error_action(self):
        text = source.private_creds()
        prepare = text[text.index('static struct cred *lsf_cleanup_prepare_creds('):]
        prepare, copied = prepare.split('\nint lsf_prepaid_cleanup_copy_creds(', 1)
        prepare = source.replace(prepare,
            'static struct cred *lsf_cleanup_prepare_creds(struct lsf_cleanup_task_source source,\n'
            '    struct task_struct *owned_task)\n', 'struct cred *prepare_creds(void)\n')
        prepare = source.replace(prepare,
            '\tnew = lsf_factory_cleanup_child_new(source, owned_task, LSF_CLEANUP_CRED, owned_task);\n',
            '\tnew = kmem_cache_alloc(cred_jar, GFP_KERNEL);\n')
        prepare = source.replace(prepare,
            '#ifdef CONFIG_SECURITY\n'
            '\tif (lsf_prepaid_cleanup_security_prepare_creds(source, owned_task, new, old, GFP_KERNEL_ACCOUNT) < 0)\n'
            '#else\n\tif (security_prepare_creds(new, old, GFP_KERNEL_ACCOUNT) < 0)\n#endif\n',
            '\tif (security_prepare_creds(new, old, GFP_KERNEL_ACCOUNT) < 0)\n')
        self.assertEqual(prepare, source.definition('prepare_creds'))
        copied = 'int lsf_prepaid_cleanup_copy_creds(' + copied
        copied = source.replace(copied,
            'int lsf_prepaid_cleanup_copy_creds(struct lsf_cleanup_task_source source,\n'
            '    struct task_struct *p, unsigned long clone_flags)\n',
            'int copy_creds(struct task_struct *p, unsigned long clone_flags)\n')
        copied = source.replace(copied,
            '\n\tif (clone_flags != LSF_CLEANUP_CLONE_FLAGS || current != kthreadd_task)\n'
            '\t\treturn -EOPNOTSUPP;\n', '')
        copied = source.replace(copied, '\tnew = lsf_cleanup_prepare_creds(source, p);\n',
            '\tnew = prepare_creds();\n')
        self.assertEqual(copied, source.definition('copy_creds'))

    def test_real_composite_size_and_registered_hook_error_dispatch_are_preserved(self):
        text = source.private_security()
        self.assertIn('*bytes = blob_sizes.lbs_cred;', text)
        self.assertIn('if (blob_sizes.lbs_cred == 0)', text)
        actual = source.definition('security_prepare_creds')
        self.assertEqual(text[text.index('\tif (rc)\n'):], actual[actual.index('\tif (rc)\n'):])
        self.assertIn('call_int_hook(cred_prepare, new, old, gfp)', text)
        self.assertIn('security_cred_free(new);', text)
        self.assertNotIn('lsf_factory_device_', text)

    def test_sighand_retains_original_constructor_and_real_rcu_wrapper(self):
        text = source.private_signal()
        self.assertIn('*bytes = sizeof(struct lsf_cleanup_sighand);', text)
        self.assertLess(text.index('struct sighand_struct value;'), text.index('struct rcu_head rcu;'))
        self.assertIn('call_rcu(&owned->rcu, lsf_cleanup_sighand_return);', text)
        self.assertIn('sighand_ctor(sig);', text)
        self.assertIn('init_waitqueue_head(&sighand->signalfd_wqh);', source.definition('sighand_ctor'))
        callback = text[text.index('static void lsf_cleanup_sighand_return('):]
        callback = callback.split('static int lsf_cleanup_sighand_defer(', 1)[0]
        self.assertEqual(callback.count('lsf_factory_cleanup_child_finish('), 1)
        self.assertNotIn('kfree(', callback)

    def test_signal_keeps_original_timers_locks_audit_autogroup_and_error_order(self):
        text = source.private_signal()
        text = text[text.index('static int lsf_cleanup_copy_signal('):]
        text = text.split('\n#ifdef CONFIG_TASK_DELAY_ACCT\n', 1)[0]
        text = source.replace(text,
            'static int lsf_cleanup_copy_signal(struct lsf_cleanup_task_source source,\n'
            '    unsigned long clone_flags, struct task_struct *tsk)\n',
            'static int copy_signal(unsigned long clone_flags, struct task_struct *tsk)\n')
        text = source.replace(text,
            '\n\tif (clone_flags != LSF_CLEANUP_CLONE_FLAGS)\n\t\treturn -EOPNOTSUPP;\n', '')
        text = source.replace(text,
            '\tsig = lsf_factory_cleanup_child_new(source, tsk, LSF_CLEANUP_SIGNAL, tsk);\n',
            '\tsig = kmem_cache_zalloc(signal_cachep, GFP_KERNEL);\n')
        self.assertEqual(text, source.definition('copy_signal'))

    def test_delay_preserves_runtime_enabled_condition_and_real_lock_init(self):
        text = source.private_signal().split('#ifdef CONFIG_TASK_DELAY_ACCT\nstatic void lsf_cleanup_delayacct_init', 1)[1]
        self.assertLess(text.index('tsk->delays = NULL;'), text.index('if (delayacct_on)'))
        self.assertLess(text.index('lsf_factory_cleanup_child_new('), text.index('raw_spin_lock_init('))
        self.assertNotIn('delayacct_on =', text)
        self.assertNotIn('static_branch_disable', text)

    def test_child_birth_uses_original_generations_parent_and_charge_before_write(self):
        text = (source.OWNED / 'factory-cleanup-descendants.c').read_text()
        new = text.split('void *lsf_factory_cleanup_child_new(', 1)[1]
        new = new.split('int lsf_factory_cleanup_child_defer(', 1)[0]
        self.assertLess(new.index('lsf_cleanup_lifecycle_identity_locked(source, task)'),
            new.index('lsf_device_allocate('))
        self.assertLess(new.index('lsf_device_allocate('), new.index('memset(result, 0, bytes)'))
        self.assertIn('lsf_cleanup_child_find_locked(parent_address, LSF_CLEANUP_CRED, &parent)', new)
        self.assertIn('cleanup_child_attempted & (1u << kind)', new)
        self.assertIn('alignment > 64u', new)
        for forbidden in ('kmalloc(', 'alloc_pages(', 'get_task_struct(', 'put_task_struct('):
            self.assertNotIn(forbidden, new)

    def test_final_destructors_once_and_child_return_never_revive_or_replay_task(self):
        text = (source.OWNED / 'factory-cleanup-descendants.c').read_text()
        self.assertIn('LSF_CLEANUP_FINAL_DESTRUCTORS', text)
        self.assertIn('LSF_CLEANUP_FINAL_WAITING', text)
        self.assertIn('LSF_CLEANUP_FINAL_RETURNED', text)
        drain = text.split('void lsf_factory_cleanup_final_drain(void)\n', 1)[1]
        self.assertLess(drain.index('current != kthreadd_task'), drain.index('spin_lock_irqsave('))
        self.assertLess(drain.index('lsf_cleanup_final_children_locked()'), drain.index('lsf_device_finish('))
        for forbidden in ('get_task_struct(', 'put_task_struct(', '__put_task_struct(',
                'free_task(', 'refcount_set(', 'task->usage ='):
            self.assertNotIn(forbidden, drain)
        finish = text.split('int lsf_factory_cleanup_child_finish(', 1)[1]
        finish = finish.split('int lsf_factory_cleanup_task_destruct_begin(', 1)[0]
        self.assertLess(finish.index('spin_unlock_irqrestore('), finish.index('wake_up_process('))


if __name__ == '__main__':
    unittest.main()
