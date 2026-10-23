"""Creator/opener handoff and physical request-return prerequisites."""
import unittest
from tools import host_stream_kernel_cleanup_close as source
from tools import host_stream_kernel_cleanup_clone as clone
from tools.host_stream_kernel_device_security import function


class CleanupCloseSource(unittest.TestCase):
    def test_real_stop_flush_and_no_execution_claim(self):
        value = source.preimages()
        self.assertIn('wait_for_completion(&kthread->exited)', value['sections']['stop']['text'])
        self.assertIn('kthread_flush_worker(worker)', value['sections']['destroy_worker']['text'])
        self.assertFalse(value['actualWorkerStop'])
        self.assertFalse(value['fullConstructorClosure'])
        with self.assertRaisesRegex(ValueError, 'cleanup-close-whole-membership'):
            source.transform({}, {})

    def test_creator_error_and_success_release_after_last_request_access(self):
        text = source.creator(clone.private_creator())
        self.assertLess(text.index('lsf_factory_cleanup_creator_error(source)'), text.index('if (!done)'))
        self.assertEqual(text.count('LSF_CLEANUP_REQUEST_CREATOR'), 3)
        self.assertLess(text.index('create->result = ERR_PTR(pid)'),
            text.index('LSF_CLEANUP_REQUEST_CREATOR', text.index('create->result = ERR_PTR(pid)')))
        tail = text[text.index('create->result = ERR_PTR(pid)'):]
        self.assertLess(tail.index('LSF_CLEANUP_REQUEST_CREATOR'), tail.index('complete(done)'))
        self.assertNotIn('create->', tail[tail.index('complete(done)'):])

    def test_interrupted_opener_and_result_copy_before_release(self):
        text = source.opener(source.preimages()['parentSections']['worker_create']['text'])
        self.assertEqual(text.count('LSF_CLEANUP_REQUEST_OPENER'), 3)
        interrupted = text[text.index('if (xchg(&owned->create.done, NULL))'):text.index('wait_for_completion(&done)')]
        self.assertLess(interrupted.index('LSF_CLEANUP_REQUEST_OPENER'), interrupted.index('return -EINTR'))
        error = text[text.index('if (IS_ERR(task))'):text.index('/* The REAL running entry')]
        self.assertLess(error.index('error = PTR_ERR(task)'), error.index('LSF_CLEANUP_REQUEST_OPENER'))
        self.assertLess(text.index('lsf_factory_cleanup_worker_associate('), text.index('wake_up_process(task)'))
        self.assertLess(text.index('wake_up_process(task)'), text.rindex('LSF_CLEANUP_REQUEST_OPENER'))
        self.assertNotIn('owned->', text[text.rindex('LSF_CLEANUP_REQUEST_OPENER'):])

    def test_stop_reference_and_no_task_access_after_stopped(self):
        factory = (source.OWNED/'factory-cleanup-close.c').read_text()
        take = function(factory, 'int lsf_factory_cleanup_worker_stop_take(')
        self.assertLess(take.index('lsf_cleanup_lifecycle_identity_locked(*source, *task)'),
            take.index('tryget_task_struct(*task)'))
        # Real child completion can precede kthreadd's clone tail. Creator is
        # allowed to finish while close stops the worker; only opener is done.
        self.assertIn('cleanup_request_users & LSF_CLEANUP_REQUEST_OPENER', take)
        kernel = function((source.OWNED/'kernel-cleanup-close.c').read_text(),
            'void lsf_prepaid_cleanup_worker_destroy_full(')
        self.assertLess(kernel.index('kthread_flush_worker(worker)'), kernel.index('kthread_stop(task)'))
        tail = kernel[kernel.index('lsf_factory_cleanup_worker_stopped(source)'):]
        self.assertIn('put_task_struct(task)', tail)
        self.assertNotIn('task->', tail)
        self.assertNotIn('worker->', tail)
        self.assertNotIn('kfree(worker)', kernel)

    def test_request_waits_for_real_returned_birth_and_irq_epilogue(self):
        factory = (source.OWNED/'factory-cleanup-close.c').read_text()
        ready = function(factory, 'static int lsf_cleanup_request_ready_locked(')
        for token in ('cleanup_request_users', 'LSF_CLEANUP_TASK_RETURNED',
                      'LSF_CLEANUP_FINAL_RETURNED', 'cleanup_worker_stop != 2u',
                      'task->phase == LSF_PREPAID_RETURNED', 'task->generation == source.task.generation'):
            self.assertIn(token, ready)
        # Here task is explicitly metadata, never the former task_struct.
        self.assertIn('struct lsf_prepaid_view *task', ready)
        self.assertNotIn('refcount_read', ready)
        drain = function(factory, 'void lsf_factory_cleanup_request_drain(')
        self.assertLess(drain.index('spin_unlock_irqrestore(&pool_lock, flags)'),
            drain.index('lsf_prepaid_cleanup_request_irq_quiesce(source)'))
        self.assertLess(drain.index('lsf_prepaid_cleanup_request_irq_quiesce(source)'),
            drain.index('lsf_device_finish('))
        irq = function((source.OWNED/'kernel-cleanup-close.c').read_text().split('#else')[0],
            'int lsf_prepaid_cleanup_request_irq_quiesce(')
        self.assertIn('LSF_CLEANUP_IRQ_ABORTED', irq)
        self.assertIn('LSF_CLEANUP_IRQ_CONSUMED', irq)
        self.assertIn('irq_work_sync(&lsf_cleanup_irq_hint.request->retire_irq)', irq)

    def test_normal_close_and_expected_open_error_keep_authentic_drains(self):
        original = source.preimages()['parentSections']
        combined = original['factory_open']['text'] + '\n' + original['factory_release']['text']
        text = source.factory_close(combined)
        release = function(text, 'static int lsf_factory_release(')
        self.assertNotIn('factory.uncertain', release)
        self.assertLess(release.index('lsf_cleanup_admission_close()'),
            release.index('mutex_unlock(&factory_lock)'))
        self.assertLess(release.index('mutex_unlock(&factory_lock)'),
            release.index('lsf_prepaid_cleanup_worker_destroy_full()'))
        self.assertLess(release.index('lsf_prepaid_cleanup_worker_destroy_full()'),
            release.index('lsf_prepaid_cleanup_sidcache_drain()'))
        opening = function(text, 'static int lsf_factory_open(')
        error = opening[opening.index('error = lsf_prepaid_cleanup_worker_create()'):]
        self.assertNotIn('WRITE_ONCE(factory.uncertain', error)
        self.assertIn('lsf_cleanup_admission_close()', error)
        self.assertLess(error.index('mutex_unlock(&factory_lock)'),
            error.index('lsf_prepaid_cleanup_worker_destroy_full()'))
        # Existing true corruption still sets sticky uncertainty.
        self.assertIn('WRITE_ONCE(factory.uncertain, 1)', opening[:opening.index('factory.mm = current->mm')])

    def test_born_request_survives_close_but_closed_admission_cannot_claim_task(self):
        lookup = source.request_lookup((source.OWNED/'factory-cleanup-clone.c').read_text())
        self.assertNotIn('factory.pool.stopped', lookup)
        self.assertNotIn('.closed', lookup)
        for token in ('current != kthreadd_task', 'lsf_factory_cleanup_task_source_locked(actual)',
                      'cleanup_task_claimed', 'LSF_CLEANUP_UNINITIALIZED',
                      'address != (const char *)page_address(factory.pages) + request->offset'):
            self.assertIn(token, lookup)
        claim = function((source.OWNED/'factory-cleanup-task.c').read_text(),
            'struct task_struct *lsf_factory_cleanup_task_claim(')
        self.assertLess(claim.index('factory.pool.stopped'), claim.index('cleanup_task_claimed = 1'))
        self.assertLess(claim.index('.closed'), claim.index('cleanup_task_claimed = 1'))


if __name__ == '__main__':
    unittest.main()
