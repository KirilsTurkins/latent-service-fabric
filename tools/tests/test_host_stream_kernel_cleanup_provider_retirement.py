"""Actual source ordering controls, not runtime or native-free qualification."""
import re
import unittest
from tools import host_stream_kernel_cleanup_provider_retirement as source
from tools.host_stream_kernel_device_security import function


class CleanupProviderRetirementSource(unittest.TestCase):
    def test_fixed_original_source_and_closed_physical_qualification(self):
        value = source.preimages()
        self.assertFalse(value['physicalRetirementQualified'])
        self.assertFalse(value['actualRcuExecution'])
        self.assertEqual(len(value['sections']), 7)

    def test_actual_stop_put_precedes_worker_view_return(self):
        text = source.reap_workers()
        self.assertLess(text.index('lsf_factory_cleanup_provider_part_origin('), text.index('list_del_init('))
        self.assertLess(text.index('lsf_factory_cleanup_provider_part_queue('), text.index('kthread_stop_put('))
        self.assertLess(text.index('kthread_stop_put('), text.index('lsf_factory_cleanup_provider_part_finish('))
        self.assertIn('\t\telse\n#endif\n\t\t\tkfree(worker)', text)

    def test_original_pool_shutdown_and_all_actual_tails_remain(self):
        text = source.put_pool()
        ordinary = re.sub(r'#ifdef CONFIG_LSF_STREAM_FACTORY\n.*?#endif\n', '', text, flags=re.S)
        self.assertEqual(ordinary, source.definition('put_unbound_pool'))
        for token in ('idr_remove(', 'detach_dying_workers(', 'reap_dying_workers(',
                      'del_timer_sync(&pool->idle_timer)', 'cancel_work_sync(&pool->idle_cull_work)',
                      'del_timer_sync(&pool->mayday_timer)', 'call_rcu(&pool->rcu, rcu_free_pool)'):
            self.assertIn(token, text)

    def test_actual_attr_and_pool_destructors_precede_latch(self):
        attrs = source.free_attrs()
        self.assertLess(attrs.index('lsf_factory_cleanup_provider_part_origin('), attrs.index('attrs->cpumask'))
        self.assertLess(attrs.index('free_cpumask_var(attrs->__pod_cpumask)'),
            attrs.index('lsf_factory_cleanup_provider_part_finish('))
        pool = source.free_pool()
        self.assertLess(pool.index('lsf_factory_cleanup_provider_part_origin('), pool.index('ida_destroy('))
        self.assertLess(pool.index('ida_destroy('), pool.index('free_workqueue_attrs('))
        self.assertLess(pool.index('free_workqueue_attrs('), pool.index('lsf_factory_cleanup_provider_pool_destructed('))

    def test_true_zero_reference_queue_and_independent_pwq_rcu_callback(self):
        put = source.put_pwq()
        self.assertLess(put.index('pwq->refcnt == 1'), put.index('--pwq->refcnt'))
        self.assertLess(put.index('lsf_factory_cleanup_provider_part_queue('), put.index('kthread_queue_work('))
        release = source.release_pwq()
        self.assertLess(release.index('lsf_factory_cleanup_provider_part_origin('), release.index('wq = pwq->wq'))
        self.assertLess(release.index('put_unbound_pool(pool)'), release.index('lsf_provider_rcu_free_pwq'))
        self.assertIn('call_rcu(&pwq->rcu, lsf_provider_rcu_free_pwq)', release)
        # Original kthread-worker source explicitly permits return/free inside
        # callback; the trace-end tail uses only the pointer address afterwards.
        original = source.definition('kthread_worker_fn')
        self.assertIn('Avoid dereferencing work after this point.', original)
        self.assertNotIn('work->', original[original.index('trace_sched_kthread_work_execute_end(work, func)'):])

    def test_pool_completion_waits_actual_same_record_children(self):
        text = (source.OWNED/'factory-cleanup-provider-retirement.c').read_text()
        finish = function(text, 'static void lsf_provider_pool_finish_if_ready_locked(')
        for token in ('cleanup_provider_pool_destructed', 'LSF_PREPAID_LIVE',
                      'child->cache_bucket == ticket.slot', 'child->cache_anchor == ticket.generation'):
            self.assertIn(token, finish)
        self.assertLess(finish.index('for (i = 1;'), finish.index('lsf_device_finish('))
        for forbidden in ('children_remaining', 'pending_count', 'pool->nr_workers', 'kfree('):
            self.assertNotIn(forbidden, finish)
        physical = function(text, 'int lsf_factory_cleanup_provider_pool_destructed(')
        self.assertIn('factory.device->cleanup_provider_pool_destructed = 1u', physical)


if __name__ == '__main__':
    unittest.main()
