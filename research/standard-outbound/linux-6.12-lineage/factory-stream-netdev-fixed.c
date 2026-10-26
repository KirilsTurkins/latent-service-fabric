/* SPDX-License-Identifier: GPL-2.0-only */
/* Exact constructor and original final-free ports, not an origin-adoption API.
 * Root keeps every original record and a REAL positive parent reference until
 * actual release and all children have completed. No future-row prediction. */
#include <linux/kref.h>
#include <net/lsf_stream_netdev_fixed_private.h>
#include <net/lsf_stream_netdev_cpu_private.h>
#include <net/lsf_stream_netdev_fixed_geometry_private.h>

static int lsf_stream_netdev_fixed_shapes(struct lsf_stream_netdev_fixed_geometry *out,
    struct lsf_stream_net_material_geometry *net)
{
    return !lsf_prepaid_stream_net_material_geometry(net) && net->netdev_private_bytes &&
        net->netdev_private_bytes <= INT_MAX &&
        !lsf_prepaid_stream_netdev_fixed_geometry(net->netdev_private_bytes, out) &&
        out->main_bytes && out->main_bytes <= ULONG_MAX - 63u &&
        out->tx_bytes && out->tx_bytes <= ULONG_MAX - 63u &&
        out->rx_bytes && out->rx_bytes <= ULONG_MAX - 63u &&
        out->ethtool_bytes && out->ethtool_bytes <= ULONG_MAX - 63u;
}

int lsf_factory_stream_netdev_selected(struct virtio_device *vdev)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_ticket parent;
    unsigned long flags;
    int result = -EOPNOTSUPP;
    if (!lsf_factory_selected_consumer()) return 0;
    spin_lock_irqsave(&pool_lock, flags);
    /* Actual driver callback holds this ordinary vdev reference. The global
     * consumer is not per-device provenance. Only genuinely outside objects
     * retain original allocation; an inside/unknown birth still refuses. */
    if (vdev && !lsf_stream_rx_address_locked(vdev)) {
        result = lsf_stream_rx_address_locked(vdev->dev.parent) ? -EOPNOTSUPP : 0;
        goto out;
    }
    state = lsf_stream_rx_current_locked();
    if (lsf_stream_rss_parent_locked(state, vdev, &parent) &&
        lsf_stream_constructor_current_locked(state)) result = 1;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void *lsf_factory_stream_netdev_allocate(struct virtio_device *vdev,
    unsigned long actual_bytes, int private_bytes)
{
    struct lsf_stream_rx_state *state;
    struct lsf_stream_netdev_fixed_geometry g;
    struct lsf_stream_net_material_geometry net;
    struct lsf_prepaid_ticket parent, ticket;
    unsigned long flags;
    u64 offset;
    struct net_device *result = NULL;
    if (!lsf_stream_netdev_fixed_shapes(&g, &net) || actual_bytes != g.main_bytes ||
        private_bytes != net.netdev_private_bytes) return NULL;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    if (!lsf_stream_rss_parent_locked(state, vdev, &parent) ||
        !lsf_stream_constructor_current_locked(state) ||
        lsf_stream_constructor_allocate_locked(state, LSF_DEVICE_NETDEV, parent,
            g.main_bytes, g.main_alignment, &ticket, &offset) != 1) goto out;
    /* Prepaid birth exists BEFORE acquiring this real positive parent ref.
     * Never get_device on a zero-ref object at its later release callback. */
    if (!kobject_get_unless_zero(&vdev->dev.kobj)) goto poison;
    factory.pool.records[ticket.slot].security_cache_location = 1u; /* held parent */
    factory.pool.records[ticket.slot].security_cache_identity = 0u; /* release not seen */
    result = (void *)((char *)page_address(factory.pages) + offset);
    memset(result, 0, g.main_bytes);
    goto out;
poison:
    factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

static int lsf_stream_netdev_child_shape(enum lsf_stream_netdev_fixed_child child,
    const struct lsf_stream_netdev_fixed_geometry *g, unsigned int *kind, u64 *bytes, u64 *alignment)
{
    switch (child) {
    case LSF_STREAM_NETDEV_TX: *kind = LSF_DEVICE_NETDEV_TX; *bytes = g->tx_bytes; *alignment = g->tx_alignment; return 1;
    case LSF_STREAM_NETDEV_RX: *kind = LSF_DEVICE_NETDEV_RX; *bytes = g->rx_bytes; *alignment = g->rx_alignment; return 1;
    case LSF_STREAM_NETDEV_ETHTOOL: *kind = LSF_DEVICE_NETDEV_ETHTOOL; *bytes = g->ethtool_bytes; *alignment = g->ethtool_alignment; return 1;
    }
    return 0;
}

static void *lsf_stream_netdev_child_alias(struct net_device *dev, enum lsf_stream_netdev_fixed_child child)
{
    switch (child) {
    case LSF_STREAM_NETDEV_TX: return dev->_tx;
    case LSF_STREAM_NETDEV_RX: return dev->_rx;
    case LSF_STREAM_NETDEV_ETHTOOL: return dev->ethtool;
    }
    return NULL;
}

static void lsf_stream_netdev_child_clear(struct net_device *dev, enum lsf_stream_netdev_fixed_child child)
{
    switch (child) {
    case LSF_STREAM_NETDEV_TX: dev->_tx = NULL; break;
    case LSF_STREAM_NETDEV_RX: dev->_rx = NULL; break;
    case LSF_STREAM_NETDEV_ETHTOOL: dev->ethtool = NULL; break;
    }
}

static struct lsf_prepaid_view *lsf_stream_netdev_child_record_locked(
    struct lsf_stream_rx_state *state, struct lsf_prepaid_ticket parent, const void *address,
    unsigned int kind, u64 bytes, struct lsf_prepaid_ticket *ticket)
{
    struct lsf_prepaid_view *record;
    unsigned long base = (unsigned long)page_address(factory.pages), at = (unsigned long)address;
    unsigned int i;
    if (!lsf_stream_rx_address_locked(address)) return NULL;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->offset != at - base) continue;
        *ticket = (struct lsf_prepaid_ticket){i, record->generation};
        if (!lsf_device_record(&factory.pool, state->owner, *ticket, kind) ||
            record->bytes != ((bytes + 63u) & ~63ull) ||
            record->cache_bucket != parent.slot || record->cache_anchor != parent.generation)
            return NULL;
        return record;
    }
    return NULL;
}

