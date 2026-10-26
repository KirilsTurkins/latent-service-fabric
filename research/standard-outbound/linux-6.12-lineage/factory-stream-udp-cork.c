/* SPDX-License-Identifier: GPL-2.0-only */
/* Include in original factory.c. No new allocation table: the exact copied
 * cork kind uses the SAME record's otherwise-unused parent identity fields. */
#include <net/ip.h>
#include <net/lsf_stream_packet_private.h>

static struct lsf_factory_context *lsf_stream_cork_parent_locked(
    struct lsf_factory_blob parent)
{
    struct lsf_factory_context *context;
    struct lsf_prepaid_view *record;
    lockdep_assert_held(&pool_lock);
    if (!lsf_factory_blob_shape(parent) || parent.domain != LSF_FACTORY_OWNER_APPLICATION ||
        !parent.ticket.slot || parent.ticket.slot >= LSF_ALLOCATION_SLOTS)
        return NULL;
    context = lsf_factory_context_current(parent.context);
    if (!context) return NULL;
    record = &factory.pool.records[parent.ticket.slot];
    if (record->phase != LSF_PREPAID_LIVE || record->kind != LSF_PREPAID_OBJECT ||
        record->generation != parent.ticket.generation || record->deferred ||
        record->owner != context->key.slot || record->owner_generation != context->key.generation)
        return NULL;
    return context;
}

static int lsf_stream_cork_record_locked(struct lsf_factory_blob copy,
    struct lsf_factory_blob parent)
{
    struct lsf_factory_context *context = lsf_stream_cork_parent_locked(parent);
    struct lsf_prepaid_view *record;
    u64 bytes = (sizeof(struct ip_options) + 40u + 63u) & ~63ull;
    lockdep_assert_held(&pool_lock);
    if (!context || !lsf_factory_blob_shape(copy) ||
        copy.domain != LSF_FACTORY_OWNER_APPLICATION || copy.context != context ||
        !copy.ticket.slot || copy.ticket.slot >= LSF_ALLOCATION_SLOTS)
        return 0;
    record = &factory.pool.records[copy.ticket.slot];
    return record->phase == LSF_PREPAID_LIVE &&
        record->kind == LSF_PREPAID_CORK_OPTIONS &&
        record->generation == copy.ticket.generation &&
        record->owner == context->key.slot && record->owner_generation == context->key.generation &&
        record->deferred == LSF_PREPAID_PRIVATE && record->bytes == bytes &&
        record->cache_bucket == parent.ticket.slot && record->cache_anchor == parent.ticket.generation;
}

struct ip_options *lsf_factory_stream_cork_allocate(struct lsf_factory_blob parent)
{
    struct lsf_factory_context *context;
    struct lsf_prepaid_ticket ticket;
    struct lsf_prepaid_view *record;
    unsigned long flags;
    u64 offset;
    struct ip_options *result = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    context = lsf_stream_cork_parent_locked(parent);
    if (context && __alignof__(struct ip_options) <= 64u &&
        lsf_prepaid_child_allocate(&factory.pool, context->key,
            sizeof(struct ip_options) + 40u, LSF_PREPAID_CORK_OPTIONS,
            parent.ticket, &ticket, &offset)) {
        record = &factory.pool.records[ticket.slot];
        record->cache_bucket = parent.ticket.slot;
        record->cache_anchor = parent.ticket.generation;
        result = (void *)((char *)page_address(factory.pages) + offset);
        memset(result, 0, sizeof(struct ip_options) + 40u);
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_cork_current(const struct ip_options *address,
    struct lsf_factory_blob parent)
{
    struct lsf_factory_blob copy;
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_factory_blob_lookup_locked(address, LSF_PREPAID_CORK_OPTIONS, &copy);
    result = result == 1 && lsf_stream_cork_record_locked(copy, parent);
    if (!result) factory.pool.poisoned = 1;
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_cork_finish(struct lsf_factory_blob copy)
{
    struct lsf_factory_blob parent = {};
    struct lsf_prepaid_view *record;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_factory_blob_shape(copy) || copy.domain != LSF_FACTORY_OWNER_APPLICATION ||
        !copy.ticket.slot || copy.ticket.slot >= LSF_ALLOCATION_SLOTS)
        goto out;
    record = &factory.pool.records[copy.ticket.slot];
    parent.context = copy.context; parent.domain = LSF_FACTORY_OWNER_APPLICATION;
    parent.ticket = (struct lsf_prepaid_ticket){record->cache_bucket, record->cache_anchor};
    if (lsf_stream_cork_record_locked(copy, parent))
        result = lsf_prepaid_blob_finish(&factory.pool, copy.context->key,
            copy.ticket, LSF_PREPAID_CORK_OPTIONS);
out:
    if (!result) factory.pool.poisoned = 1;
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
