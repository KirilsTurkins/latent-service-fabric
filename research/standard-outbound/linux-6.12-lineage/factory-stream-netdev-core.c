/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual embedded NETDEV device, private metadata and full kobject epilogue.
 * SAME original records/arena/positive VIRTIO ref. No new queue or task. */
#include <net/lsf_stream_netdev_core_private.h>

static struct lsf_prepaid_view *lsf_stream_netdev_core_parent_locked(
    struct lsf_stream_rx_state *state, const void *address, unsigned int kobject,
    struct lsf_prepaid_ticket *ticket, struct net_device **dev)
{
    unsigned long displacement = offsetof(struct net_device, dev), base, value;
    if (kobject) displacement += offsetof(struct device, kobj);
    lockdep_assert_held(&pool_lock);
    if (!lsf_stream_rx_address_locked(address)) return NULL;
    base = (unsigned long)page_address(factory.pages); value = (unsigned long)address;
    if (value - base < displacement) return NULL;
    *dev = (void *)(value - displacement);
    return lsf_stream_netdev_record_locked(state, *dev, ticket);
}

/* 0 is not a NETDEV root; existing PCI/outside dispatch remains authoritative.
 * A matching NETDEV birth must authenticate before any object dereference. */
int lsf_factory_stream_netdev_core_classify(const void *address, unsigned int kobject)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_ticket ticket;
    struct net_device *dev;
    unsigned long flags, base, at = (unsigned long)address;
    unsigned long displacement = offsetof(struct net_device, dev);
    unsigned int i;
    int result = 0;
    if (kobject > 1u) return -EOPNOTSUPP;
    if (kobject) displacement += offsetof(struct device, kobj);
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_stream_rx_address_locked(address)) goto out;
    base = (unsigned long)page_address(factory.pages);
    if (at - base < displacement) goto out;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        const struct lsf_prepaid_view *r = &factory.pool.records[i];
        if (r->kind != LSF_DEVICE_NETDEV || r->offset != at - base - displacement) continue;
        result = -EOPNOTSUPP;
        state = lsf_stream_rx_current_locked();
        if (lsf_stream_netdev_core_parent_locked(state, address, kobject, &ticket, &dev)) result = 1;
        break;
    }
out:
    if (result < 0) { factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1); }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

static int lsf_stream_netdev_core_shape(unsigned long *bytes, unsigned long *alignment)
{
    return !lsf_prepaid_stream_netdev_core_geometry(bytes, alignment) && *bytes &&
        *bytes <= ULONG_MAX - 63u && *alignment && *alignment <= 64u &&
        !(*alignment & (*alignment - 1u));
}

int lsf_factory_stream_netdev_core_begin(struct net_device *dev)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *r;
    struct lsf_prepaid_ticket ticket;
    unsigned long flags;
    int kind = lsf_factory_stream_netdev_core_classify(&dev->dev, 0), result = -EOPNOTSUPP;
    if (!kind) return 0; /* The ordinary device_initialize path is unchanged. */
    if (kind < 0) return kind;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    r = lsf_stream_netdev_record_locked(state, dev, &ticket);
    if (!r || r->deferred != LSF_PREPAID_PUBLISHED ||
        !lsf_stream_constructor_current_locked(state) || IS_ENABLED(CONFIG_DEBUG_KOBJECT_RELEASE) ||
        r->security_cache_identity || dev->dev.p) goto poison;
    r->security_cache_identity = LSF_STREAM_NETDEV_CORE;
    result = 0; goto out;
poison:
    factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_netdev_core_owned(const void *address)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *r;
    struct lsf_prepaid_ticket ticket;
    struct net_device *dev;
    unsigned long flags;
    int result = -EOPNOTSUPP;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    r = lsf_stream_netdev_core_parent_locked(state, address, 0, &ticket, &dev);
    if (r && r->deferred == LSF_PREPAID_PUBLISHED &&
        r->security_cache_identity == LSF_STREAM_NETDEV_CORE &&
        lsf_stream_constructor_current_locked(state)) result = 1;
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

static struct lsf_prepaid_view *lsf_stream_netdev_core_child_locked(
    struct lsf_stream_rx_state *state, struct lsf_prepaid_ticket parent,
    struct lsf_prepaid_ticket *ticket)
{
    struct lsf_prepaid_view *found = NULL;
    unsigned int i;
    lockdep_assert_held(&pool_lock);
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        struct lsf_prepaid_view *r = &factory.pool.records[i];
        if (r->kind != LSF_DEVICE_NETDEV_CORE || r->owner != state->owner.slot ||
            r->owner_generation != state->owner.generation ||
            r->cache_bucket != parent.slot || r->cache_anchor != parent.generation ||
            r->phase == LSF_PREPAID_EMPTY) continue;
        if (found) { factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1); return NULL; }
        found = r; *ticket = (struct lsf_prepaid_ticket){i, r->generation};
    }
    return found;
}

