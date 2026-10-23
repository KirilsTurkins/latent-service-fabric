/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual __kthread_create_worker's association, after REAL child completion.
 * Only original opener authority and exact charged request/Task births work. */
int lsf_factory_cleanup_worker_associate(struct lsf_cleanup_task_source source,
    void *request_address, struct kthread_worker *worker, struct task_struct *task)
{
    struct lsf_prepaid_view *request;
    unsigned long flags, request_bytes, worker_offset, worker_bytes;
    int result = 0;
    if (lsf_prepaid_cleanup_worker_geometry(&request_bytes, &worker_offset, &worker_bytes) ||
        worker_bytes != sizeof(*worker) || worker_offset > request_bytes ||
        worker_bytes > request_bytes - worker_offset)
        return 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_cleanup_lifecycle_identity_locked(source, task) || factory.pool.stopped ||
        factory.pool.contexts[source.owner.slot].closed || current->mm != factory.mm ||
        task_tgid(current) != factory.tgid || current_cred() != factory.cred ||
        !current->nsproxy || current->nsproxy->net_ns != factory.net ||
        factory.device->cleanup_lifecycle != LSF_CLEANUP_PUBLISHED ||
        factory.device->cleanup_final_phase != LSF_CLEANUP_FINAL_NONE ||
        !factory.device->cleanup_entry_started || factory.device->cleanup_worker_associated ||
        factory.device->cleanup_retire_task != task)
        goto poison;
    request = lsf_device_record(&factory.pool, source.owner, source.request, LSF_DEVICE_CLEANUP_REQUEST);
    if (!request || request->bytes < request_bytes ||
        request_address != (char *)page_address(factory.pages) + request->offset ||
        (void *)worker != (char *)request_address + worker_offset)
        goto poison;
    /* Both exact immutable births precede even the first Task/worker field. */
    if (!refcount_read(&task->usage) || !refcount_read(&task->stack_refcount) ||
        READ_ONCE(task->__state) == TASK_DEAD ||
        (worker->task && worker->task != task) || worker->flags)
        goto poison;
    worker->flags = 0; /* Actual fixed original flags profile. */
    worker->task = task;
    factory.device->cleanup_worker_associated = 1;
    result = 1;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result; /* Original wake_up_process is outside this pool lock. */
}
