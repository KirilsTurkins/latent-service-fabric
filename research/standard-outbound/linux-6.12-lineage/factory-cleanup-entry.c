/* SPDX-License-Identifier: GPL-2.0-only */
/* Fixed private entry only. This cannot admit a caller task or manufacture a
 * running worker from the partial constructor. All outputs stay bank-owned. */
int lsf_factory_cleanup_entry_current(void **request_address, void **metadata_address)
{
    struct lsf_cleanup_task_source source;
    struct lsf_prepaid_view *request, *metadata;
    unsigned long flags;
    int result = 0;
    if (!request_address || !metadata_address)
        return 0;
    *request_address = NULL;
    *metadata_address = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.device)
        goto poison;
    source = (struct lsf_cleanup_task_source){factory.device->key,
        factory.device->root, factory.device->cleanup_request, factory.device->cleanup_task};
    /* Exact current TASK address and full source generations precede even
     * the first current task field read. A supplied create pointer is not proof. */
    if (!lsf_cleanup_lifecycle_identity_locked(source, current) ||
        factory.device->cleanup_lifecycle != LSF_CLEANUP_PUBLISHED ||
        factory.device->cleanup_entry_started || factory.device->cleanup_retire_task != current)
        goto poison;
    request = lsf_device_record(&factory.pool, source.owner, source.request,
        LSF_DEVICE_CLEANUP_REQUEST);
    metadata = lsf_device_record(&factory.pool, source.owner, factory.device->cleanup_kthread,
        LSF_DEVICE_CLEANUP_KTHREAD);
    if (!request || !metadata || metadata->deferred != LSF_PREPAID_PUBLISHED ||
        metadata->cache_bucket != source.task.slot ||
        metadata->cache_anchor != source.task.generation ||
        current->worker_private != (char *)page_address(factory.pages) + metadata->offset ||
        !(current->flags & PF_KTHREAD) || refcount_read(&current->usage) < 1)
        goto poison;
    factory.device->cleanup_entry_started = 1u;
    *request_address = (char *)page_address(factory.pages) + request->offset;
    *metadata_address = (char *)page_address(factory.pages) + metadata->offset;
    result = 1;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
