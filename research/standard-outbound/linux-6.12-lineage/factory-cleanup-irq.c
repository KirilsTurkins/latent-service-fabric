/* SPDX-License-Identifier: GPL-2.0-only */
/* Process-only exact birth resolution; never called from the last-put hook. */
int lsf_factory_cleanup_irq_hint(struct lsf_cleanup_task_source source,
    struct task_struct *task, unsigned long bytes, void **request_address,
    unsigned long *bank_base)
{
    struct lsf_prepaid_view *request, *metadata;
    unsigned long flags;
    int result = 0;
    if (!request_address || !bank_base || current != kthreadd_task || in_interrupt())
        return 0;
    *request_address = NULL;
    *bank_base = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_cleanup_lifecycle_identity_locked(source, task) ||
        (factory.device->cleanup_lifecycle != LSF_CLEANUP_METADATA &&
         factory.device->cleanup_lifecycle != LSF_CLEANUP_PUBLISHED))
        goto out;
    request = lsf_device_record(&factory.pool, source.owner, source.request,
        LSF_DEVICE_CLEANUP_REQUEST);
    metadata = lsf_device_record(&factory.pool, source.owner, factory.device->cleanup_kthread,
        LSF_DEVICE_CLEANUP_KTHREAD);
    if (!request || !bytes || bytes > LSF_FACTORY_INFRA_BYTES ||
        request->bytes != (((lsf_u64)bytes + 63u) & ~(lsf_u64)63u) || !metadata ||
        metadata->cache_bucket != source.task.slot ||
        metadata->cache_anchor != source.task.generation ||
        task->worker_private != (char *)page_address(factory.pages) + metadata->offset)
        goto out;
    *request_address = (char *)page_address(factory.pages) + request->offset;
    *bank_base = (unsigned long)page_address(factory.pages);
    result = 1;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_cleanup_irq_published(struct lsf_cleanup_task_source source,
    struct task_struct *task)
{
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = current == kthreadd_task && lsf_cleanup_lifecycle_identity_locked(source, task) &&
        factory.device->cleanup_lifecycle == LSF_CLEANUP_PUBLISHED &&
        factory.device->cleanup_retire_task == task && refcount_read(&task->usage) >= 1;
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
