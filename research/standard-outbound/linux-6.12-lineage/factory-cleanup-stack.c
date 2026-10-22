/* SPDX-License-Identifier: GPL-2.0-only */
/* Included after factory-cleanup-task.c; pool_lock precedes every record access. */
int lsf_factory_cleanup_stack_reserve(struct lsf_cleanup_task_source source,
    struct task_struct *actual_task, unsigned long bytes, void **address)
{
    struct lsf_prepaid_view *task;
    struct lsf_prepaid_ticket ticket;
    lsf_u64 offset;
    unsigned long flags, actual_bytes;
    int result = -EOPNOTSUPP;
    if (!address || lsf_prepaid_cleanup_stack_geometry(&actual_bytes) ||
        bytes != actual_bytes || !bytes || bytes > LSF_FACTORY_INFRA_BYTES)
        return result;
    *address = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    if (current != kthreadd_task || !lsf_factory_cleanup_task_source_locked(source) ||
        factory.pool.stopped || factory.pool.contexts[source.owner.slot].closed ||
        factory.device->cleanup_task_claimed != 1u ||
        factory.device->cleanup_stack_attempted)
        goto out;
    task = &factory.pool.records[source.task.slot];
    if (task->deferred != LSF_PREPAID_PRIVATE ||
        actual_task != (void *)((char *)page_address(factory.pages) + task->offset))
        goto out;
    /* The original allocator checks bytes, slot and generation BEFORE the
     * first write. A failed attempt is not retried or borrowed from a cache. */
    factory.device->cleanup_stack_attempted = 1u;
    if (!lsf_device_allocate(&factory.pool, source.owner, bytes,
            LSF_DEVICE_CLEANUP_STACK, source.task, &ticket, &offset))
        goto out;
    factory.device->cleanup_stack = ticket;
    *address = (char *)page_address(factory.pages) + offset;
    memset(*address, 0, bytes);
    result = 0;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void *lsf_factory_cleanup_stack_current(struct lsf_cleanup_task_source source,
    const struct task_struct *actual_task)
{
    struct lsf_prepaid_view *record, *task;
    unsigned long flags;
    void *result = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    if (current != kthreadd_task || !lsf_factory_cleanup_task_source_locked(source) ||
        factory.device->cleanup_task_claimed != 1u)
        goto out;
    task = &factory.pool.records[source.task.slot];
    record = lsf_device_record(&factory.pool, source.owner, factory.device->cleanup_stack,
        LSF_DEVICE_CLEANUP_STACK);
    if (!record || record->deferred != LSF_PREPAID_PRIVATE ||
        record->cache_bucket != source.task.slot ||
        record->cache_anchor != source.task.generation ||
        actual_task != (const void *)((char *)page_address(factory.pages) + task->offset))
        goto out;
    result = (char *)page_address(factory.pages) + record->offset;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_cleanup_stack_finish(struct lsf_cleanup_task_source source,
    const void *address)
{
    struct lsf_prepaid_ticket ticket;
    struct lsf_prepaid_view *record;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    /* Final return deliberately allows a closed context. It is not a birth
     * or a claim and cannot reopen stopped admission. */
    if (current != kthreadd_task || !lsf_factory_cleanup_task_source_locked(source))
        goto poison;
    ticket = factory.device->cleanup_stack;
    record = lsf_device_record(&factory.pool, source.owner, ticket,
        LSF_DEVICE_CLEANUP_STACK);
    if (!record || record->deferred != LSF_PREPAID_PRIVATE ||
        record->cache_bucket != source.task.slot ||
        record->cache_anchor != source.task.generation ||
        address != (char *)page_address(factory.pages) + record->offset ||
        !lsf_device_finish(&factory.pool, source.owner, ticket, LSF_DEVICE_CLEANUP_STACK))
        goto poison;
    result = 1;
    goto out;
poison:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void lsf_factory_cleanup_stack_poison(struct lsf_cleanup_task_source source)
{
    unsigned long flags;
    spin_lock_irqsave(&pool_lock, flags);
    /* A disagreement cannot authorize a return. Even an unrecognised source
     * leaves all backing held; no pointer is promoted into an owner. */
    (void)source;
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
    spin_unlock_irqrestore(&pool_lock, flags);
}