void *lsf_factory_stream_netdev_core_allocate(const void *address, unsigned long actual_bytes)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *r;
    struct lsf_prepaid_ticket parent, child;
    struct net_device *dev;
    unsigned long flags, bytes, alignment;
    u64 offset;
    void *result = NULL;
    if (!lsf_stream_netdev_core_shape(&bytes, &alignment) || actual_bytes != bytes) return NULL;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    r = lsf_stream_netdev_core_parent_locked(state, address, 0, &parent, &dev);
    if (!r || r->deferred != LSF_PREPAID_PUBLISHED ||
        r->security_cache_identity != LSF_STREAM_NETDEV_CORE || dev->dev.p ||
        !lsf_stream_constructor_current_locked(state) ||
        lsf_stream_netdev_core_child_locked(state, parent, &child) ||
        factory.pool.poisoned || READ_ONCE(factory.uncertain)) goto out;
    if (lsf_stream_constructor_allocate_locked(state, LSF_DEVICE_NETDEV_CORE,
            parent, bytes, alignment, &child, &offset) != 1) goto out;
    result = (char *)page_address(factory.pages) + offset;
    memset(result, 0, bytes);
    if (!lsf_device_publish(&factory.pool, state->owner, child, LSF_DEVICE_NETDEV_CORE)) {
        factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1); result = NULL;
    }
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_netdev_core_return(const void *address, const void *metadata)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *r, *child;
    struct lsf_prepaid_ticket parent, ticket;
    struct net_device *dev;
    unsigned long flags, bytes, alignment, base;
    unsigned int bits;
    int result = -EOPNOTSUPP;
    if (!lsf_stream_netdev_core_shape(&bytes, &alignment)) return result;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    r = lsf_stream_netdev_core_parent_locked(state, address, 0, &parent, &dev);
    if (!r) goto poison;
    bits = r->security_cache_identity;
    if (!(bits & LSF_STREAM_NETDEV_CORE) || (bits & LSF_STREAM_NETDEV_TAIL_DONE) ||
        !(((bits & LSF_STREAM_NETDEV_TAIL_ACTIVE) && state->netdev_tail_task == current) ||
          (!(bits & (LSF_STREAM_NETDEV_TAIL_ACTIVE | LSF_STREAM_NETDEV_RELEASE)) &&
           lsf_stream_constructor_current_locked(state)))) goto poison;
    child = lsf_stream_netdev_core_child_locked(state, parent, &ticket);
    if (factory.pool.poisoned || READ_ONCE(factory.uncertain)) goto poison;
    if (!metadata) {
        if (dev->dev.p || (child && child->phase != LSF_PREPAID_RETURNED)) goto poison;
        result = 0; goto out;
    }
    base = (unsigned long)page_address(factory.pages);
    if (!child || dev->dev.p != metadata ||
        child->offset != (unsigned long)metadata - base || child->offset % alignment ||
        child->bytes != ((bytes + 63u) & ~63ull) ||
        !lsf_device_record(&factory.pool, state->owner, ticket, LSF_DEVICE_NETDEV_CORE) ||
        child->deferred != LSF_PREPAID_PUBLISHED) goto poison;
    dev->dev.p = NULL; /* Original cached p remains valid through its actual return. */
    if (!lsf_device_queue(&factory.pool, state->owner, ticket, LSF_DEVICE_NETDEV_CORE) ||
        !lsf_device_finish(&factory.pool, state->owner, ticket, LSF_DEVICE_NETDEV_CORE)) goto poison;
    result = 1; goto out;
poison:
    factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Retained storage authentication ONLY for synchronous borrow revocation.
 * Poison/closed state cannot lend authority or finish a record here. Original
 * immutable owner/root/state births and extents must still match, and the
 * caller may ONLY clear the exact current+object pair it installed at entry. */
