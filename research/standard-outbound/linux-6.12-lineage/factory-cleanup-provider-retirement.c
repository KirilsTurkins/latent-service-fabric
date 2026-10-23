/* SPDX-License-Identifier: GPL-2.0-only */
/* All physical state is in original charged records and the actual Root.
 * No Task/worker/pool field is read to infer another object's final free. */
static struct lsf_prepaid_view *lsf_provider_part_record_locked(
    struct lsf_cleanup_task_source source, unsigned int part, const void *address)
{
    struct lsf_prepaid_view *record;
    unsigned int i;
    if (!address || !lsf_cleanup_provider_part_locked(source, part, address, 1))
        return NULL;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->kind == lsf_cleanup_provider_kind(part) && record->phase == LSF_PREPAID_LIVE &&
            record->owner == source.owner.slot && record->owner_generation == source.owner.generation)
            return record; /* The part lookup already proved uniqueness/ancestry. */
    }
    return NULL;
}

int lsf_factory_cleanup_provider_part_origin(const void *address, unsigned int part,
    struct lsf_cleanup_task_source *source)
{
    unsigned long flags, base, value = (unsigned long)address;
    int result = 0;
    if (!source)
        return -EIO;
    *source = (struct lsf_cleanup_task_source){0};
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.pages)
        goto out;
    base = (unsigned long)page_address(factory.pages);
    if (value < base || value - base >= LSF_BACKING_BYTES)
        goto out;
    result = -EIO;
    if (!factory.device)
        goto out;
    *source = (struct lsf_cleanup_task_source){factory.device->key, factory.device->root,
        factory.device->cleanup_request, factory.device->cleanup_task};
    if (lsf_provider_part_record_locked(*source, part, address))
        result = 1;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_cleanup_provider_part_publish(struct lsf_cleanup_task_source source,
    unsigned int part, const void *address)
{
    struct lsf_prepaid_view *record;
    struct lsf_prepaid_ticket ticket;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (factory.pool.stopped || factory.pool.poisoned || READ_ONCE(factory.uncertain) ||
        current->mm != factory.mm || task_tgid(current) != factory.tgid || current_cred() != factory.cred ||
        !current->nsproxy || current->nsproxy->net_ns != factory.net)
        goto out;
    record = lsf_provider_part_record_locked(source, part, address);
    if (!record)
        goto out;
    ticket = (struct lsf_prepaid_ticket){record - factory.pool.records, record->generation};
    result = lsf_device_publish(&factory.pool, source.owner, ticket, record->kind);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

static int lsf_provider_part_queue_locked(struct lsf_cleanup_task_source source,
    struct lsf_prepaid_view *record)
{
    struct lsf_prepaid_ticket ticket = {record - factory.pool.records, record->generation};
    if (record->deferred == LSF_PREPAID_PRIVATE || record->deferred == LSF_PREPAID_QUEUED)
        return 1;
    return lsf_device_queue(&factory.pool, source.owner, ticket, record->kind);
}

int lsf_factory_cleanup_provider_part_queue(struct lsf_cleanup_task_source source,
    unsigned int part, const void *address)
{
    struct lsf_prepaid_view *record;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    record = lsf_provider_part_record_locked(source, part, address);
    if (record)
        result = lsf_provider_part_queue_locked(source, record);
    if (!result)
        lsf_cleanup_lifecycle_poison_locked();
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

static void lsf_provider_pool_finish_if_ready_locked(struct lsf_cleanup_task_source source)
{
    struct lsf_prepaid_view *pool, *child;
    struct lsf_prepaid_ticket ticket;
    unsigned int i;
    if (!factory.device->cleanup_provider_pool_destructed)
        return;
    ticket = factory.device->cleanup_provider_pool;
    pool = lsf_device_record(&factory.pool, source.owner, ticket, LSF_DEVICE_CLEANUP_PROVIDER_POOL);
    if (!pool)
        return; /* Already physically returned, no destructor replay. */
    /* Actual independently ordered Pool-RCU and PWQ-RCU callbacks may finish
     * either way. The real parent record, not a copied child count, decides. */
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        child = &factory.pool.records[i];
        if (child->phase == LSF_PREPAID_LIVE && child->owner == source.owner.slot &&
            child->owner_generation == source.owner.generation && child->cache_bucket == ticket.slot &&
            child->cache_anchor == ticket.generation)
            return;
    }
    if (!lsf_device_finish(&factory.pool, source.owner, ticket, LSF_DEVICE_CLEANUP_PROVIDER_POOL))
        lsf_cleanup_lifecycle_poison_locked();
}

int lsf_factory_cleanup_provider_part_finish(struct lsf_cleanup_task_source source,
    unsigned int part, const void *address)
{
    struct lsf_prepaid_view *record;
    struct lsf_prepaid_ticket ticket;
    unsigned long flags;
    int result = 0;
    if (part == LSF_PROVIDER_POOL)
        return 0; /* Only the real completed Pool destructor can arm its latch. */
    spin_lock_irqsave(&pool_lock, flags);
    record = lsf_provider_part_record_locked(source, part, address);
    if (!record || !lsf_provider_part_queue_locked(source, record))
        goto poison;
    ticket = (struct lsf_prepaid_ticket){record - factory.pool.records, record->generation};
    if (!lsf_device_finish(&factory.pool, source.owner, ticket, record->kind))
        goto poison;
    if (part == LSF_PROVIDER_WORKER && factory.device->cleanup_worker_associated)
        factory.device->cleanup_worker_stop = 2u; /* Actual stop_put completed. */
    lsf_provider_pool_finish_if_ready_locked(source);
    result = 1;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    if (result)
        wake_up_process(kthreadd_task);
    return result;
}

int lsf_factory_cleanup_provider_pool_destructed(struct lsf_cleanup_task_source source,
    const void *address)
{
    struct lsf_prepaid_view *record;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    record = lsf_provider_part_record_locked(source, LSF_PROVIDER_POOL, address);
    if (!record || factory.device->cleanup_provider_pool_destructed ||
        !lsf_provider_part_queue_locked(source, record))
        goto poison;
    /* ida_destroy and the real attrs destructor have completed, including
     * their final pool/attrs reads. No Pool fields are accessed after here. */
    factory.device->cleanup_provider_pool_destructed = 1u;
    lsf_provider_pool_finish_if_ready_locked(source);
    result = 1;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    if (result)
        wake_up_process(kthreadd_task);
    return result;
}

int lsf_factory_cleanup_provider_parts_retired_locked(struct lsf_cleanup_task_source source)
{
    unsigned int i;
    if (factory.device->cleanup_physical_role != LSF_CLEANUP_PHYSICAL_PROVIDER)
        return 1;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        struct lsf_prepaid_view *record = &factory.pool.records[i];
        if (record->phase == LSF_PREPAID_LIVE && record->owner == source.owner.slot &&
            record->owner_generation == source.owner.generation &&
            record->kind >= LSF_DEVICE_CLEANUP_PROVIDER_POOL && record->kind <= LSF_DEVICE_CLEANUP_PROVIDER_CONTEXT)
            return 0;
    }
    return 1;
}