void *lsf_factory_stream_netdev_fixed_allocate(struct net_device *dev,
    enum lsf_stream_netdev_fixed_child child, unsigned long actual_bytes)
{
    struct lsf_stream_rx_state *state;
    struct lsf_stream_netdev_fixed_geometry g;
    struct lsf_stream_net_material_geometry net;
    struct lsf_prepaid_ticket parent, ticket;
    struct lsf_prepaid_view *record;
    u64 bytes, alignment, offset;
    unsigned int kind, i;
    unsigned long flags;
    void *result = NULL;
    if (!lsf_stream_netdev_fixed_shapes(&g, &net) ||
        !lsf_stream_netdev_child_shape(child, &g, &kind, &bytes, &alignment) || actual_bytes != bytes)
        return NULL;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    record = lsf_stream_netdev_record_locked(state, dev, &parent);
    if (!record || record->deferred != LSF_PREPAID_PRIVATE) goto out;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->owner == state->owner.slot && record->owner_generation == state->owner.generation &&
            record->cache_bucket == parent.slot && record->cache_anchor == parent.generation &&
            record->kind == kind && record->phase != LSF_PREPAID_EMPTY) goto out; /* no hidden retry */
    }
    if (lsf_stream_constructor_allocate_locked(state, kind, parent, bytes, alignment,
            &ticket, &offset) != 1) goto out;
    result = (char *)page_address(factory.pages) + offset;
    memset(result, 0, bytes);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_netdev_fixed_return(struct net_device *dev,
    enum lsf_stream_netdev_fixed_child child)
{
    struct lsf_stream_rx_state *state;
    struct lsf_stream_netdev_fixed_geometry g;
    struct lsf_stream_net_material_geometry net;
    struct lsf_prepaid_view *parent_record, *record;
    struct lsf_prepaid_ticket parent, ticket;
    unsigned int kind, i;
    unsigned long flags;
    u64 bytes, alignment;
    void *address;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_stream_rx_address_locked(dev)) goto out;
    result = -1;
    state = lsf_stream_rx_current_locked();
    parent_record = lsf_stream_netdev_record_locked(state, dev, &parent);
    if (!parent_record || !lsf_stream_netdev_fixed_shapes(&g, &net) ||
        !lsf_stream_netdev_child_shape(child, &g, &kind, &bytes, &alignment)) goto poison;
    address = lsf_stream_netdev_child_alias(dev, child);
    if (!address) {
        for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
            record = &factory.pool.records[i];
            if (record->phase == LSF_PREPAID_LIVE && record->owner == state->owner.slot &&
                record->owner_generation == state->owner.generation && record->kind == kind &&
                record->cache_bucket == parent.slot && record->cache_anchor == parent.generation)
                goto poison;
        }
        result = 1; goto out; /* Actual original NULL free, no view refunded. */
    }
    record = lsf_stream_netdev_child_record_locked(state, parent, address, kind, bytes, &ticket);
    if (!record || (record->deferred != LSF_PREPAID_PRIVATE &&
                    record->deferred != LSF_PREPAID_PUBLISHED)) goto poison;
    lsf_stream_netdev_child_clear(dev, child); /* Actual alias BEFORE return. */
    if ((record->deferred == LSF_PREPAID_PUBLISHED &&
            !lsf_device_queue(&factory.pool, state->owner, ticket, kind)) ||
        !lsf_device_finish(&factory.pool, state->owner, ticket, kind)) goto poison;
    result = 1; goto out;