static struct lsf_stream_rx_state *lsf_stream_netdev_core_borrow_state_locked(void)
{
    struct lsf_stream_rx_state *state = lsf_stream_rx;
    struct lsf_prepaid_view *r, *root;
    struct lsf_prepaid_key key;
    struct lsf_prepaid_ticket parent;
    unsigned long base, at = (unsigned long)state;
    unsigned int i;
    lockdep_assert_held(&pool_lock);
    if (!factory.pages || !factory.device || !state || !factory.pool.initialized) return NULL;
    key = factory.device->key; parent = factory.device->root;
    if (key.slot != LSF_DEVICE_OWNER_SLOT || !key.generation ||
        factory.pool.contexts[key.slot].generation != key.generation ||
        !parent.slot || parent.slot >= LSF_ALLOCATION_SLOTS || !parent.generation) return NULL;
    base = (unsigned long)page_address(factory.pages);
    if (at < base || at - base < LSF_FACTORY_INFRA_OFFSET ||
        at - base - LSF_FACTORY_INFRA_OFFSET > LSF_FACTORY_INFRA_BYTES - sizeof(*state)) return NULL;
    root = &factory.pool.records[parent.slot];
    if (root->phase != LSF_PREPAID_LIVE || root->kind != LSF_DEVICE_ROOT ||
        root->generation != parent.generation || root->owner != key.slot ||
        root->owner_generation != key.generation || root->offset < LSF_FACTORY_INFRA_OFFSET ||
        root->offset - LSF_FACTORY_INFRA_OFFSET > LSF_FACTORY_INFRA_BYTES ||
        !root->bytes || root->bytes > LSF_FACTORY_INFRA_BYTES -
            (root->offset - LSF_FACTORY_INFRA_OFFSET)) return NULL;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        r = &factory.pool.records[i];
        if (r->offset != at - base || r->kind != LSF_DEVICE_QUEUE) continue;
        if (r->phase != LSF_PREPAID_LIVE || !r->generation ||
            r->owner != key.slot || r->owner_generation != key.generation ||
            r->bytes < sizeof(*state) || r->offset < LSF_FACTORY_INFRA_OFFSET ||
            r->offset - LSF_FACTORY_INFRA_OFFSET > LSF_FACTORY_INFRA_BYTES ||
            r->bytes > LSF_FACTORY_INFRA_BYTES - (r->offset - LSF_FACTORY_INFRA_OFFSET) ||
            r->cache_bucket != parent.slot || r->cache_anchor != parent.generation) return NULL;
        if (state->state.slot != i || state->state.generation != r->generation ||
            state->owner.slot != key.slot || state->owner.generation != key.generation ||
            state->root.slot != parent.slot || state->root.generation != parent.generation) return NULL;
        return state;
    }
    return NULL;
}

int lsf_factory_stream_netdev_core_tail_enter(const void *address)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *r;
    struct lsf_prepaid_ticket ticket;
    struct net_device *dev;
    unsigned long flags;
    int result = -EOPNOTSUPP;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    r = lsf_stream_netdev_core_parent_locked(state, address, 1, &ticket, &dev);
    if (!r || r->deferred != LSF_PREPAID_PUBLISHED ||
        r->security_cache_identity != LSF_STREAM_NETDEV_CORE ||
        state->netdev_tail_task || state->netdev_tail_object)
        goto poison;
    r->security_cache_identity |= LSF_STREAM_NETDEV_TAIL_ACTIVE;
    state->netdev_tail_object = address;
    state->netdev_tail_task = current; /* Borrowed only across this original synchronous tail. */
    result = 1; goto out;
