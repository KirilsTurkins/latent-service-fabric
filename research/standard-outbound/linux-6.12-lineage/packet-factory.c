/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in the authenticated factory.c. The protected allocator creates
 * these records; this routine only routes existing addresses at real kernel
 * use/return sites. It cannot adopt an address or accept a caller proof. */
static int lsf_factory_packet_birth_locked(const void *address, unsigned int kind,
                                           struct lsf_factory_blob *copy)
{
    struct lsf_prepaid_context *owner;
    struct lsf_prepaid_view *record;
    struct lsf_prepaid_key key;
    unsigned long base, value = (unsigned long)address;
    unsigned int audit_kind, i;
    if (!factory.pages)
        return 0;
    base = (unsigned long)page_address(factory.pages);
    if (value < base || value - base >= LSF_BACKING_BYTES)
        return 0;
    if (!copy || !factory.pool.initialized || factory.pool.poisoned)
        goto invalid;
    if (kind == LSF_PREPAID_PACKET_SKB)
        audit_kind = LSF_PREPAID_AUDIT_SKB;
    else if (kind == LSF_PREPAID_PACKET_HEAD)
        audit_kind = LSF_PREPAID_AUDIT_HEAD;
    else
        goto invalid;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->offset != value - base || record->phase != LSF_PREPAID_LIVE)
            continue;
        /* A known audit birth is passed to the ORIGINAL audit routing. This
         * is not a generic kind mismatch exception or a normal-heap fallback.
         * Its generation and return semantics are still checked there. */
        if (record->kind == audit_kind)
            return 0;
        if (record->kind != kind || !record->generation ||
            !record->owner_generation || record->deferred)
            goto invalid;
        key = (struct lsf_prepaid_key){record->owner, record->owner_generation};
        owner = lsf_prepaid_context_for(&factory.pool, key);
        if (!owner || !owner->live || factory.contexts[key.slot].key.slot != key.slot ||
            factory.contexts[key.slot].key.generation != key.generation)
            goto invalid;
        copy->context = &factory.contexts[key.slot];
        copy->ticket = (struct lsf_prepaid_ticket){i, record->generation};
        return 1;
    }
invalid:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
    return -1;
}

int lsf_factory_packet_birth(const void *address, unsigned int kind,
                              struct lsf_factory_blob *copy)
{
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_factory_packet_birth_locked(address, kind, copy);
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* A linear SKB's complete shared-info span must fit its ORIGINAL head birth
 * before any skb_shinfo pointer is derived or dereferenced. */
int lsf_factory_packet_head_current(const void *address, unsigned long bytes,
                                     struct lsf_factory_blob *copy)
{
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_factory_packet_birth_locked(address, LSF_PREPAID_PACKET_HEAD, copy);
    if (result == 1 && (!bytes || bytes > LSF_TCP_BYTES ||
        bytes > factory.pool.records[copy->ticket.slot].bytes)) {
        factory.pool.contexts[copy->context->key.slot].poisoned = 1;
        WRITE_ONCE(factory.uncertain, 1);
        result = -1;
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
