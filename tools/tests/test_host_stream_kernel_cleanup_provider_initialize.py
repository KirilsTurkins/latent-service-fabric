"""Source controls for charged alignment, fixed ID0 and actual create handshake."""
import unittest
from tools import host_stream_kernel_cleanup_provider_initialize as source
from tools.host_stream_kernel_device_security import function


class CleanupProviderInitializeSource(unittest.TestCase):
    def test_source_pin_and_qualification_stays_closed(self):
        value = source.preimages()
        self.assertFalse(value['taskCreated'])
        self.assertFalse(value['queueLifetimeRegistered'])
        self.assertEqual(len(value['sections']), 7)
        with self.assertRaisesRegex(ValueError, 'cleanup-provider-initialize-whole-membership'):
            source.transform({}, {})

    def test_charged_alignment_inside_same_original_record_for_every_residue(self):
        text = source.aligned_storage((source.OWNED/'factory-cleanup-provider-executor.c').read_text())
        reserve = function(text, 'int lsf_factory_cleanup_provider_storage_reserve(')
        self.assertLess(reserve.index('charged[i] = bytes[i] + alignment[i] - 1u'),
            reserve.index('lsf_device_allocate('))
        self.assertIn('source.owner, charged[i]', reserve)
        self.assertIn('storage->addresses[i] = (void *)ALIGN(', reserve)
        self.assertIn('bytes > record->bytes - padding', text)
        for alignment in (64, 256, 512, 4096):
            for offset in range(0, alignment, 64):
                for size in (1, 256, 512, 4096):
                    charged = (size + alignment - 1 + 63) & ~63
                    address = (offset + alignment - 1) & ~(alignment - 1)
                    self.assertEqual(address % alignment, 0)
                    self.assertLessEqual(address - offset + size, charged)

    def test_actual_pool_initializer_uses_only_paid_attrs(self):
        text = source.pool_initialize()
        self.assertLess(text.index('lsf_factory_cleanup_provider_birth_current('), text.index('raw_spin_lock_init('))
        for token in ('timer_setup(&pool->idle_timer', 'INIT_WORK(&pool->idle_cull_work',
                      'timer_setup(&pool->mayday_timer', 'ida_init(&pool->worker_ida)',
                      'pool->attrs = attrs', 'cpumask_copy(attrs->cpumask, cpu_possible_mask)',
                      'wqattrs_clear_for_pool(pool->attrs)'):
            self.assertIn(token, text)
        self.assertNotIn('alloc_workqueue_attrs(', text)

    def test_fixed_empty_ida_routes_real_inline_zero_branch(self):
        text = source.worker_create()
        self.assertLess(text.index('!xa_empty(&pool->worker_ida.xa)'), text.index('ida_alloc_range('))
        self.assertIn('ida_alloc_range(&pool->worker_ida, 0, 0, GFP_KERNEL)', text)
        self.assertIn('if (bit < BITS_PER_XA_VALUE)', source.definition('ida_alloc_range'))
        self.assertIn('bitmap = xa_mk_value(1UL << bit)', source.definition('ida_alloc_range'))
        self.assertIn('if (max == 0)', source.definition('xas_expand'))
        self.assertIn('allow_root = !xa_is_node(entry) && !xa_is_zero(entry)', source.definition('xas_store'))
        self.assertIn('while (shift > order)', source.definition('xas_create'))

    def test_actual_task_association_precedes_bind_attach_and_wake(self):
        text = source.worker_create()
        for later in ('set_user_nice(', 'kthread_bind_mask(', 'worker_attach_to_pool(', 'wake_up_process('):
            self.assertLess(text.index('lsf_factory_cleanup_provider_task_associate('), text.index(later))
        self.assertNotIn('kthread_create_on_node(', text)
        self.assertNotIn('kfree(worker)', text)
        self.assertIn('ida_free(&pool->worker_ida, id)', text)

    def test_exact_role_function_and_actual_birth_before_pair_acceptance(self):
        text = (source.OWNED/'factory-cleanup-provider-initialize.c').read_text()
        pair = function(text, 'int lsf_factory_cleanup_thread_pair(')
        for token in ('LSF_CLEANUP_PHYSICAL_PRIVATE', 'function == kthread_worker_fn',
                      'LSF_CLEANUP_PHYSICAL_PROVIDER', 'LSF_PROVIDER_WORKER, NULL, 0',
                      'function == lsf_prepaid_cleanup_provider_worker_thread', 'data == worker'):
            self.assertIn(token, pair)
        associate = function(text, 'int lsf_factory_cleanup_provider_task_associate(')
        self.assertLess(associate.index('lsf_cleanup_lifecycle_identity_locked(source, task)'),
            associate.index('refcount_read(&task->usage)'))

    def test_real_pending_completion_and_last_request_access(self):
        text = (source.OWNED/'kthread-cleanup-provider-initialize.c').read_text()
        self.assertLess(text.index('lsf_factory_cleanup_provider_open_request('), text.index('owned->source'))
        for token in ('WRITE_ONCE(lsf_cleanup_pending, owned)', 'wake_up_process(kthreadd_task)',
                      'wait_for_completion_killable(&done)', 'xchg(&owned->create.done, NULL)',
                      'wait_for_completion(&done)', 'return ERR_PTR(-EINTR)'):
            self.assertIn(token, text)
        self.assertLess(text.index('task = owned->create.result'),
            text.rindex('lsf_factory_cleanup_request_put(source, LSF_CLEANUP_REQUEST_OPENER)'))
        self.assertNotIn('wake_up_process(task)', text)


if __name__ == '__main__':
    unittest.main()
