"""Closed relay source boundaries; no real IRQ/task/hotplug qualification."""
import unittest
from tools import host_stream_kernel_cleanup_irq as source


class CleanupIrqSource(unittest.TestCase):
    def test_fixed_original_origin_and_runtime_gates_stay_closed(self):
        value = source.preimages()
        self.assertEqual(len(value['sections']), 8)
        for name in ('actualNmiExecution', 'cpuHotplugQualified',
                'irqBootstrapOwnerQualified', 'completeAllocationClosure', 'productionInstallation'):
            self.assertFalse(value[name])
        with self.assertRaisesRegex(ValueError, 'cleanup-irq-whole-membership'):
            source.transform({}, {})

    def test_selected_primitive_has_local_queue_and_real_postcallback_epilogue(self):
        value = source.preimages()['sections']
        self.assertIn('__irq_work_queue_local(work);', value['queue']['text'])
        self.assertNotIn('irq_work_queue_on(', value['queue']['text'])
        actual = value['single']['text']
        self.assertLess(actual.index('work->func(work);'), actual.index('atomic_cmpxchg('))
        self.assertIn('lockdep_assert_irqs_enabled();', value['sync']['text'])
        self.assertIn('while (irq_work_is_busy(work))', value['sync']['text'])

    def test_fast_hook_never_takes_record_vm_rq_locks_or_reads_task_fields(self):
        text = (source.OWNED / 'kernel-cleanup-irq.c').read_text()
        fast = text.split('int lsf_prepaid_cleanup_stack_release(struct task_struct *task)\n', 1)[1]
        fast = fast.split('int lsf_prepaid_cleanup_irq_pending(void)', 1)[0]
        for forbidden in ('spin_lock(', 'spin_lock_irqsave(', 'task->',
                'lsf_factory_', 'wake_up_process(', 'put_task_struct(', 'tryget_task_struct(',
                'irq_work_queue_on('):
            self.assertNotIn(forbidden, fast)
        self.assertEqual(fast.count('irq_work_queue(&lsf_cleanup_irq_hint.request->retire_irq)'), 1)
        self.assertLess(fast.index('task != lsf_cleanup_irq_hint.task'),
            fast.index('irq_work_queue(&lsf_cleanup_irq_hint.request->retire_irq)'))
        self.assertLess(fast.index('atomic_cmpxchg('),
            fast.index('irq_work_queue(&lsf_cleanup_irq_hint.request->retire_irq)'))

    def test_callback_only_signals_and_process_sync_precedes_original_capture(self):
        text = (source.OWNED / 'kernel-cleanup-irq.c').read_text()
        callback = text.split('static void lsf_cleanup_irq_notify', 1)[1]
        callback = callback.split('int lsf_prepaid_cleanup_irq_prepare', 1)[0]
        for forbidden in ('lsf_factory_', 'put_task_struct(', 'stack_capture', 'spin_lock'):
            self.assertNotIn(forbidden, callback)
        consume = text.split('void lsf_prepaid_cleanup_irq_drain(void)\n', 1)[1].split('#else', 1)[0]
        self.assertLess(consume.index('irq_work_sync('),
            consume.index('lsf_prepaid_cleanup_stack_capture_deferred(task)'))
        self.assertLess(consume.index('LSF_CLEANUP_IRQ_CONSUMED'),
            consume.index('lsf_prepaid_cleanup_retire_one();'))
        self.assertNotIn('spin_lock', consume)

    def test_real_continuation_reference_and_all_generations_are_required_before_arm(self):
        text = (source.OWNED / 'factory-cleanup-irq.c').read_text()
        self.assertLess(text.index('lsf_cleanup_lifecycle_identity_locked(source, task)'),
            text.index('task->worker_private'))
        self.assertIn('bytes > LSF_FACTORY_INFRA_BYTES', text)
        self.assertIn('request->bytes != (((lsf_u64)bytes + 63u) & ~(lsf_u64)63u)', text)
        self.assertIn('metadata->cache_anchor != source.task.generation', text)
        self.assertIn('factory.device->cleanup_retire_task == task', text)
        self.assertIn('refcount_read(&task->usage) >= 1', text)
        relay = (source.OWNED / 'kernel-cleanup-irq.c').read_text()
        self.assertIn('lsf_factory_cleanup_irq_published(source, task)', relay)
        self.assertIn('!arch_irq_work_has_interrupt()', relay)
        self.assertNotIn('atomic_set(&lsf_cleanup_irq_hint.phase, LSF_CLEANUP_IRQ_EMPTY)', relay)

    def test_original_ordinary_free_and_actual_irq_algorithms_are_not_replaced(self):
        text = source.FIXTURE.read_text()
        self.assertIn('irq_work_claim', text)
        self.assertIn('smpcfd_dying_cpu', text)
        implementation = (source.OWNED / 'kernel-cleanup-irq.c').read_text()
        self.assertNotIn('void irq_work_single(', implementation)
        self.assertNotIn('void irq_work_sync(', implementation)
        self.assertNotIn('alloc_pages(', implementation)
        self.assertNotIn('kfree(', implementation)
        self.assertNotIn('synchronize_net(', implementation)


if __name__ == '__main__':
    unittest.main()
