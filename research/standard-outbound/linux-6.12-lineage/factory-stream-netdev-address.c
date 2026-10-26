/* SPDX-License-Identifier: GPL-2.0-only */
/* SAME original Node records/backing and exact typed NETDEV/HW_ADDR kinds.
 * The NETDEV main producer/final-release and per-CPU ports remain separate
 * obligations. This source never adopts an ordinary device or address list. */
#include <linux/netdevice.h>
#include <linux/cache.h>
#include <net/lsf_stream_material_geometry_private.h>
#include <net/lsf_stream_netdev_private.h>

static struct lsf_prepaid_view *lsf_stream_netdev_record_locked(
    struct lsf_stream_rx_state *state, const struct net_device *device,
    struct lsf_prepaid_ticket *ticket)
{
    struct lsf_stream_net_material_geometry g;
    struct lsf_prepaid_view *record;
    struct net_device *shape = NULL;
    unsigned long at = (unsigned long)device, base;
    u64 bytes;
    unsigned int i;
    lockdep_assert_held(&pool_lock);
    if (!state || !ticket || !lsf_stream_rx_address_locked(device) ||
        lsf_prepaid_stream_net_material_geometry(&g) || !g.netdev_private_bytes ||
        g.netdev_private_bytes > INT_MAX || __alignof__(struct net_device) > 64)
        return NULL;
    bytes = struct_size(shape, priv, (size_t)g.netdev_private_bytes);
    if (bytes == SIZE_MAX || bytes > ULONG_MAX - 63u) return NULL;
    bytes = (bytes + 63u) & ~63ull;
    base = (unsigned long)page_address(factory.pages);
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->offset != at - base) continue;
        *ticket = (struct lsf_prepaid_ticket){i, record->generation};
        if (record->bytes != bytes || !lsf_device_record(&factory.pool, state->owner,
                *ticket, LSF_DEVICE_NETDEV)) return NULL;
        return record;
    }
    return NULL;
}

int lsf_factory_stream_hw_addr_parent(const struct netdev_hw_addr_list *list,
    struct lsf_stream_netdev_source *output)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_ticket ticket;
    struct lsf_prepaid_view *record;
    unsigned long flags, base, at = (unsigned long)list;
    unsigned int i;
    int result = 0;
    if (!output) return -1;
    *output = (struct lsf_stream_netdev_source){};
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_stream_rx_address_locked(list)) goto out;
    result = -1;
    state = lsf_stream_rx_current_locked();
    if (!state) goto out;
    base = (unsigned long)page_address(factory.pages);
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        const struct net_device *device;
        record = &factory.pool.records[i];
        if (record->kind != LSF_DEVICE_NETDEV || record->offset >= LSF_BACKING_BYTES)
            continue;
        device = (void *)(base + record->offset);
        /* Exact embedded lists only; no pointer subtraction/adoption. */
        if (at != (unsigned long)device + offsetof(struct net_device, dev_addrs) &&
            at != (unsigned long)device + offsetof(struct net_device, uc) &&
            at != (unsigned long)device + offsetof(struct net_device, mc)) continue;
        record = lsf_stream_netdev_record_locked(state, device, &ticket);
        if (!record || (record->deferred != LSF_PREPAID_PRIVATE &&
                        record->deferred != LSF_PREPAID_PUBLISHED)) goto out;
        if (record->deferred == LSF_PREPAID_PRIVATE &&
            !lsf_stream_constructor_current_locked(state)) goto out;
        *output = (struct lsf_stream_netdev_source){device};
        result = 1; goto out;
    }
out:
    if (result < 0) { factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1); }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void *lsf_factory_stream_hw_addr_allocate(struct lsf_stream_netdev_source source)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *parent;
    struct lsf_prepaid_ticket parent_ticket, ticket;
    unsigned long flags;
    u64 offset;
    unsigned long bytes = max_t(unsigned long, sizeof(struct netdev_hw_addr), L1_CACHE_BYTES);
    void *result = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    parent = lsf_stream_netdev_record_locked(state, source.device, &parent_ticket);
    if (!parent || L1_CACHE_BYTES > 64 || __alignof__(struct netdev_hw_addr) > 64 ||
        (parent->deferred != LSF_PREPAID_PRIVATE && parent->deferred != LSF_PREPAID_PUBLISHED) ||
        (parent->deferred == LSF_PREPAID_PRIVATE && !lsf_stream_constructor_current_locked(state)))
        goto out;
    /* Public NETDEV callbacks inherit that actual live parent; the original
     * list/RTNL locks and last-use callers remain unchanged. Late drain has
     * no new Root admission. Actual allocation hook seals finalizing births. */
    if (lsf_device_allocate_stream_aligned(&factory.pool, state->owner, bytes,
            LSF_DEVICE_HW_ADDR, parent_ticket, &ticket, 64, &offset)) {
        result = (char *)page_address(factory.pages) + offset;
        memset(result, 0, bytes);
    }
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

static struct lsf_prepaid_view *lsf_stream_hw_addr_record_locked(
    struct lsf_stream_rx_state *state, const void *address, struct lsf_prepaid_ticket *ticket)
{
    struct lsf_prepaid_view *record, *parent;
    unsigned long base, at = (unsigned long)address;
    u64 bytes = (max_t(u64, sizeof(struct netdev_hw_addr), L1_CACHE_BYTES) + 63u) & ~63ull;
    unsigned int i;
    lockdep_assert_held(&pool_lock);
    if (!state || !ticket || !lsf_stream_rx_address_locked(address)) return NULL;
    base = (unsigned long)page_address(factory.pages);
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->offset != at - base) continue;
        *ticket = (struct lsf_prepaid_ticket){i, record->generation};
        if (record->bytes != bytes || !lsf_device_record(&factory.pool, state->owner,
                *ticket, LSF_DEVICE_HW_ADDR)) return NULL;
        parent = lsf_device_record(&factory.pool, state->owner,
            (struct lsf_prepaid_ticket){record->cache_bucket, record->cache_anchor}, LSF_DEVICE_NETDEV);
        if (!parent) return NULL;
        return record;
    }
    return NULL;
}

int lsf_factory_stream_hw_addr_publish(const void *address, struct lsf_stream_netdev_source source)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *record, *parent;
    struct lsf_prepaid_ticket ticket, parent_ticket;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    record = lsf_stream_hw_addr_record_locked(state, address, &ticket);
    parent = lsf_stream_netdev_record_locked(state, source.device, &parent_ticket);
    if (record && parent && record->cache_bucket == parent_ticket.slot &&
        record->cache_anchor == parent_ticket.generation)
        result = lsf_device_publish(&factory.pool, state->owner, ticket, LSF_DEVICE_HW_ADDR);
    if (!result) { factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1); }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_hw_addr_queue(const void *address)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *record;
    struct lsf_prepaid_ticket ticket;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_stream_rx_address_locked(address)) goto out;
    result = -1;
    state = lsf_stream_rx_current_locked();
    record = lsf_stream_hw_addr_record_locked(state, address, &ticket);
    if (record && lsf_device_queue(&factory.pool, state->owner, ticket, LSF_DEVICE_HW_ADDR))
        result = 1;
out:
    if (result < 0) { factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1); }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_hw_addr_finish(const void *address)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *record;
    struct lsf_prepaid_ticket ticket;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    record = lsf_stream_hw_addr_record_locked(state, address, &ticket);
    if (record && record->deferred == LSF_PREPAID_QUEUED)
        result = lsf_device_finish(&factory.pool, state->owner, ticket, LSF_DEVICE_HW_ADDR);
    if (!result) { factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1); }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
