"""Finite source controls: real original references, colors and ordered slots."""
import re
import unittest
from tools import host_stream_kernel_cleanup_provider_executor as source
from tools.host_stream_kernel_device_security import function


class CleanupProviderExecutorSource(unittest.TestCase):
    def test_unselected_whole_source_and_no_constructor_guard_widening(self):
        value = source.preimages()
        self.assertEqual(len(value['source']), 5)
        for key in ('providerCreated', 'taskCreated', 'queueMigrationExecuted',
                    'queueLifetimeRegistered', 'physicalRetirementQualified', 'constructorFunctionGuardWidened'):
            self.assertFalse(value[key])
        with self.assertRaisesRegex(ValueError, 'cleanup-provider-executor-whole-membership'):
            source.transform({}, {})

    def test_three_whole_ordinary_bodies_project_exactly(self):
        for name, modified in [('put_pwq', source.put_pwq()), ('get_unbound_pool', source.get_unbound_pool()),
                               ('apply_prepare', source.apply_prepare())]:
            ordinary = re.sub(r'#ifdef CONFIG_LSF_STREAM_FACTORY\n.*?#endif\n', '', modified, flags=re.S)
            self.assertEqual(ordinary, source.definition(name))
        pool = source.get_unbound_pool()
        self.assertLess(pool.index('lsf_factory_cleanup_provider_pool_address(pool)'),
            pool.index('wqattrs_equal(pool->attrs, attrs)'))
        prepare = source.apply_prepare()
        self.assertLess(prepare.index('return ERR_PTR(-ENOMEM)'), prepare.index('ctx = kzalloc('))

    def test_real_drop_notification_precedes_actual_decrement(self):
        drop = source.put_pwq()
        self.assertLess(drop.index('lockdep_assert_held(&pwq->pool->lock)'),
            drop.index('lsf_prepaid_cleanup_provider_pwq_drop(pwq)'))
        self.assertLess(drop.index('lsf_prepaid_cleanup_provider_pwq_drop(pwq)'), drop.index('--pwq->refcnt'))
        text = (source.OWNED/'workqueue-cleanup-provider-executor.c').read_text()
        notify = function(text, 'void lsf_prepaid_cleanup_provider_pwq_drop(')
        self.assertIn('pwq->refcnt == 2', notify)
        self.assertIn('kthread_queue_work(pwq_release_worker, &control->handoff)', notify)
        self.assertNotIn('alloc', notify)

    def test_manual_park_requires_all_real_refs_colors_and_rcu(self):
        text = (source.OWNED/'workqueue-cleanup-provider-executor.c').read_text()
        quiet = function(text, 'static bool lsf_provider_pwq_quiescent_locked(')
        for token in ('pwq->refcnt != 1', 'pwq->nr_active', 'pwq->inactive_works',
                      'pwq->flush_color != -1', 'pwq->pending_node', 'WORK_NR_COLORS', 'pwq->nr_in_flight[color]'):
            self.assertIn(token, quiet)
        handoff = function(text, 'static void lsf_provider_park_handoff(')
        self.assertEqual(handoff.count('synchronize_rcu();'), 2)
        self.assertLess(handoff.index('synchronize_rcu();'), handoff.index('lsf_provider_pwq_quiescent_locked(original)'))
        self.assertLess(handoff.index('lsf_provider_pwq_quiescent_locked(original)'), handoff.index('list_del_rcu('))
        self.assertLess(handoff.index('list_del_rcu('), handoff.index('unplug_oldest_pwq(wq)'))
        self.assertLess(handoff.rindex('synchronize_rcu();'), handoff.index('INIT_LIST_HEAD('))
        self.assertNotIn('kfree(', handoff)
        self.assertNotIn('complete(', handoff)

    def test_restore_uses_real_borrowed_original_without_allocation(self):
        text = (source.OWNED/'workqueue-cleanup-provider-executor.c').read_text()
        restore = function(text, 'static int lsf_provider_ordered_restore(')
        for token in ('lsf_factory_cleanup_provider_control_current(candidate)',
                      'LSF_PROVIDER_CONTEXT, context', 'LSF_PROVIDER_QUEUE_LIVE',
                      'lsf_provider_pwq_quiescent_locked(original)', 'get_pwq(original)',
                      'original->plugged = true', 'install_unbound_pwq(wq, cpu, original)',
                      'install_unbound_pwq(wq, -1, original)', 'put_pwq_unlocked(original)'):
            self.assertIn(token, restore)
        for forbidden in ('kmalloc(', 'kzalloc(', 'alloc_unbound_pwq(', 'get_unbound_pool(', 'context = NULL'):
            self.assertNotIn(forbidden, restore)

    def test_finite_worker_cannot_enter_original_spare_allocator_retry(self):
        original = source.definition('worker_thread')
        private = source.worker_thread()
        self.assertIn('manage_workers(worker)', original)
        self.assertNotIn('manage_workers(worker)', private)
        self.assertLess(private.index('lsf_provider_worker_entry(__worker)'), private.index('pool = worker->pool'))
        for token in ('lsf_provider_single_worker_locked(worker, pool)', 'worker_enter_idle(worker)',
                      'set_current_state(TASK_UNINTERRUPTIBLE)', 'goto woke_up', 'process_scheduled_works(worker)',
                      'ida_free(&pool->worker_ida, worker->id)', 'set_pf_worker(false)'):
            self.assertIn(token, private)
        text = (source.OWNED/'workqueue-cleanup-provider-executor.c').read_text()
        finite = function(text, 'static bool lsf_provider_single_worker_locked(')
        for token in ('pool->nr_workers == 1', 'list_is_singular(&pool->workers)',
                      'pool->workers.next == &worker->node', 'pwq->wq == control->wq',
                      'READ_ONCE(control->wq->max_active) == 1', 'worker->task == current'):
            self.assertIn(token, finite)

    def test_complete_six_part_admission_before_first_birth_or_write(self):
        text = (source.OWNED/'factory-cleanup-provider-executor.c').read_text()
        reserve = function(text, 'int lsf_factory_cleanup_provider_storage_reserve(')
        self.assertLess(reserve.index('lsf_prepaid_cleanup_provider_part_geometry('),
            reserve.index('spin_lock_irqsave('))
        self.assertLess(reserve.index('empty < LSF_PROVIDER_PARTS'), reserve.index('lsf_device_allocate('))
        self.assertLess(reserve.index('lsf_device_allocate('), reserve.index('memset('))
        self.assertIn('LSF_DEVICE_CLEANUP_PROVIDER_POOL', text)
        self.assertIn('storage->tickets[LSF_PROVIDER_POOL] : source.root', reserve)
        self.assertNotIn('kmalloc(', reserve)
        self.assertNotIn('alloc_pages(', reserve)


if __name__ == '__main__':
    unittest.main()