poison:
    factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_netdev_publish(struct net_device *dev)
{
    struct lsf_stream_rx_state *state;
    struct lsf_stream_netdev_fixed_geometry g;
    struct lsf_stream_net_material_geometry net;
    struct lsf_prepaid_view *parent_record, *record;
    struct lsf_prepaid_ticket parent, child;
    unsigned long flags;
    unsigned int kind;
    enum lsf_stream_netdev_fixed_child selector;
    u64 bytes, alignment;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    parent_record = lsf_stream_netdev_record_locked(state, dev, &parent);
    if (!parent_record || parent_record->deferred != LSF_PREPAID_PRIVATE ||
        parent_record->security_cache_location != 1u || parent_record->security_cache_identity ||
        !lsf_stream_constructor_current_locked(state) || !lsf_stream_netdev_fixed_shapes(&g, &net) ||
        !READ_ONCE(dev->lsf_cpu_storage) || dev->pcpu_refcnt || dev->core_stats) goto poison;
    record = lsf_stream_netdev_child_record_locked(state, parent, dev->lsf_cpu_storage,
        LSF_DEVICE_NETDEV_CPU, sizeof(struct lsf_stream_netdev_cpu_storage), &child);
    if (!record || record->deferred != LSF_PREPAID_PUBLISHED) goto poison;
    for (selector = LSF_STREAM_NETDEV_TX; selector <= LSF_STREAM_NETDEV_ETHTOOL; ++selector) {
        if (!lsf_stream_netdev_child_shape(selector, &g, &kind, &bytes, &alignment)) goto poison;
        record = lsf_stream_netdev_child_record_locked(state, parent,
            lsf_stream_netdev_child_alias(dev, selector), kind, bytes, &child);
        if (!record || !lsf_device_publish(&factory.pool, state->owner, child, kind)) goto poison;
    }
    result = lsf_device_publish(&factory.pool, state->owner, parent, LSF_DEVICE_NETDEV);
    if (!result) goto poison;
    goto out;
poison:
    factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_netdev_release(struct net_device *dev)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *record;
    struct lsf_prepaid_ticket ticket;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_stream_rx_address_locked(dev)) goto out;
    result = -1;
    state = lsf_stream_rx_current_locked();
    record = lsf_stream_netdev_record_locked(state, dev, &ticket);
    if (!record || record->security_cache_location != 1u || record->security_cache_identity ||
        (record->deferred != LSF_PREPAID_PRIVATE && record->deferred != LSF_PREPAID_PUBLISHED))
        goto poison;
    record->security_cache_identity = 1u; /* Actual original final kvfree reached. */
    if ((record->deferred == LSF_PREPAID_PRIVATE &&
            !lsf_device_publish(&factory.pool, state->owner, ticket, LSF_DEVICE_NETDEV)) ||
        !lsf_device_queue(&factory.pool, state->owner, ticket, LSF_DEVICE_NETDEV)) goto poison;
    /* Children may still be in their original RCU callback. Keep both actual
     * NETDEV record and positive VIRTIO parent ref until stop's real barrier. */
    result = 1; goto out;
