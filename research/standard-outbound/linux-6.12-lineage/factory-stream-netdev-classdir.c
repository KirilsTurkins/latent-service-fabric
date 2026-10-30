/* SPDX-License-Identifier: GPL-2.0-only */
/* Real NETDEV class glue object, from original arena before kobject_add.
 * Each original callback borrow lives in its SAME paid record; no new task,
 * queue, side ledger or ambient allocation. Kernfs readiness stays separate. */
#include <net/lsf_stream_netdev_classdir_private.h>

static int lsf_stream_classdir_shape(unsigned long *bytes, unsigned long *alignment)
{
    return !lsf_prepaid_stream_netdev_classdir_geometry(bytes, alignment) && *bytes &&
        *bytes <= ULONG_MAX - 63u && *alignment && *alignment <= 64u &&
        !(*alignment & (*alignment - 1u));
}

static struct lsf_prepaid_view *lsf_stream_classdir_record_locked(
    struct lsf_stream_rx_state *state, const void *object,
    struct lsf_prepaid_ticket *ticket, struct lsf_prepaid_ticket *parent)
{
    struct lsf_prepaid_view *r, *birth;
    struct lsf_prepaid_ticket checked;
    struct net_device *dev;
    unsigned long base, bytes, alignment;
    unsigned int i;
    lockdep_assert_held(&pool_lock);
    if (!state || !lsf_stream_rx_address_locked(object) ||
        !lsf_stream_classdir_shape(&bytes, &alignment)) return NULL;
    base = (unsigned long)page_address(factory.pages);
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        r = &factory.pool.records[i];
        if (r->offset != (unsigned long)object - base) continue;
        *ticket = (struct lsf_prepaid_ticket){i, r->generation};
        if (!lsf_device_record(&factory.pool, state->owner, *ticket, LSF_DEVICE_NETDEV_CLASSDIR) ||
            r->bytes != ((bytes + 63u) & ~63ull) || r->offset % alignment) return NULL;
        *parent = (struct lsf_prepaid_ticket){r->cache_bucket, r->cache_anchor};
        birth = lsf_device_record(&factory.pool, state->owner, *parent, LSF_DEVICE_NETDEV);
        if (!birth) return NULL;
        dev = (void *)(base + birth->offset);
        if (lsf_stream_netdev_record_locked(state, dev, &checked) != birth ||
            checked.slot != parent->slot || checked.generation != parent->generation) return NULL;
        return r;
    }
    return NULL;
}

int lsf_factory_stream_netdev_classdir_select(struct device *device, struct device *parent)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *r, *virtio;
    struct lsf_prepaid_ticket ticket, ancestor;
    struct net_device *dev;
    unsigned long flags, base;
    int result;
    if (!lsf_factory_selected_consumer()) return 0;
    result = lsf_factory_stream_netdev_core_classify(device, 0);
    spin_lock_irqsave(&pool_lock, flags);
    if (!result) {
        if (!lsf_stream_rx_address_locked(device) && lsf_stream_rx_address_locked(parent))
            result = -EOPNOTSUPP; /* Outside child cannot create an ambient glue alias to paid parent. */
        goto out;
    }
    if (result < 0) goto out;
    result = -EOPNOTSUPP;
    state = lsf_stream_rx_current_locked();
    r = lsf_stream_netdev_core_parent_locked(state, device, 0, &ticket, &dev);
    if (!r || r->deferred != LSF_PREPAID_PUBLISHED ||
        r->security_cache_identity != LSF_STREAM_NETDEV_CORE ||
        !lsf_stream_constructor_current_locked(state) ||
        !lsf_prepaid_stream_netdev_class_known(device->class)) goto out;
    ancestor = (struct lsf_prepaid_ticket){r->cache_bucket, r->cache_anchor};
    virtio = lsf_device_record(&factory.pool, state->owner, ancestor, LSF_DEVICE_VIRTIO);
    if (!virtio || virtio->bytes < sizeof(struct virtio_device)) goto out;
    base = (unsigned long)page_address(factory.pages);
    if ((void *)(base + virtio->offset) != state->virtio ||
        parent != &state->virtio->dev || device->parent != parent) goto out;
    result = 1;
