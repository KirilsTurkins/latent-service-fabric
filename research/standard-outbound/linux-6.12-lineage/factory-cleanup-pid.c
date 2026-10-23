/* SPDX-License-Identifier: GPL-2.0-only */
/* Included after the original lifecycle/descendant helpers in factory.c.
 * All allocations and callback returns use the original fixed pool records. */
static int lsf_cleanup_pid_constructing_locked(struct lsf_cleanup_task_source source,
    struct task_struct *task, const struct pid *pid)
{
    struct lsf_prepaid_ticket ticket;
    return current == kthreadd_task && !in_interrupt() &&
        lsf_cleanup_lifecycle_identity_locked(source, task) && !factory.pool.stopped &&
        !factory.pool.contexts[source.owner.slot].closed &&
        factory.device->cleanup_final_phase == LSF_CLEANUP_FINAL_NONE &&
        (factory.device->cleanup_lifecycle == LSF_CLEANUP_INITIALIZED ||
         factory.device->cleanup_lifecycle == LSF_CLEANUP_METADATA) &&
        lsf_cleanup_child_find_locked(pid, LSF_CLEANUP_PID, &ticket) == 1;
}

int lsf_factory_cleanup_pid_constructing(struct lsf_cleanup_task_source source,
    struct task_struct *task, const struct pid *pid)
{
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_cleanup_pid_constructing_locked(source, task, pid);
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_cleanup_pid_origin(const struct pid *pid)
{
    struct lsf_prepaid_ticket ticket;
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_cleanup_child_find_locked(pid, LSF_CLEANUP_PID, &ticket);
    if (result < 0)
        lsf_cleanup_lifecycle_poison_locked();
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void *lsf_factory_cleanup_pid_radix_new(struct lsf_cleanup_task_source source,
    struct task_struct *task, const struct pid *pid)
{
    struct lsf_prepaid_ticket ticket;
    unsigned long flags, bytes, alignment;
    lsf_u64 offset;
    void *result = NULL;
    if (lsf_prepaid_cleanup_pid_radix_geometry(&bytes, &alignment) ||
        !bytes || bytes > LSF_FACTORY_INFRA_BYTES || !alignment || alignment > 64u ||
        (alignment & (alignment - 1u)))
        return NULL;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_cleanup_pid_constructing_locked(source, task, pid) ||
        !lsf_device_allocate(&factory.pool, source.owner, bytes, LSF_DEVICE_CLEANUP_PID_RADIX,
            source.root, &ticket, &offset))
        goto out;
    if (((unsigned long)page_address(factory.pages) + offset) & (alignment - 1u)) {
        lsf_cleanup_lifecycle_poison_locked();
        goto out;
    }
    result = (char *)page_address(factory.pages) + offset;
    memset(result, 0, bytes); /* Same original charge before the first write. */
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Classify a typed bank birth before any radix node fields are touched.
 * Known other original kinds fall through to their ORIGINAL typed dispatcher.
 * A wrong interior, returned or unrecognized bank address never reaches SLUB. */
static int lsf_cleanup_pid_radix_find_locked(const void *address, unsigned int phase,
    struct lsf_cleanup_pid_radix_source *source)
{
    struct lsf_prepaid_view *record;
    struct lsf_prepaid_ticket ticket;
    unsigned long base, at = (unsigned long)address;
    unsigned int i;
    if (!factory.pages)
        return 0;
    base = (unsigned long)page_address(factory.pages);
    if (at < base || at - base >= LSF_BACKING_BYTES)
        return 0;
    if (!factory.device ||
        !lsf_device_record(&factory.pool, factory.device->key, factory.device->root, LSF_DEVICE_ROOT))
        return -1;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->offset != at - base)
            continue;
        ticket = (struct lsf_prepaid_ticket){i, record->generation};
        if (!lsf_device_record(&factory.pool, factory.device->key, ticket, record->kind))
            return -1;
        if (record->kind != LSF_DEVICE_CLEANUP_PID_RADIX)
            return 0;
        if (record->cache_bucket != factory.device->root.slot ||
            record->cache_anchor != factory.device->root.generation || record->deferred != phase)
            return -1;
        *source = (struct lsf_cleanup_pid_radix_source){factory.device->key,
            factory.device->root, ticket, address};
        return 1;
    }
    return -1;
}

int lsf_factory_cleanup_pid_radix_publish(struct lsf_cleanup_task_source task_source,
    struct task_struct *task, const struct pid *pid, const void *address)
{
    struct lsf_cleanup_pid_radix_source source;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_cleanup_pid_constructing_locked(task_source, task, pid) ||
        lsf_cleanup_pid_radix_find_locked(address, LSF_PREPAID_PRIVATE, &source) != 1 ||
        !lsf_device_publish(&factory.pool, source.owner, source.allocation, LSF_DEVICE_CLEANUP_PID_RADIX))
        goto poison;
    result = 1;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_cleanup_pid_radix_return_begin(const void *address,
    struct lsf_cleanup_pid_radix_source *source)
{
    unsigned long flags;
    int result;
    if (!source)
        return -1;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_cleanup_pid_radix_find_locked(address, LSF_PREPAID_PUBLISHED, source);
    if (result == 1 && !lsf_device_queue(&factory.pool, source->owner,
            source->allocation, LSF_DEVICE_CLEANUP_PID_RADIX))
        result = -1;
    if (result < 0)
        lsf_cleanup_lifecycle_poison_locked();
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_cleanup_pid_radix_return_finish(struct lsf_cleanup_pid_radix_source source)
{
    struct lsf_cleanup_pid_radix_source actual;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (lsf_cleanup_pid_radix_find_locked(source.address, LSF_PREPAID_QUEUED, &actual) != 1 ||
        actual.owner.slot != source.owner.slot || actual.owner.generation != source.owner.generation ||
        actual.root.slot != source.root.slot || actual.root.generation != source.root.generation ||
        actual.allocation.slot != source.allocation.slot ||
        actual.allocation.generation != source.allocation.generation ||
        !lsf_device_finish(&factory.pool, source.owner, source.allocation, LSF_DEVICE_CLEANUP_PID_RADIX))
        goto poison;
    result = 1;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
