/* SPDX-License-Identifier: GPL-2.0-only */
/* The original embedded worker is NEVER passed to ordinary kfree. */
void lsf_prepaid_cleanup_worker_destroy_full(void)
{
    struct lsf_cleanup_task_source source;
    struct kthread_worker *worker;
    struct task_struct *task;
    if (lsf_factory_cleanup_worker_stop_take(&source, &worker, &task) != 1)
        return;
    kthread_flush_worker(worker);
    kthread_stop(task);
    if (WARN_ON(!list_empty(&worker->delayed_work_list)) ||
        WARN_ON(!list_empty(&worker->work_list))) {
        lsf_factory_cleanup_stack_poison(source);
        /* Real stop continuation still receives its actual put. Quarantine
         * prevents physical view return after the malformed worker state. */
        put_task_struct(task);
        return;
    }
    lsf_factory_cleanup_worker_stopped(source); /* LAST worker/request access. */
    put_task_struct(task); /* May trigger actual final Task return; no later read. */
}

#if defined(CONFIG_X86_64) && defined(CONFIG_IRQ_WORK) && !defined(CONFIG_PREEMPT_RT)
int lsf_prepaid_cleanup_request_irq_quiesce(struct lsf_cleanup_task_source source)
{
    int phase;
    if (current != kthreadd_task || in_interrupt() || irqs_disabled() ||
        !lsf_cleanup_irq_source_equal(source, lsf_cleanup_irq_hint.source) ||
        atomic_read(&lsf_cleanup_irq_hint.uncertain))
        return -EIO;
    phase = atomic_read_acquire(&lsf_cleanup_irq_hint.phase);
    if (phase != LSF_CLEANUP_IRQ_ABORTED && phase != LSF_CLEANUP_IRQ_CONSUMED)
        return -EIO;
    /* ABORTED was never armed/queued. CONSUMED already followed the actual
     * callback+sync. Synchronize the real descriptor here as the final request
     * boundary too; never infer BUSY-clear from callback notification alone. */
    irq_work_sync(&lsf_cleanup_irq_hint.request->retire_irq);
    return atomic_read(&lsf_cleanup_irq_hint.uncertain) ? -EIO : 0;
}
#else
int lsf_prepaid_cleanup_request_irq_quiesce(struct lsf_cleanup_task_source source)
{
    (void)source;
    return -EOPNOTSUPP;
}
#endif
