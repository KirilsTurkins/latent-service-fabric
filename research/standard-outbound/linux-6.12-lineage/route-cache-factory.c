/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in the exact selected factory.c, after its original definitions.
 * Pool lock never encloses an original cache lock, dst_release or parent put. */

static struct lsf_prepaid_view *lsf_factory_route_record_locked(struct lsf_factory_blob copy)
{
    struct lsf_factory_context *context = lsf_factory_context_current(copy.context);
    struct lsf_prepaid_view *record;
    if (!context || !copy.ticket.slot || copy.ticket.slot >= LSF_ALLOCATION_SLOTS)
        goto invalid;
    record = &factory.pool.records[copy.ticket.slot];
    if (record->phase != LSF_PREPAID_LIVE || record->kind != LSF_PREPAID_ROUTE ||
        record->generation != copy.ticket.generation || record->owner != context->key.slot ||
        record->owner_generation != context->key.generation || record->bytes < sizeof(struct rtable))
        goto invalid;
    return record;
invalid:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
    return NULL;
}

int lsf_factory_route_parent_attach(const void *address,
    const struct lsf_route_cache_owner *parent)
{
    struct lsf_factory_blob birth;
    struct lsf_prepaid_view *record;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (lsf_factory_blob_lookup_locked(address, LSF_PREPAID_ROUTE, &birth) != 1)
        goto invalid;
    record = lsf_factory_route_record_locked(birth);
    if (!record)
        goto out;
    if (!parent || !parent->parent || !parent->nhc ||
        (parent->parent_kind != LSF_ROUTE_PARENT_FIB && parent->parent_kind != LSF_ROUTE_PARENT_NH) ||
        parent->cache_kind || parent->cpu || parent->daddr ||
        (parent->parent_kind == LSF_ROUTE_PARENT_NH && parent->nh_index) ||
        !lsf_route_cache_empty(&record->route_cache) || record->deferred != LSF_PREPAID_PRIVATE)
        goto invalid;
    if (factory.pool.stopped || factory.pool.poisoned ||
        factory.pool.contexts[record->owner].closed || factory.pool.contexts[record->owner].poisoned)
        goto out;
    /* The caller already owns this actual parent reference. Transfer it into
     * the original route birth BEFORE any shared-cache publication. */
    record->route_cache = *parent;
    result = 1;
    goto out;
invalid:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_route_cache_publish(struct rtable *rt, struct rtable __rcu **cell,
    struct rtable *original, unsigned int kind, unsigned int cpu, unsigned int daddr,
    struct rtable **previous)
{
    struct lsf_factory_blob birth;
    struct lsf_prepaid_view *record;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!cell || !previous || lsf_factory_blob_lookup_locked(rt, LSF_PREPAID_ROUTE, &birth) != 1)
        goto invalid;
    record = lsf_factory_route_record_locked(birth);
    if (!record)
        goto out;
    if (!record->route_cache.parent || !record->route_cache.nhc ||
        record->route_cache.cache_kind || record->deferred != LSF_PREPAID_PRIVATE ||
        kind < LSF_ROUTE_CACHE_INPUT || kind > LSF_ROUTE_CACHE_EXCEPTION_OUTPUT ||
        ((kind == LSF_ROUTE_CACHE_INPUT || kind == LSF_ROUTE_CACHE_OUTPUT) && daddr) ||
        (kind != LSF_ROUTE_CACHE_OUTPUT && cpu))
        goto invalid;
    if (factory.pool.stopped || factory.pool.poisoned ||
        factory.pool.contexts[record->owner].closed || factory.pool.contexts[record->owner].poisoned)
        goto out;
    record->route_cache.cache_kind = kind;
    record->route_cache.cpu = cpu;
    record->route_cache.daddr = daddr;
    /* The root-close fence and the REAL publication share this lock. A close
     * scan cannot run between a successful fence and a later publication. */
    dst_hold(&rt->dst);
    if (kind == LSF_ROUTE_CACHE_INPUT || kind == LSF_ROUTE_CACHE_OUTPUT)
        *previous = cmpxchg((struct rtable **)cell, original, rt);
    else {
        rcu_assign_pointer(*cell, rt);
        *previous = original;
    }
    result = 1;
    goto out;
invalid:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_route_current(struct lsf_factory_context *context, unsigned int slot,
    struct rtable **route, struct lsf_route_cache_owner *owner)
{
    struct lsf_prepaid_view *record;
    struct rtable *rt;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    context = lsf_factory_context_current(context);
    if (!context || !route || !owner || !slot || slot >= LSF_ALLOCATION_SLOTS ||
        !factory.pages || !factory.pool.contexts[context->key.slot].closed)
        goto out;
    record = &factory.pool.records[slot];
    if (record->phase != LSF_PREPAID_LIVE || record->kind != LSF_PREPAID_ROUTE ||
        record->owner != context->key.slot || record->owner_generation != context->key.generation ||
        record->deferred != LSF_PREPAID_PRIVATE || !record->route_cache.cache_kind)
        goto out;
    if (!record->generation || record->bytes < sizeof(*rt) ||
        !record->route_cache.parent || !record->route_cache.nhc ||
        record->offset > LSF_BACKING_BYTES - sizeof(*rt))
        goto invalid;
    rt = (void *)((char *)page_address(factory.pages) + record->offset);
    /* A LIVE view alone is not a live dst. The real final put may already have
     * happened while its original callback is waiting for this pool lock. */
    if (!dst_hold_safe(&rt->dst))
        goto out;
    *route = rt;
    *owner = record->route_cache;
    result = 1;
    goto out;
invalid:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_route_parent_take(const void *address, struct lsf_route_cache_owner *owner)
{
    struct lsf_factory_blob birth;
    struct lsf_prepaid_view *record;
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_factory_blob_lookup_locked(address, LSF_PREPAID_ROUTE, &birth);
    if (result != 1)
        goto out;
    record = lsf_factory_route_record_locked(birth);
    if (!record || !owner || record->deferred >= LSF_PREPAID_PUBLISHED)
        goto invalid;
    if (!lsf_route_cache_empty(&record->route_cache) &&
        (!record->route_cache.parent || !record->route_cache.nhc ||
         (record->route_cache.parent_kind != LSF_ROUTE_PARENT_FIB &&
          record->route_cache.parent_kind != LSF_ROUTE_PARENT_NH) ||
         record->route_cache.cache_kind > LSF_ROUTE_CACHE_EXCEPTION_OUTPUT ||
         (record->route_cache.parent_kind == LSF_ROUTE_PARENT_NH && record->route_cache.nh_index)))
        goto invalid;
    *owner = record->route_cache;
    record->route_cache = (struct lsf_route_cache_owner){0};
    goto out;
invalid:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
    result = -1;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
