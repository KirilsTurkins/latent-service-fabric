"""Complete real clone/wake/PID and create-completion caller tails."""
import unittest
from tools import host_stream_kernel_cleanup_clone as source
from tools.host_stream_kernel_device_security import function


class CleanupCloneSource(unittest.TestCase):
    def test_actual_kthreadd_mm_profile_precedes_request_birth_read(self):
        text = (source.OWNED/'kernel-cleanup-clone.c').read_text()
        self.assertLess(text.index('current->mm'), text.index('lsf_factory_cleanup_constructor_request('))
    def test_source_and_disconnected_consumer_are_explicit(self):
        value = source.preimages()
        self.assertEqual(len(value['sections']), 3)
        for name in ('taskCreated', 'executorReady', 'pendingConsumerCallsFullClone',
                'observerClosure', 'bootstrapQualified', 'fullConstructorClosure'):
            self.assertFalse(value[name])
        with self.assertRaisesRegex(ValueError, 'cleanup-clone-whole-membership'):
            source.transform({}, {})

    def test_full_original_clone_tail_and_inverse_are_exact(self):
        actual = function(source.private_clone(), 'pid_t lsf_prepaid_cleanup_kernel_clone(')
        original = source.definition('kernel_clone')
        self.assertEqual(actual[actual.index('\tadd_latent_entropy();\n'):],
            original[original.index('\tadd_latent_entropy();\n'):])
        actual = source.replace(actual,
            'pid_t lsf_prepaid_cleanup_kernel_clone(struct lsf_cleanup_task_source source,\n'
            '    struct kernel_clone_args *args)\n',
            'pid_t kernel_clone(struct kernel_clone_args *args)\n')
        actual = source.replace(actual, '\tu64 clone_flags = args ? args->flags : 0;\n',
            '\tu64 clone_flags = args->flags;\n')
        actual = source.replace(actual,
            '\n\tif (!lsf_prepaid_cleanup_clone_args_current(source, args))\n\t\treturn -EOPNOTSUPP;\n', '')
        actual = source.replace(actual,
            '\tp = lsf_prepaid_cleanup_copy_process(source, args, NUMA_NO_NODE);\n',
            '\tp = copy_process(NULL, trace, NUMA_NO_NODE, args);\n')
        self.assertEqual(actual, original)

    def test_full_original_kernel_thread_flag_translation_is_exact(self):
        actual = function(source.private_clone(), 'pid_t lsf_prepaid_cleanup_kernel_thread(')
        actual = source.replace(actual,
            'pid_t lsf_prepaid_cleanup_kernel_thread(struct lsf_cleanup_task_source source,\n'
            '    int (*fn)(void *), void *arg, const char *name, unsigned long flags)\n',
            'pid_t kernel_thread(int (*fn)(void *), void *arg, const char *name,\n'
            '\t\t    unsigned long flags)\n')
        actual = source.replace(actual, '\treturn lsf_prepaid_cleanup_kernel_clone(source, &args);\n',
            '\treturn kernel_clone(&args);\n')
        self.assertEqual(actual, source.definition('kernel_thread'))

    def test_actual_child_completes_success_and_creator_only_completes_error(self):
        actual = source.private_creator()
        self.assertLess(actual.index('lsf_factory_cleanup_constructor_request('),
            actual.index('current->pref_node_fork = create->node'))
        error = actual[actual.index('\tif (pid < 0) {'):]
        self.assertEqual(actual.count('complete(done)'), 1)
        self.assertIn('xchg(&create->done, NULL)', error)
        self.assertLess(error.index('create->result = ERR_PTR(pid)'), error.index('complete(done)'))
        for forbidden in ('kfree(', 'wake_up_new_task(', 'create->result = current'):
            self.assertNotIn(forbidden, actual)
        self.assertIn('lsf_prepaid_cleanup_kthread_entry', actual)

    def test_request_birth_precedes_request_fields_and_alias_checks(self):
        text = (source.OWNED / 'kernel-cleanup-clone.c').read_text()
        self.assertLess(text.index('lsf_factory_cleanup_constructor_request('),
            text.index('owned = address;'))
        self.assertLess(text.index('owned = address;'), text.index('owned->source'))
        for field in ('args->fn_arg == &owned->create', 'args->name == owned->name',
                'owned->create.data == &owned->worker', 'owned->create.threadfn == kthread_worker_fn'):
            self.assertIn(field, text)
        factory = (source.OWNED / 'factory-cleanup-clone.c').read_text()
        self.assertIn('factory.device->cleanup_task_claimed', factory)
        self.assertIn('factory.device->cleanup_lifecycle != LSF_CLEANUP_UNINITIALIZED', factory)
        self.assertIn('address != (const char *)page_address(factory.pages) + request->offset', factory)
        for forbidden in ('address->', 'get_task_struct(', 'memset(', 'lsf_device_allocate('):
            self.assertNotIn(forbidden, factory)


if __name__ == '__main__':
    unittest.main()
