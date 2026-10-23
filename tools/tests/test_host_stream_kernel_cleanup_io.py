"""Actual non-ICQ I/O-context construction and target ownership boundaries."""
import unittest
from tools import host_stream_kernel_cleanup_io as source
from tools.host_stream_kernel_device_security import function


class CleanupIoSource(unittest.TestCase):
    def test_exact_git_sources_and_actual_selected_configuration(self):
        value = source.preimages()
        self.assertEqual(len(value['source']), 3)
        self.assertEqual(value['source']['selected.config']['sha256'],
            'b2bcccd5507f3f3a673690b660a2321870b57a3c77e72ce8532975f3c4752176')
        self.assertIn('gitBlob', value['source']['block/blk-ioc.c'])
        self.assertIn('gitBlob', value['source']['include/linux/iocontext.h'])
        self.assertFalse(value['runtimeIoExecution'])
        self.assertFalse(value['fullConstructorClosure'])
        with self.assertRaisesRegex(ValueError, 'cleanup-io-whole-membership'):
            source.transform({}, {})

    def test_full_original_allocator_initialization_and_inverse(self):
        actual = function(source.private_io(), 'static struct io_context *lsf_cleanup_alloc_io_context(')
        original = source.definition('alloc_io_context')
        self.assertEqual(actual[actual.index('\tif (unlikely(!ioc))'):],
            original[original.index('\tif (unlikely(!ioc))'):])
        actual = source.replace(actual,
            'static struct io_context *lsf_cleanup_alloc_io_context(struct task_struct *target,\n'
            '    gfp_t gfp_flags, int node)\n',
            'static struct io_context *alloc_io_context(gfp_t gfp_flags, int node)\n')
        actual = source.replace(actual, '\tvoid *address;\n\tint origin;\n', '')
        actual = source.replace(actual,
            '\torigin = lsf_factory_cleanup_io_reserve(target, sizeof(*ioc), __alignof__(*ioc), &address);\n'
            '\tif (!origin)\n\t\treturn alloc_io_context(gfp_flags, node);\n'
            '\tif (origin < 0)\n\t\treturn NULL;\n\tioc = address;\n',
            '\tioc = kmem_cache_alloc_node(iocontext_cachep, gfp_flags | __GFP_ZERO,\n'
            '\t\t\t\t    node);\n')
        self.assertEqual(actual, original)

    def test_actual_parent_lock_bounds_scalar_ioprio_snapshot(self):
        text = function(source.private_io(), 'int lsf_prepaid_cleanup_copy_io(')
        lock = text.index('task_lock(current)')
        read = text.index('ioprio = ioc->ioprio')
        unlock = text.index('task_unlock(current)')
        self.assertLess(lock, read)
        self.assertLess(read, unlock)
        self.assertEqual(text.count('ioc->ioprio'), 1)
        self.assertLess(text.index('clone_flags != LSF_CLEANUP_CLONE_FLAGS'), lock)
        self.assertIn('IS_ENABLED(CONFIG_BLK_ICQ)', text[:lock])
        self.assertIn('ioprio_valid(ioprio)', text)
        self.assertIn('tsk->io_context->ioprio = ioprio;', text)
        self.assertNotIn('tsk->io_context = alloc_io_context(', text)

    def test_original_ioprio_permissions_and_final_reference_boundary(self):
        original = source.definition('set_task_ioprio')
        self.assertLess(original.index('security_task_setioprio(task, ioprio)'),
            original.index('alloc_io_context(GFP_ATOMIC, NUMA_NO_NODE)'))
        self.assertIn('if (task->flags & PF_EXITING)', original)
        self.assertIn('if (task->io_context)', original)
        put = source.definition('put_io_context')
        self.assertLess(put.index('atomic_long_dec_and_test(&ioc->refcount)'),
            put.index('kmem_cache_free(iocontext_cachep, ioc)'))

    def test_typed_bank_failure_cannot_fall_through_to_slub(self):
        allocate = function(source.private_io(), 'static struct io_context *lsf_cleanup_alloc_io_context(')
        self.assertIn('if (!origin)\n\t\treturn alloc_io_context(gfp_flags, node);', allocate)
        self.assertIn('if (origin < 0)\n\t\treturn NULL;', allocate)
        actual = (source.OWNED / 'factory-cleanup-io.c').read_text()
        self.assertLess(actual.index('target != task'), actual.index('refcount_read(&task->usage)'))
        self.assertLess(actual.index('source.task, &ticket, &offset'), actual.index('memset(*address, 0, bytes)'))
        self.assertIn('cleanup_child_attempted & (1u << LSF_CLEANUP_IO_CONTEXT)', actual)
        self.assertIn('result = 1;', actual)
        self.assertIn('factory.device->cleanup_final_phase != LSF_CLEANUP_FINAL_NONE', actual)
        for forbidden in ('kmalloc(', 'kmem_cache_alloc(', 'get_task_struct(', 'put_task_struct('):
            self.assertNotIn(forbidden, actual)


if __name__ == '__main__':
    unittest.main()
