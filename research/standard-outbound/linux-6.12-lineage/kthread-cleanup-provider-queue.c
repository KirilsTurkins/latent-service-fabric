/* SPDX-License-Identifier: GPL-2.0-only */
/* Cancellation is only for a request which was NEVER submitted. The actual
 * immutable publication latch is checked in the same original Root record. */
int lsf_prepaid_cleanup_provider_irq_abort_opener_locked(struct lsf_cleanup_task_source source,
    struct task_struct *task)
{
#if defined(CONFIG_X86_64) && defined(CONFIG_IRQ_WORK) && !defined(CONFIG_PREEMPT_RT)
    if (in_interrupt() || task != lsf_cleanup_irq_hint.task ||
        !lsf_cleanup_irq_source_equal(source, lsf_cleanup_irq_hint.source) ||
        atomic_read(&lsf_cleanup_irq_hint.uncertain))
        return -EIO;
    return atomic_cmpxchg(&lsf_cleanup_irq_hint.phase, LSF_CLEANUP_IRQ_BORN,
        LSF_CLEANUP_IRQ_ABORTED) == LSF_CLEANUP_IRQ_BORN ? 0 : -EIO;
#else
    (void)source; (void)task;
    return -EOPNOTSUPP;
#endif
}

int lsf_prepaid_cleanup_provider_create_full(void)
{
    struct lsf_cleanup_provider_storage storage;
    struct lsf_cleanup_task_source source;
    void *request;
    unsigned long request_bytes, task_bytes, alignment;
    int error;
    if (IS_ENABLED(CONFIG_DEBUG_LOCK_ALLOC) || !lsf_factory_cleanup_provider_profile_ready() ||
        !lsf_prepaid_cleanup_provider_queue_available())
        return -EOPNOTSUPP;
    error = lsf_prepaid_cleanup_request_geometry(&request_bytes);
    if (!error)
        error = lsf_prepaid_cleanup_task_geometry(&task_bytes, &alignment);
    if (error)
        return error;
    error = lsf_factory_cleanup_task_reserve(request_bytes, task_bytes, alignment, &source, &request);
    if (error)
        return error;
    error = lsf_factory_cleanup_provider_storage_reserve(source, &storage);
    if (error) {
        /* Complete original preflight produced no parts on ordinary ENOMEM.
         * A partial invariant failure already poisoned and retains the bank. */
        (void)lsf_factory_cleanup_provider_cancel_unsubmitted(source);
        return error;
    }
    error = lsf_factory_cleanup_provider_bind(source, storage.tickets[LSF_PROVIDER_POOL],
        storage.tickets[LSF_PROVIDER_WORKER]);
    if (error) {
        lsf_factory_cleanup_provider_hold(source);
        return error;
    }
    /* WQ initializes the exact six paid parts, registers actual ACPI lifetime,
     * constructs the authenticated Task, and performs same-queue parking. */
    return lsf_prepaid_cleanup_provider_queue_prepare(source, &storage);
}