poison:
    factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_netdev_core_tail_finish(const void *address)
{
    struct lsf_stream_rx_state *state, *borrow;
    struct lsf_prepaid_view *r, *child;
    struct lsf_prepaid_ticket parent, ticket;
    struct net_device *dev;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    borrow = lsf_stream_netdev_core_borrow_state_locked();
    if (!borrow || borrow->netdev_tail_task != current || borrow->netdev_tail_object != address)
        goto out; /* Not this original NETDEV callback; existing PCI dispatch remains authoritative. */
    /* Revoke the exact callback pair BEFORE any poison-sensitive classifier,
     * child lookup, completion check or error path. This does not authorize
     * any operation/return, and never touches another task/nested object. */
    borrow->netdev_tail_task = NULL;
    borrow->netdev_tail_object = NULL;
    result = -EOPNOTSUPP;
    state = lsf_stream_rx_current_locked();
    r = lsf_stream_netdev_core_parent_locked(state, address, 1, &parent, &dev);
    if (state != borrow || !r || r->deferred != LSF_PREPAID_QUEUED ||
        r->security_cache_identity != (LSF_STREAM_NETDEV_CORE | LSF_STREAM_NETDEV_RELEASE |
                                       LSF_STREAM_NETDEV_TAIL_ACTIVE)) goto poison;
    child = lsf_stream_netdev_core_child_locked(state, parent, &ticket);
    if (factory.pool.poisoned || READ_ONCE(factory.uncertain) ||
        (child && child->phase != LSF_PREPAID_RETURNED)) goto poison;
    /* Original release, cached-name free and parent kobject_put all returned.
     * No payload dereference follows; the queued whole NETDEV still retains
     * its original positive VIRTIO reference until stop drains its children. */
    r->security_cache_identity &= ~LSF_STREAM_NETDEV_TAIL_ACTIVE;
    r->security_cache_identity |= LSF_STREAM_NETDEV_TAIL_DONE;
    result = 1; goto out;
poison:
    factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_netdev_core_name(struct net_device *dev)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *r;
    struct lsf_prepaid_ticket parent, ticket;
    unsigned long flags;
    unsigned int i;
    size_t length;
    u64 offset;
    char *copy;
    int result = -EOPNOTSUPP;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    r = lsf_stream_netdev_record_locked(state, dev, &parent);
    if (!r || r->deferred != LSF_PREPAID_PUBLISHED ||
        r->security_cache_identity != LSF_STREAM_NETDEV_CORE || dev->dev.kobj.name ||
        !lsf_stream_constructor_current_locked(state)) goto out;
    length = strnlen(dev->name, sizeof(dev->name));
    if (!length || length == sizeof(dev->name) || memchr(dev->name, '/', length)) goto out;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        r = &factory.pool.records[i];
        if (r->kind == LSF_DEVICE_NETDEV_CORE_NAME && r->owner == state->owner.slot &&
            r->owner_generation == state->owner.generation && r->cache_bucket == parent.slot &&
            r->cache_anchor == parent.generation && r->phase != LSF_PREPAID_EMPTY) goto out;
    }
    result = lsf_stream_constructor_allocate_locked(state, LSF_DEVICE_NETDEV_CORE_NAME,
        parent, sizeof(dev->name), __alignof__(dev->name), &ticket, &offset);
    if (result != 1) goto out;
    copy = (char *)page_address(factory.pages) + offset;
    memset(copy, 0, sizeof(dev->name)); memcpy(copy, dev->name, length + 1);
    if (!lsf_device_publish(&factory.pool, state->owner, ticket, LSF_DEVICE_NETDEV_CORE_NAME)) {
        factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1); result = -EIO; goto out;
    }
    /* Exact original format is "%s", source is the already validated fixed
     * NETDEV array (no slash). Publish its original paid copy BEFORE alias. */
    dev->dev.kobj.name = copy;
    result = 0;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_netdev_core_name_return(const void *kobject, const void *name)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *r, *birth;
    struct lsf_prepaid_ticket ticket, parent;
    struct net_device *dev;
    unsigned long flags, base;
    unsigned int i;
    int kind = lsf_factory_stream_netdev_core_classify(kobject, 1), result = -EOPNOTSUPP;
    if (kind <= 0) return kind; /* Existing non-NETDEV private cleanup unchanged. */
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    birth = lsf_stream_netdev_core_parent_locked(state, kobject, 1, &parent, &dev);
    if (!birth || !lsf_stream_rx_address_locked(name) || state->netdev_tail_task != current ||
        birth->deferred != LSF_PREPAID_QUEUED || dev->dev.kobj.name != name ||
        birth->security_cache_identity != (LSF_STREAM_NETDEV_CORE | LSF_STREAM_NETDEV_RELEASE |
                                            LSF_STREAM_NETDEV_TAIL_ACTIVE)) goto poison;
    base = (unsigned long)page_address(factory.pages);
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        r = &factory.pool.records[i];
        if (r->offset != (unsigned long)name - base) continue;
        ticket = (struct lsf_prepaid_ticket){i, r->generation};
        if (!lsf_device_record(&factory.pool, state->owner, ticket, LSF_DEVICE_NETDEV_CORE_NAME) ||
            r->bytes != ((sizeof(dev->name) + 63u) & ~63ull) ||
            r->deferred != LSF_PREPAID_PUBLISHED || r->cache_bucket != parent.slot ||
            r->cache_anchor != parent.generation) goto poison;
        dev->dev.kobj.name = NULL; /* Original cleanup already cached name. */
        if (!lsf_device_queue(&factory.pool, state->owner, ticket, LSF_DEVICE_NETDEV_CORE_NAME) ||
            !lsf_device_finish(&factory.pool, state->owner, ticket, LSF_DEVICE_NETDEV_CORE_NAME)) goto poison;
        result = 1; goto out;
    }
poison:
    factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