poison:
    factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Original stop still holds its counted bank loan and real PCI/vdev refs.
 * Called only AFTER PCI removal + actual rcu_barrier, BEFORE those refs/firmware
 * tail are released. No physical put/callback runs under either factory lock. */
static int lsf_stream_netdev_drain_after_remove(struct lsf_stream_rx_state *expected)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *record, *child, *parent;
    struct virtio_device *vdev;
    struct lsf_prepaid_ticket ticket;
    unsigned long flags, base;
    unsigned int pass, i, j;
    for (pass = 0; pass < LSF_ALLOCATION_SLOTS; ++pass) {
        spin_lock_irqsave(&pool_lock, flags);
        state = lsf_stream_rx_current_locked();
        if (state != expected || !state || !state->closing || !state->hardware_stopped ||
            state->device_borrows != 1 || factory.pool.poisoned || READ_ONCE(factory.uncertain))
            goto unknown;
        for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
            record = &factory.pool.records[i];
            if (record->owner == state->owner.slot && record->owner_generation == state->owner.generation &&
                record->kind == LSF_DEVICE_NETDEV && record->phase == LSF_PREPAID_LIVE) break;
        }
        if (i == LSF_ALLOCATION_SLOTS) {
            spin_unlock_irqrestore(&pool_lock, flags); return 0;
        }
        ticket = (struct lsf_prepaid_ticket){i, record->generation};
        if (record->deferred != LSF_PREPAID_QUEUED || record->security_cache_identity != 1u ||
            record->security_cache_location != 1u) goto unknown;
        for (j = 1; j < LSF_ALLOCATION_SLOTS; ++j) {
            child = &factory.pool.records[j];
            if (child->owner == state->owner.slot && child->owner_generation == state->owner.generation &&
                child->cache_bucket == ticket.slot && child->cache_anchor == ticket.generation &&
                child->phase != LSF_PREPAID_RETURNED) goto unknown;
        }
        parent = lsf_device_record(&factory.pool, state->owner,
            (struct lsf_prepaid_ticket){record->cache_bucket, record->cache_anchor}, LSF_DEVICE_VIRTIO);
        base = (unsigned long)page_address(factory.pages);
        if (!parent || parent->bytes < sizeof(*vdev)) goto unknown;
        vdev = (void *)(base + parent->offset);
        if (vdev != state->virtio) goto unknown;
        record->security_cache_location = 0u; /* One real ref moves to fixed stack below. */
        if (!lsf_device_finish(&factory.pool, state->owner, ticket, LSF_DEVICE_NETDEV)) {
            record->security_cache_location = 1u; goto unknown;
        }
        spin_unlock_irqrestore(&pool_lock, flags);
        put_device(&vdev->dev); /* SAME stop loan/ref keeps whole bank through epilogue. */
    }
    return -EOVERFLOW;
unknown:
    factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1);
    spin_unlock_irqrestore(&pool_lock, flags);
    return -EIO; /* SAME owners remain retained; never infer physical cleanup. */
}