out:
    if (result < 0) { factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1); }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void *lsf_factory_stream_netdev_classdir_allocate(struct device *device)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *r;
    struct lsf_prepaid_ticket parent, ticket;
    struct net_device *dev;
    unsigned long flags, bytes, alignment;
    unsigned int i;
    u64 offset;
    void *result = NULL;
    if (!lsf_stream_classdir_shape(&bytes, &alignment)) return NULL;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    r = lsf_stream_netdev_core_parent_locked(state, device, 0, &parent, &dev);
    if (!r || r->deferred != LSF_PREPAID_PUBLISHED ||
        r->security_cache_identity != LSF_STREAM_NETDEV_CORE ||
        !lsf_stream_constructor_current_locked(state)) goto out;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        r = &factory.pool.records[i];
        if (r->kind == LSF_DEVICE_NETDEV_CLASSDIR && r->owner == state->owner.slot &&
            r->owner_generation == state->owner.generation && r->cache_bucket == parent.slot &&
            r->cache_anchor == parent.generation && r->phase != LSF_PREPAID_EMPTY) goto out;
    }
    if (lsf_stream_constructor_allocate_locked(state, LSF_DEVICE_NETDEV_CLASSDIR,
            parent, bytes, alignment, &ticket, &offset) != 1) goto out;
    result = (char *)page_address(factory.pages) + offset;
    memset(result, 0, bytes);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_netdev_classdir_name(void *object, struct kobject *kobj, const char *name)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *r;
    struct lsf_prepaid_ticket ticket, parent, child;
    unsigned long flags;
    u64 offset;
    char *copy;
    int result = -EOPNOTSUPP;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    r = lsf_stream_classdir_record_locked(state, object, &ticket, &parent);
    if (!r || object != kobj || r->deferred != LSF_PREPAID_PRIVATE ||
        r->security_cache_identity || r->security_cache_location || kobj->name ||
        !lsf_prepaid_stream_netdev_classdir_initialized(kobj)) goto out;
    /* Original kobject_init already completed in the real allocating TU.
     * Save that existing-object fact BEFORE the first fallible name birth;
     * it is cleanup evidence, never new-constructor authority. */
    r->security_cache_identity = LSF_STREAM_CLASSDIR_INITIALIZED;
    if (!lsf_stream_constructor_current_locked(state) || !name ||
        memcmp(name, "net", sizeof("net"))) goto out;
    result = lsf_stream_constructor_allocate_locked(state, LSF_DEVICE_NETDEV_CLASSDIR_NAME,
        ticket, sizeof("net"), 1u, &child, &offset);
    if (result != 1) goto out;
    copy = (char *)page_address(factory.pages) + offset;
    memcpy(copy, name, sizeof("net"));
    if (!lsf_device_publish(&factory.pool, state->owner, child, LSF_DEVICE_NETDEV_CLASSDIR_NAME)) {
        factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1); result = -EIO; goto out;
    }
    kobj->name = copy;
    result = 0;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

static int lsf_stream_classdir_named_locked(struct lsf_stream_rx_state *state,
    struct lsf_prepaid_ticket parent, const struct kobject *object)
{
    unsigned long base = (unsigned long)page_address(factory.pages);
    unsigned int i;
    if (!lsf_stream_rx_address_locked(object->name)) return 0;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        struct lsf_prepaid_view *r = &factory.pool.records[i];
        struct lsf_prepaid_ticket ticket = {i, r->generation};
        if (r->offset != (unsigned long)object->name - base) continue;
        return lsf_device_record(&factory.pool, state->owner, ticket,
            LSF_DEVICE_NETDEV_CLASSDIR_NAME) == r && r->deferred == LSF_PREPAID_PUBLISHED &&
            r->bytes == 64u && r->cache_bucket == parent.slot &&
            r->cache_anchor == parent.generation && !memcmp(object->name, "net", sizeof("net"));
    }
    return 0;
}

