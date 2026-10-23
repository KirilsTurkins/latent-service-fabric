/* SPDX-License-Identifier: GPL-2.0-only */
/* Thread-function selection follows immutable physical role and real births.
 * It grants no operation authority; entry/constructor callers independently
 * authenticate their actual current Task/request before reading that pair. */
int lsf_factory_cleanup_thread_pair(struct lsf_cleanup_task_source source,
    int (*function)(void *), const void *data)
{
    struct lsf_cleanup_task_source actual;
    struct lsf_prepaid_view *request;
    unsigned long flags, request_bytes, worker_offset, worker_bytes;
    void *worker;
    int result = 0;
    if (lsf_prepaid_cleanup_worker_geometry(&request_bytes, &worker_offset, &worker_bytes) ||
        worker_offset > request_bytes || worker_bytes > request_bytes - worker_offset)
        return 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.pages || !factory.device)
        goto out;
    actual = (struct lsf_cleanup_task_source){factory.device->key, factory.device->root,
        factory.device->cleanup_request, factory.device->cleanup_task};
    if (!lsf_cleanup_provider_same_task_source(source, actual))
        goto out;
    request = lsf_cleanup_provider_held_record_locked(source, source.request,
        LSF_DEVICE_CLEANUP_REQUEST, source.root);
    if (!request || request->phase != LSF_PREPAID_LIVE || request->bytes < request_bytes)
        goto out;
    if (factory.device->cleanup_physical_role == LSF_CLEANUP_PHYSICAL_PRIVATE) {
        worker = (char *)page_address(factory.pages) + request->offset + worker_offset;
        result = function == kthread_worker_fn && data == worker;
    } else if (factory.device->cleanup_physical_role == LSF_CLEANUP_PHYSICAL_PROVIDER) {
        worker = lsf_cleanup_provider_part_locked(source, LSF_PROVIDER_WORKER, NULL, 0);
        result = worker && data == worker && function == lsf_prepaid_cleanup_provider_worker_thread;
    }
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_cleanup_provider_open_request(struct lsf_cleanup_task_source source,
    const void *worker, void **address)
{
    struct lsf_prepaid_view *request;
    unsigned long flags, bytes;
    int result = 0;
    if (!address || lsf_prepaid_cleanup_request_geometry(&bytes))
        return 0;
    *address = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_factory_cleanup_task_source_locked(source) || factory.pool.stopped ||
        factory.pool.poisoned || factory.pool.contexts[source.owner.slot].closed ||
        factory.device->cleanup_task_claimed ||
        factory.device->cleanup_physical_role != LSF_CLEANUP_PHYSICAL_PROVIDER ||
        factory.device->cleanup_lifecycle != LSF_CLEANUP_UNINITIALIZED ||
        current->mm != factory.mm || task_tgid(current) != factory.tgid ||
        current_cred() != factory.cred || !current->nsproxy || current->nsproxy->net_ns != factory.net ||
        !lsf_cleanup_provider_part_locked(source, LSF_PROVIDER_WORKER, worker, 1))
        goto out;
    request = lsf_device_record(&factory.pool, source.owner, source.request, LSF_DEVICE_CLEANUP_REQUEST);
    if (!request || request->bytes < bytes)
        goto out;
    *address = (char *)page_address(factory.pages) + request->offset;
    result = 1;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_cleanup_provider_task_associate(struct lsf_cleanup_task_source source,
    const void *worker, struct task_struct *task)
{
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_cleanup_lifecycle_identity_locked(source, task) || factory.pool.stopped ||
        factory.pool.poisoned || factory.pool.contexts[source.owner.slot].closed ||
        current->mm != factory.mm || task_tgid(current) != factory.tgid || current_cred() != factory.cred ||
        !current->nsproxy || current->nsproxy->net_ns != factory.net ||
        factory.device->cleanup_physical_role != LSF_CLEANUP_PHYSICAL_PROVIDER ||
        factory.device->cleanup_lifecycle != LSF_CLEANUP_PUBLISHED ||
        factory.device->cleanup_final_phase != LSF_CLEANUP_FINAL_NONE ||
        !factory.device->cleanup_entry_started || factory.device->cleanup_worker_associated ||
        factory.device->cleanup_retire_task != task ||
        !lsf_cleanup_provider_part_locked(source, LSF_PROVIDER_WORKER, worker, 1))
        goto poison;
    if (!refcount_read(&task->usage) || !refcount_read(&task->stack_refcount) ||
        READ_ONCE(task->__state) == TASK_DEAD)
        goto poison;
    /* WQ caller writes worker->task, attaches and wakes only after this exact
     * actual born-task association. It never treats embedded kthread_worker
     * storage in the request as this provider worker. */
    factory.device->cleanup_worker_associated = 1u;
    result = 1;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
