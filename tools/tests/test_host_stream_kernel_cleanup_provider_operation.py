"""Exact physical/operation separation, ordinary projection and refusal fences."""
import re
import unittest
from tools import host_stream_kernel_cleanup_provider_operation as source
from tools.host_stream_kernel_device_security import function


class CleanupProviderOperationSource(unittest.TestCase):
    def test_actual_source_and_unselected_extent(self):
        value = source.preimages()
        self.assertEqual(len(value['source']), 3)
        self.assertFalse(value['providerCreated'])
        self.assertFalse(value['physicalRoleBound'])
        self.assertFalse(value['dispatchExecuted'])
        with self.assertRaisesRegex(ValueError, 'cleanup-provider-operation-whole-membership'):
            source.transform({}, {})

    def test_complete_original_dispatch_projects_exactly(self):
        modified = source.process_one_work()
        ordinary = re.sub(r'#ifdef CONFIG_LSF_STREAM_FACTORY\n.*?#endif\n', '', modified, flags=re.S)
        original = source.preimages()['sections']['process_one_work']['text']
        self.assertEqual(ordinary, original)
        self.assertLess(modified.index('raw_spin_unlock_irq(&pool->lock)'),
            modified.index('lsf_factory_cleanup_provider_dispatch_begin()'))
        self.assertLess(modified.index('lsf_factory_cleanup_provider_dispatch_begin()'),
            modified.index('worker->current_func(work)'))
        self.assertLess(modified.index('worker->current_func(work)'),
            modified.index('lsf_factory_cleanup_provider_dispatch_end()'))
        self.assertLess(modified.index('lsf_factory_cleanup_provider_dispatch_end()'),
            modified.index('trace_workqueue_execute_end('))

    def test_physical_identity_is_retained_read_only_not_admission(self):
        text = (source.OWNED/'factory-cleanup-provider-operation.c').read_text()
        physical = function(text, 'static int lsf_cleanup_provider_physical_locked(')
        self.assertLess(physical.index('address != base + task->offset'),
            physical.index('refcount_read(&current->usage)'))
        for forbidden in ('factory.uncertain', 'factory.pool.poisoned', 'cleanup_lifecycle',
                          'lsf_device_allocate(', 'lsf_cleanup_lifecycle_poison_locked('):
            self.assertNotIn(forbidden, physical)
        for token in ('root->phase != LSF_PREPAID_LIVE', 'request->phase != LSF_PREPAID_LIVE',
                      'task->phase != LSF_PREPAID_LIVE', 'source->owner.generation',
                      'factory.device != (void *)(base + root->offset)', 'LSF_CLEANUP_PHYSICAL_PROVIDER'):
            self.assertIn(token, physical)

    def test_snapshot_derives_actual_same_task_fields_after_full_birth(self):
        text = (source.OWNED/'workqueue-cleanup-provider-operation.c').read_text()
        self.assertLess(text.index('lsf_factory_cleanup_provider_snapshot_source(source,'),
            text.index('READ_ONCE(worker->task)'))
        for token in ('READ_ONCE(worker->task) != current', 'READ_ONCE(worker->pool) != actual_pool',
                      'READ_ONCE(worker->current_work)', 'READ_ONCE(worker->current_func)', '!in_task()'):
            self.assertIn(token, text)
        for forbidden in ('kthread_data(', 'worker_private', 'current->comm', 'spin_lock', 'kmalloc('):
            self.assertNotIn(forbidden, text)

    def test_only_authenticated_dispatch_tuple_is_operation_authority(self):
        text = (source.OWNED/'factory-cleanup-provider-operation.c').read_text()
        begin = function(text, 'void lsf_factory_cleanup_provider_dispatch_begin(void)')
        end = function(text, 'void lsf_factory_cleanup_provider_dispatch_end(void)')
        current = function(text, 'int lsf_factory_cleanup_provider_operation_current(void)')
        self.assertIn('lsf_prepaid_cleanup_provider_snapshot(source, &work, &function)', begin)
        self.assertLess(begin.index('cleanup_operation_function = function'),
            begin.index('cleanup_operation_active = 1u'))
        self.assertNotIn('lsf_prepaid_cleanup_provider_snapshot(', end)
        self.assertIn('cleanup_operation_work = NULL', end)
        self.assertIn('cleanup_operation_function = NULL', end)
        # Ordinary work/idle must stay ordinary even when Root is quarantined.
        self.assertLess(current.index('if (!factory.device->cleanup_operation_active)'),
            current.index('factory.pool.poisoned'))
        self.assertLess(current.index('address < base || address - base >= LSF_BACKING_BYTES'),
            current.index('factory.pool.poisoned'))
        for token in ('LSF_PREPAID_LIVE', 'LSF_PREPAID_QUEUED', 'owned->putting',
                      'lsf_factory_device_firmware_put', 'lsf_factory_device_firmware_pci(',
                      'lsf_factory_device_firmware_for_pci(', 'result = -EIO'):
            self.assertIn(token, current)

    def test_physical_binding_is_before_claim_and_not_generic_function_admission(self):
        text = (source.OWNED/'factory-cleanup-provider-operation.c').read_text()
        bind = function(text, 'int lsf_factory_cleanup_provider_bind(')
        for token in ('cleanup_task_claimed', 'LSF_CLEANUP_UNINITIALIZED',
                      'lsf_factory_cleanup_task_source_locked(source)', 'current->mm != factory.mm',
                      'pool->cache_bucket != source.root.slot', 'worker->cache_bucket != pool_ticket.slot',
                      'LSF_PREPAID_PRIVATE'):
            self.assertIn(token, bind)
        self.assertLess(bind.index('cleanup_provider_worker = worker_ticket'),
            bind.index('cleanup_physical_role = LSF_CLEANUP_PHYSICAL_PROVIDER'))
        # This source piece does not widen any existing constructor function guard.
        self.assertNotIn('kernel_clone(', text)
        self.assertNotIn('kthread_create(', text)


if __name__ == '__main__':
    unittest.main()
