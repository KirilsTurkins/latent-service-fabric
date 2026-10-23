"""Typed real errors before module/helper admission, ordinary bodies intact."""
import re
import unittest
from tools import host_stream_kernel_cleanup_worker_operations as source


class CleanupWorkerOperationsSource(unittest.TestCase):
    def test_exact_real_sources_and_unqualified_foreign_info(self):
        value = source.preimages()
        self.assertEqual(len(value['source']), 7)
        for key in ('operationExecuted', 'factoryCallsFullWorkerCreate',
                    'pendingConsumerCallsFullClone', 'foreignInfoCleanupQualified',
                    'publishedWorkerLsmQualified', 'completeAllocationClosure'):
            self.assertFalse(value[key])
        with self.assertRaisesRegex(ValueError, 'cleanup-worker-operations-whole-membership'):
            source.transform({}, {})

    def test_all_four_complete_ordinary_bodies_project_exactly(self):
        for key, modified in [('request_module', source.request_module()), ('helper', source.helper()),
                              ('setup', source.setup()), ('exec', source.execute())]:
            ordinary = re.sub(r'#ifdef CONFIG_LSF_STREAM_FACTORY\n.*?#endif\n', '', modified, flags=re.S)
            self.assertEqual(ordinary, source.definition(key))

    def test_origin_is_exact_current_birth_and_process_context_before_fields(self):
        text = (source.OWNED/'factory-cleanup-worker-operations.c').read_text()
        self.assertIn('lsf_factory_cleanup_worker_operation_current(void)', text)
        self.assertLess(text.index('if (!in_task())'), text.index('spin_lock_irqsave('))
        self.assertLess(text.index('lsf_cleanup_lifecycle_identity_locked(source, current)'),
            text.index('refcount_read(&current->usage)'))
        for token in ('LSF_CLEANUP_PUBLISHED', 'LSF_CLEANUP_FINAL_NONE', 'current->flags & PF_KTHREAD',
                      'result = -EIO', 'lsf_cleanup_lifecycle_poison_locked()'):
            self.assertIn(token, text)
        # Normal close cannot turn an existing owned Task into ordinary fallback.
        self.assertNotIn('factory.pool.stopped', text)
        self.assertNotIn('.closed', text)
        for forbidden in ('current->comm', 'task_pid', 'current_cred', 'worker_private'):
            self.assertNotIn(forbidden, text)

    def test_module_real_error_precedes_lsm_audit_and_every_helper_admission(self):
        text = source.request_module()
        guard = text.index('lsf_factory_cleanup_worker_operation_current()')
        for target in ('current_is_async()', 'va_start(args, fmt)', 'security_kernel_module_request(',
                       'down_timeout(', 'trace_module_request(', 'kmod_dup_request_exists_wait(', 'call_modprobe('):
            self.assertLess(guard, text.index(target))
        self.assertIn('return owned < 0 ? -EIO : -EOPNOTSUPP', text)
        actual = source.definition('call_modprobe')
        self.assertLess(actual.index('kmalloc('), actual.index('call_usermodehelper_setup('))
        self.assertIn('free_module_name:', actual)
        self.assertIn('free_argv:', actual)
        self.assertIn('return -ENOMEM;', actual)

    def test_convenience_has_integer_error_but_setup_preserves_null_contract(self):
        helper = source.helper()
        self.assertLess(helper.index('lsf_factory_cleanup_worker_operation_current()'),
            helper.index('info = call_usermodehelper_setup('))
        self.assertIn('return owned < 0 ? -EIO : -EOPNOTSUPP', helper)
        setup = source.setup()
        self.assertLess(setup.index('lsf_factory_cleanup_worker_operation_current()'), setup.index('kzalloc('))
        self.assertIn('return NULL;', setup)
        self.assertNotIn('return ERR_PTR(', setup)
        self.assertNotIn('return -EOPNOTSUPP', setup)

    def test_exec_consumes_info_once_before_lock_queue_and_new_task(self):
        text = source.execute()
        guard = text[text.index('#ifdef CONFIG_LSF_STREAM_FACTORY'):text.index('#endif')]
        self.assertEqual(guard.count('call_usermodehelper_freeinfo(sub_info)'), 1)
        self.assertNotIn('helper_unlock(', guard)
        self.assertNotIn('queue_work(', guard)
        self.assertLess(text.index('lsf_factory_cleanup_worker_operation_current()'), text.index('helper_lock()'))
        self.assertLess(text.index('lsf_factory_cleanup_worker_operation_current()'), text.index('if (!sub_info->path)'))
        free = source.definition('freeinfo')
        self.assertLess(free.index('(*info->cleanup)(info)'), free.index('kfree(info)'))
        self.assertIn('queue_work(system_unbound_wq, &sub_info->work)', source.definition('exec'))
        self.assertIn('user_mode_thread(', source.definition('exec_work'))
        self.assertIn('user_mode_thread(', source.definition('exec_sync'))
        self.assertIn('kernel_execve(', source.definition('exec_async'))


if __name__ == '__main__':
    unittest.main()
