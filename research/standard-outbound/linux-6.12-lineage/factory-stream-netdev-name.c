/* SPDX-License-Identifier: GPL-2.0-only */
/* Only the original primary name-node birth and original two return sites.
 * Alternate-name strings are not funded by this fixed source path. */
#include <net/lsf_stream_netdev_name_private.h>

static int lsf_stream_name_shape(unsigned long *bytes, unsigned long *alignment)
{
    return !lsf_prepaid_stream_netdev_name_geometry(bytes, alignment) && *bytes &&
        *bytes <= ULONG_MAX - 63u && *alignment && *alignment <= 64u &&
        !(*alignment & (*alignment - 1u));
}

int lsf_factory_stream_netdev_name_parent(const struct net_device *dev)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *record;
    struct lsf_prepaid_ticket ticket;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_stream_rx_address_locked(dev)) goto out;
    result = -EOPNOTSUPP;
    state = lsf_stream_rx_current_locked();
    record = lsf_stream_netdev_record_locked(state, dev, &ticket);
    if (record && record->deferred == LSF_PREPAID_PUBLISHED &&
        lsf_stream_constructor_current_locked(state)) result = 1;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void *lsf_factory_stream_netdev_name_allocate(struct net_device *dev)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *record;
    struct lsf_prepaid_ticket parent, ticket;
    unsigned long flags, bytes, alignment;
    unsigned int i;
    u64 offset;
    void *result = NULL;
    if (!lsf_stream_name_shape(&bytes, &alignment)) return NULL;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    record = lsf_stream_netdev_record_locked(state, dev, &parent);
    if (!record || record->deferred != LSF_PREPAID_PUBLISHED || dev->name_node)
        goto out;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->kind == LSF_DEVICE_NETDEV_NAME && record->owner == state->owner.slot &&
            record->owner_generation == state->owner.generation &&
            record->cache_bucket == parent.slot && record->cache_anchor == parent.generation &&
            record->phase != LSF_PREPAID_EMPTY) goto out;
    }
    if (lsf_stream_constructor_allocate_locked(state, LSF_DEVICE_NETDEV_NAME,
            parent, bytes, alignment, &ticket, &offset) != 1) goto out;
    result = (char *)page_address(factory.pages) + offset;
    memset(result, 0, bytes);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

static struct lsf_prepaid_view *lsf_stream_name_record_locked(
    struct lsf_stream_rx_state *state, const void *node,
    struct lsf_prepaid_ticket *ticket, struct lsf_prepaid_ticket *parent)
{
    struct lsf_prepaid_view *record, *birth;
    unsigned long bytes, alignment, base, at = (unsigned long)node;
    unsigned int i;
    lockdep_assert_held(&pool_lock);
    if (!state || !lsf_stream_rx_address_locked(node) ||
        !lsf_stream_name_shape(&bytes, &alignment)) return NULL;
    base = (unsigned long)page_address(factory.pages);
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->offset != at - base) continue;
        *ticket = (struct lsf_prepaid_ticket){i, record->generation};
        if (!lsf_device_record(&factory.pool, state->owner, *ticket, LSF_DEVICE_NETDEV_NAME) ||
            record->bytes != ((bytes + 63u) & ~63ull) || record->offset % alignment)
            return NULL;
        *parent = (struct lsf_prepaid_ticket){record->cache_bucket, record->cache_anchor};
        birth = lsf_device_record(&factory.pool, state->owner, *parent, LSF_DEVICE_NETDEV);
        if (!birth || (birth->deferred != LSF_PREPAID_PUBLISHED &&
                       birth->deferred != LSF_PREPAID_QUEUED)) return NULL;
        return record;
    }
    return NULL;
}

int lsf_factory_stream_netdev_name_publish(struct net_device *dev, const void *node)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *record, *birth;
    struct lsf_prepaid_ticket ticket, parent, actual_parent;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    record = lsf_stream_name_record_locked(state, node, &ticket, &parent);
    birth = lsf_stream_netdev_record_locked(state, dev, &actual_parent);
    if (record && birth && birth->deferred == LSF_PREPAID_PUBLISHED &&
        record->deferred == LSF_PREPAID_PRIVATE && parent.slot == actual_parent.slot &&
        parent.generation == actual_parent.generation && !dev->name_node &&
        lsf_stream_constructor_current_locked(state))
        result = lsf_device_publish(&factory.pool, state->owner, ticket, LSF_DEVICE_NETDEV_NAME);
    if (!result) { factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1); }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_netdev_name_return(const void *node)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *record;
    struct lsf_prepaid_ticket ticket, parent;
    struct net_device *dev;
    unsigned long flags, base;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_stream_rx_address_locked(node)) goto out;
    result = -EOPNOTSUPP;
    state = lsf_stream_rx_current_locked();
    record = lsf_stream_name_record_locked(state, node, &ticket, &parent);
    if (!record || record->deferred != LSF_PREPAID_PUBLISHED) goto poison;
    base = (unsigned long)page_address(factory.pages);
    dev = (void *)(base + factory.pool.records[parent.slot].offset);
    if (dev->name_node != node) goto poison;
    /* Both actual original free sites are after their own last use/fence.
     * Clear the actual parent alias BEFORE returning this original child. */
    dev->name_node = NULL;
    if (lsf_device_queue(&factory.pool, state->owner, ticket, LSF_DEVICE_NETDEV_NAME) &&
        lsf_device_finish(&factory.pool, state->owner, ticket, LSF_DEVICE_NETDEV_NAME)) {
        result = 1; goto out;
    }
poison:
    factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