int lsf_factory_stream_netdev_classdir_publish(struct device *device, void *object)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *r, *birth;
    struct lsf_prepaid_ticket ticket, parent, actual;
    struct net_device *dev;
    unsigned long flags;
    int result = -EOPNOTSUPP;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    r = lsf_stream_classdir_record_locked(state, object, &ticket, &parent);
    birth = lsf_stream_netdev_core_parent_locked(state, device, 0, &actual, &dev);
    if (r && birth && parent.slot == actual.slot && parent.generation == actual.generation &&
        r->deferred == LSF_PREPAID_PRIVATE && !r->security_cache_location &&
        r->security_cache_identity == LSF_STREAM_CLASSDIR_INITIALIZED &&
        lsf_stream_constructor_current_locked(state) &&
        lsf_stream_classdir_named_locked(state, ticket, object) &&
        lsf_device_publish(&factory.pool, state->owner, ticket, LSF_DEVICE_NETDEV_CLASSDIR)) result = 0;
    if (result) { factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1); }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_netdev_classdir_current(struct device *device, const struct kobject *kobj)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *r, *birth;
    struct lsf_prepaid_ticket ticket, parent, actual;
    struct net_device *dev;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    r = lsf_stream_classdir_record_locked(state, kobj, &ticket, &parent);
    birth = lsf_stream_netdev_core_parent_locked(state, device, 0, &actual, &dev);
    if (r && birth && r->deferred == LSF_PREPAID_PUBLISHED &&
        parent.slot == actual.slot && parent.generation == actual.generation &&
        r->security_cache_identity == LSF_STREAM_CLASSDIR_INITIALIZED && !r->security_cache_location &&
        lsf_stream_classdir_named_locked(state, ticket, kobj) &&
        lsf_stream_constructor_current_locked(state)) result = 1;
    if (!result) { factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1); }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_netdev_classdir_tail_enter(const void *object)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *r;
    struct lsf_prepaid_ticket ticket, parent;
    unsigned long flags;
    unsigned int i;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_stream_rx_address_locked(object)) goto out;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i)
        if (factory.pool.records[i].kind == LSF_DEVICE_NETDEV_CLASSDIR &&
            factory.pool.records[i].offset == (unsigned long)object -
                (unsigned long)page_address(factory.pages)) break;
    if (i == LSF_ALLOCATION_SLOTS) goto out; /* Other root remains with original dispatcher. */
    result = -EOPNOTSUPP;
    state = lsf_stream_rx_current_locked();
    r = lsf_stream_classdir_record_locked(state, object, &ticket, &parent);
    if (!r || r->security_cache_identity != LSF_STREAM_CLASSDIR_INITIALIZED ||
        r->security_cache_location ||
        (r->deferred != LSF_PREPAID_PRIVATE && r->deferred != LSF_PREPAID_PUBLISHED)) goto poison;
    /* A genuine original cleanup after failed naming retires the initialized
     * object even after constructor/closing authority ends. No allocation or
     * external publication occurs here; original context/record gates remain. */
    if (r->deferred == LSF_PREPAID_PRIVATE &&
        !lsf_device_publish(&factory.pool, state->owner, ticket, LSF_DEVICE_NETDEV_CLASSDIR)) goto poison;
    r->security_cache_identity = LSF_STREAM_NETDEV_TAIL_ACTIVE;
    r->security_cache_location = (unsigned long)current; /* Borrowed, never task-dereferenced. */
    result = 1; goto out;
poison:
    factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_netdev_classdir_queue(const void *object)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *r;
    struct lsf_prepaid_ticket ticket, parent;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_stream_rx_address_locked(object)) goto out;
    result = -EOPNOTSUPP;
    state = lsf_stream_rx_current_locked();
    r = lsf_stream_classdir_record_locked(state, object, &ticket, &parent);
    if (!r || r->deferred != LSF_PREPAID_PUBLISHED ||
        r->security_cache_identity != LSF_STREAM_NETDEV_TAIL_ACTIVE ||
        r->security_cache_location != (unsigned long)current ||
        !lsf_device_queue(&factory.pool, state->owner, ticket, LSF_DEVICE_NETDEV_CLASSDIR)) goto poison;
    r->security_cache_identity |= LSF_STREAM_NETDEV_RELEASE;
    result = 1; goto out;
poison:
    factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_netdev_classdir_name_return(const void *object, const void *name)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *r, *child;
    struct lsf_prepaid_ticket ticket, parent, owned;
    unsigned long flags, base;
    unsigned int i;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_stream_rx_address_locked(object)) goto out;
    base = (unsigned long)page_address(factory.pages);
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i)
        if (factory.pool.records[i].kind == LSF_DEVICE_NETDEV_CLASSDIR &&
            factory.pool.records[i].offset == (unsigned long)object - base) break;
    if (i == LSF_ALLOCATION_SLOTS) goto out;
    result = -EOPNOTSUPP;
    state = lsf_stream_rx_current_locked();
    r = lsf_stream_classdir_record_locked(state, object, &ticket, &parent);
    if (!r || r->deferred != LSF_PREPAID_QUEUED ||
        r->security_cache_identity != (LSF_STREAM_NETDEV_TAIL_ACTIVE | LSF_STREAM_NETDEV_RELEASE) ||
        r->security_cache_location != (unsigned long)current ||
        !lsf_stream_rx_address_locked(name) || ((struct kobject *)object)->name != name) goto poison;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        child = &factory.pool.records[i];
        if (child->offset != (unsigned long)name - base) continue;
        owned = (struct lsf_prepaid_ticket){i, child->generation};
        if (!lsf_device_record(&factory.pool, state->owner, owned, LSF_DEVICE_NETDEV_CLASSDIR_NAME) ||
            child->deferred != LSF_PREPAID_PUBLISHED || child->bytes != 64u ||
            child->cache_bucket != ticket.slot || child->cache_anchor != ticket.generation) goto poison;
        ((struct kobject *)object)->name = NULL;
        if (!lsf_device_queue(&factory.pool, state->owner, owned, LSF_DEVICE_NETDEV_CLASSDIR_NAME) ||
            !lsf_device_finish(&factory.pool, state->owner, owned, LSF_DEVICE_NETDEV_CLASSDIR_NAME)) goto poison;
        result = 1; goto out;
    }
