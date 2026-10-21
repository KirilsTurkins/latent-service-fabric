/* SPDX-License-Identifier: GPL-2.0-only */
/* Included by the private factory after its original address classifier. */
int lsf_factory_avc_member(const void *address, unsigned int kind,
    unsigned long bytes, struct lsf_factory_blob *copy)
{
    struct lsf_prepaid_view *record;
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    if (!copy || !bytes || !lsf_prepaid_avc_kind(kind)) {
        factory.pool.poisoned = 1;
        result = -1;
        goto out;
    }
    result = lsf_factory_blob_lookup_locked(address, kind, copy);
    if (result != 1)
        goto out;
    record = &factory.pool.records[copy->ticket.slot];
    if (record->bytes < bytes ||
        (kind != LSF_PREPAID_AVC_NODE && record->deferred != LSF_PREPAID_PRIVATE) ||
        record->deferred > LSF_PREPAID_PUBLISHED) {
        factory.pool.poisoned = 1;
        result = -1;
    }
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_avc_phase(struct lsf_factory_blob copy, unsigned int phase)
{
    struct lsf_factory_context *context;
    struct lsf_prepaid_view *record;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    context = lsf_factory_context_current(copy.context);
    if (!context || !copy.ticket.slot || copy.ticket.slot >= LSF_ALLOCATION_SLOTS ||
        (phase != LSF_PREPAID_PRIVATE && phase != LSF_PREPAID_QUEUED))
        goto invalid;
    record = &factory.pool.records[copy.ticket.slot];
    if (record->phase != LSF_PREPAID_LIVE || record->kind != LSF_PREPAID_AVC_NODE ||
        record->generation != copy.ticket.generation || record->owner != context->key.slot ||
        record->owner_generation != context->key.generation || record->deferred != phase)
        goto invalid;
    result = 1;
    goto out;
invalid:
    factory.pool.poisoned = 1;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_avc_replace(const void *address, const void *prior_address,
    unsigned int bucket)
{
    struct lsf_factory_blob copy, prior = {0};
    struct lsf_prepaid_key prior_key = {0};
    unsigned long flags;
    int result = -1, owned = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (lsf_factory_blob_lookup_locked(address, LSF_PREPAID_AVC_NODE, &copy) != 1)
        goto invalid;
    if (prior_address) {
        owned = lsf_factory_blob_lookup_locked(prior_address, LSF_PREPAID_AVC_NODE, &prior);
        if (owned < 0)
            goto invalid;
        if (owned)
            prior_key = prior.context->key;
    }
    if (!lsf_prepaid_avc_replace(&factory.pool, copy.context->key, copy.ticket,
                                prior_key, prior.ticket, owned, bucket))
        goto invalid;
    result = 1;
    goto out;
invalid:
    factory.pool.poisoned = 1;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_avc_publish(const void *address, unsigned int bucket)
{
    return lsf_factory_avc_replace(address, NULL, bucket);
}

int lsf_factory_avc_queue(const void *address)
{
    struct lsf_factory_blob copy;
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_factory_blob_lookup_locked(address, LSF_PREPAID_AVC_NODE, &copy);
    if (result == 1 && !lsf_prepaid_avc_queue(&factory.pool, copy.context->key, copy.ticket)) {
        factory.pool.poisoned = 1;
        result = -1;
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_avc_candidate(struct lsf_factory_context *context, unsigned int slot,
    struct lsf_prepaid_ticket *ticket, unsigned int *bucket)
{
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    context = lsf_factory_context_current(context);
    if (context)
        result = lsf_prepaid_avc_candidate(&factory.pool, context->key, slot, ticket, bucket);
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_avc_current(struct lsf_factory_context *context,
    struct lsf_prepaid_ticket ticket, unsigned int bucket, void **address)
{
    unsigned long flags;
    lsf_u64 offset;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    context = lsf_factory_context_current(context);
    if (context && address && factory.pages &&
        lsf_prepaid_avc_current(&factory.pool, context->key, ticket, bucket, &offset)) {
        *address = (char *)page_address(factory.pages) + offset;
        result = 1;
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