poison:
    factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Immutable paid birth authentication ONLY for revoking this record's borrow.
 * Do not use this path for admission, allocation, data access or final return. */
static struct lsf_prepaid_view *lsf_stream_classdir_borrow_locked(const void *object,
    struct lsf_stream_rx_state **retained, struct lsf_prepaid_ticket *ticket)
{
    struct lsf_stream_rx_state *state = lsf_stream_netdev_core_borrow_state_locked();
    struct lsf_prepaid_view *r, *parent;
    unsigned long base, bytes, alignment;
    unsigned int i;
    lockdep_assert_held(&pool_lock);
    if (!state || !lsf_stream_classdir_shape(&bytes, &alignment)) return NULL;
    base = (unsigned long)page_address(factory.pages);
    if ((unsigned long)object < base ||
        (unsigned long)object - base >= LSF_BACKING_BYTES) return NULL;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        r = &factory.pool.records[i];
        if (r->kind != LSF_DEVICE_NETDEV_CLASSDIR || r->offset != (unsigned long)object - base) continue;
        if (r->phase != LSF_PREPAID_LIVE || !r->generation || r->owner != state->owner.slot ||
            r->owner_generation != state->owner.generation || r->bytes != ((bytes + 63u) & ~63ull) ||
            r->offset < LSF_FACTORY_INFRA_OFFSET || r->offset % alignment ||
            r->offset - LSF_FACTORY_INFRA_OFFSET > LSF_FACTORY_INFRA_BYTES ||
            r->bytes > LSF_FACTORY_INFRA_BYTES - (r->offset - LSF_FACTORY_INFRA_OFFSET) ||
            !r->cache_bucket || r->cache_bucket >= LSF_ALLOCATION_SLOTS || !r->cache_anchor) return NULL;
        parent = &factory.pool.records[r->cache_bucket];
        if (parent->phase != LSF_PREPAID_LIVE || parent->kind != LSF_DEVICE_NETDEV ||
            parent->generation != r->cache_anchor || parent->owner != state->owner.slot ||
            parent->owner_generation != state->owner.generation) return NULL;
        *retained = state; *ticket = (struct lsf_prepaid_ticket){i, r->generation};
        return r;
    }
    return NULL;
}

int lsf_factory_stream_netdev_classdir_tail_finish(const void *object)
{
    struct lsf_stream_rx_state *retained = NULL, *state;
    struct lsf_prepaid_view *r, *borrow;
    struct lsf_prepaid_ticket ticket, parent, held;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    borrow = lsf_stream_classdir_borrow_locked(object, &retained, &held);
    if (!borrow || borrow->security_cache_location != (unsigned long)current) goto out;
    borrow->security_cache_location = 0u; /* Exact object+current borrow revoked before any validation. */
    result = -EOPNOTSUPP;
    state = lsf_stream_rx_current_locked();
    r = lsf_stream_classdir_record_locked(state, object, &ticket, &parent);
    if (state != retained || r != borrow || ticket.slot != held.slot ||
        ticket.generation != held.generation || r->deferred != LSF_PREPAID_QUEUED ||
        r->security_cache_identity != (LSF_STREAM_NETDEV_TAIL_ACTIVE | LSF_STREAM_NETDEV_RELEASE) ||
        !lsf_device_finish(&factory.pool, state->owner, ticket, LSF_DEVICE_NETDEV_CLASSDIR)) goto poison;
    /* Cached name and original parent put already returned. Never read object
     * payload after this actual final view return. Original Root still owns the bank. */
    result = 1; goto out;
poison:
    factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
