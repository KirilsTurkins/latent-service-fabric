/* SPDX-License-Identifier: GPL-2.0-only */
/* Unselected empty class-directory ownership; original funded arena only. */
#include <net/lsf_stream_classdir_registration_private.h>

/* Only actual post-epilogue metadata is inspected here. The native kobject
 * and its parent-put tail may already be dead; never borrow their payload.
 * Every actual child, including an unknown/non-returned phase, retains parent. */
static int lsf_stream_classdir_children_locked(struct lsf_stream_rx_state *state,
    struct lsf_prepaid_ticket parent)
{
    unsigned int i;
    lockdep_assert_held(&pool_lock);
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        struct lsf_prepaid_view *child = &factory.pool.records[i];
        if (child->owner == state->owner.slot && child->owner_generation == state->owner.generation &&
            child->cache_bucket == parent.slot && child->cache_anchor == parent.generation &&
            child->phase != LSF_PREPAID_RETURNED) return 1;
    }
    return 0;
}

/* 1: actual completed parent returned; 0: still legitimately retained;
 * negative: missing/changed original proof. No constructor admission here. */
static int lsf_stream_classdir_try_finish_locked(struct lsf_stream_rx_state *state,
    struct lsf_prepaid_ticket ticket)
{
    struct lsf_prepaid_view *r, *checked;
    struct lsf_prepaid_ticket same, parent;
    const void *object;
    lockdep_assert_held(&pool_lock);
    if (!state || !factory.pages || !ticket.slot || ticket.slot >= LSF_ALLOCATION_SLOTS)
        return -EIO;
    r = lsf_device_record(&factory.pool, state->owner, ticket, LSF_DEVICE_NETDEV_CLASSDIR);
    if (!r) return -EIO;
    object = (char *)page_address(factory.pages) + r->offset;
    checked = lsf_stream_classdir_record_locked(state, object, &same, &parent);
    if (checked != r || same.slot != ticket.slot || same.generation != ticket.generation)
        return -EIO;
    if (r->security_cache_identity != (LSF_STREAM_CLASSDIR_TAIL_DONE | LSF_STREAM_NETDEV_RELEASE))
        return 0; /* Real original kobject epilogue has not completed. */
    if (r->deferred != LSF_PREPAID_QUEUED || r->security_cache_location) return -EIO;
    if (lsf_stream_classdir_children_locked(state, ticket)) return 0;
    return lsf_device_finish(&factory.pool, state->owner, ticket,
        LSF_DEVICE_NETDEV_CLASSDIR) ? 1 : -EIO;
}

/* Original stop holds its SAME counted bank loan + PCI/vdev refs. Run after
 * the real RCU barrier and before NETDEV drain/device puts; no callbacks here. */
static int lsf_stream_classdir_drain_after_remove(struct lsf_stream_rx_state *expected)
{
    struct lsf_stream_rx_state *state;
    unsigned long flags;
    unsigned int i;
    int result, pending = 0;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    if (!state || state != expected || !state->closing || !state->hardware_stopped ||
        state->device_borrows != 1 || factory.pool.poisoned || READ_ONCE(factory.uncertain))
        goto poison;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        struct lsf_prepaid_view *r = &factory.pool.records[i];
        if (r->owner != state->owner.slot || r->owner_generation != state->owner.generation ||
            r->kind != LSF_DEVICE_NETDEV_CLASSDIR || r->phase != LSF_PREPAID_LIVE) continue;
        result = lsf_stream_classdir_try_finish_locked(state,
            (struct lsf_prepaid_ticket){i, r->generation});
        if (result < 0) goto poison;
        if (!result) pending = 1;
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return pending ? -EBUSY : 0; /* No timeout/refund or inferred child death. */
poison:
    factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1);
    spin_unlock_irqrestore(&pool_lock, flags);
    return -EIO;
}

static_assert(LSF_STREAM_CLASSDIR_NODE == LSF_DEVICE_STREAM_CLASSDIR_NODE);
static_assert(LSF_STREAM_CLASSDIR_NAME == LSF_DEVICE_STREAM_CLASSDIR_NAME);
static_assert(LSF_STREAM_CLASSDIR_IDR == LSF_DEVICE_STREAM_CLASSDIR_IDR);

static void lsf_stream_classdir_unknown_locked(void)
{
    lockdep_assert_held(&pool_lock);
    factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1);
}

void lsf_factory_stream_classdir_retain_unknown(void)
{
    unsigned long flags;
    spin_lock_irqsave(&pool_lock, flags);
    lsf_stream_classdir_unknown_locked();
    spin_unlock_irqrestore(&pool_lock, flags);
}

static int lsf_stream_classdir_registration_shape(unsigned int kind,
    unsigned long *bytes, unsigned long *alignment)
{
    if (kind == LSF_STREAM_CLASSDIR_NODE) {
        *bytes = sizeof(struct kernfs_node); *alignment = __alignof__(struct kernfs_node);
    } else if (kind == LSF_STREAM_CLASSDIR_IDR) {
        *bytes = sizeof(struct radix_tree_node); *alignment = __alignof__(struct radix_tree_node);
    } else if (kind == LSF_STREAM_CLASSDIR_NAME) {
        *bytes = sizeof("net"); *alignment = 1u;
    } else return 0;
    return *bytes && *bytes <= ULONG_MAX - 63u && *alignment && *alignment <= 64u &&
        !(*alignment & (*alignment - 1u));
}

/* Discriminate ONLY this namespace before poison-sensitive authorization.
 * A zero result supplies no authority; original namespaces still validate it. */
static struct lsf_prepaid_view *lsf_stream_classdir_raw_locked(const void *address,
    unsigned int kind, struct lsf_prepaid_ticket *ticket)
{
    unsigned long base, value = (unsigned long)address;
    unsigned int i;
    lockdep_assert_held(&pool_lock);
    if (!factory.pages) return NULL;
    base = (unsigned long)page_address(factory.pages);
    if (value < base || value - base >= LSF_BACKING_BYTES) return NULL;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        struct lsf_prepaid_view *r = &factory.pool.records[i];
        if (r->offset != value - base || r->kind != kind) continue;
        *ticket = (struct lsf_prepaid_ticket){i, r->generation};
        return r;
    }
    return NULL;
}

static struct lsf_prepaid_view *lsf_stream_classdir_source_record_locked(
    struct lsf_stream_rx_state *state, struct lsf_stream_classdir_registration_source source,
    unsigned int deferred)
{
    struct lsf_prepaid_ticket ticket = {source.slot, source.generation};
    struct lsf_prepaid_ticket parent = {source.class_slot, source.class_generation}, same, unused;
    struct lsf_prepaid_view *r, *class, *netdev, *virtio;
    const void *object;
    unsigned long bytes, alignment, base;
    lockdep_assert_held(&pool_lock);
    if (!state || !factory.pages || !parent.slot || parent.slot >= LSF_ALLOCATION_SLOTS)
        return NULL;
    class = lsf_device_record(&factory.pool, state->owner, parent, LSF_DEVICE_NETDEV_CLASSDIR);
    if (!class) return NULL;
    base = (unsigned long)page_address(factory.pages);
    object = (void *)(base + class->offset);
    if (lsf_stream_classdir_record_locked(state, object, &same, &unused) != class ||
        same.slot != parent.slot || same.generation != parent.generation) return NULL;
    netdev = lsf_device_record(&factory.pool, state->owner, unused, LSF_DEVICE_NETDEV);
    if (!netdev || netdev->security_cache_location != 1u) return NULL;
    virtio = lsf_device_record(&factory.pool, state->owner,
        (struct lsf_prepaid_ticket){netdev->cache_bucket, netdev->cache_anchor}, LSF_DEVICE_VIRTIO);
    if (!virtio || virtio->bytes < sizeof(struct virtio_device) ||
        state->virtio != (void *)(base + virtio->offset)) return NULL;
    if (source.kind == LSF_DEVICE_NETDEV_CLASSDIR) {
        if (source.slot != parent.slot || source.generation != parent.generation ||
            source.address != object) return NULL;
        r = class;
    } else {
        if (!lsf_stream_classdir_registration_shape(source.kind, &bytes, &alignment)) return NULL;
        r = lsf_device_record(&factory.pool, state->owner, ticket, source.kind);
        if (!r || r->cache_bucket != parent.slot || r->cache_anchor != parent.generation ||
            r->bytes != ((bytes + 63u) & ~63ull) || r->offset % alignment ||
            source.address != (void *)(base + r->offset)) return NULL;
    }
    if (deferred && r->deferred != deferred) return NULL;
    return r;
}

static void lsf_stream_classdir_copy(const void *address, struct lsf_prepaid_ticket ticket,
    unsigned int kind, struct lsf_prepaid_view *r,
    struct lsf_stream_classdir_registration_source *copy)
{
    *copy = (struct lsf_stream_classdir_registration_source){
        .address = address, .slot = ticket.slot, .generation = ticket.generation, .kind = kind,
        .class_slot = kind == LSF_DEVICE_NETDEV_CLASSDIR ? ticket.slot : r->cache_bucket,
        .class_generation = kind == LSF_DEVICE_NETDEV_CLASSDIR ? ticket.generation : r->cache_anchor,
    };
}

static int lsf_stream_classdir_registration_current_locked(struct lsf_stream_rx_state *state,
    struct lsf_stream_classdir_registration_source source)
{
    struct lsf_prepaid_view *class;
    lockdep_assert_held(&pool_lock);
    if ((source.kind != LSF_DEVICE_NETDEV_CLASSDIR && source.kind != LSF_STREAM_CLASSDIR_NODE) ||
        !lsf_stream_classdir_source_record_locked(state, source, LSF_PREPAID_PUBLISHED) ||
        !lsf_stream_constructor_current_locked(state)) return 0;
    class = lsf_device_record(&factory.pool, state->owner,
        (struct lsf_prepaid_ticket){source.class_slot, source.class_generation}, LSF_DEVICE_NETDEV_CLASSDIR);
    return class && class->deferred == LSF_PREPAID_PUBLISHED &&
        class->security_cache_identity == LSF_STREAM_CLASSDIR_INITIALIZED &&
        !class->security_cache_location;
}

int lsf_factory_stream_classdir_kobject(const struct kobject *kobj,
    struct lsf_stream_classdir_registration_source *copy)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_ticket ticket;
    struct lsf_prepaid_view *r;
    unsigned long flags;
    int result = 0;
    if (!copy) return -EINVAL;
    if (!lsf_factory_selected_consumer()) return 0;
    spin_lock_irqsave(&pool_lock, flags);
    r = lsf_stream_classdir_raw_locked(kobj, LSF_DEVICE_NETDEV_CLASSDIR, &ticket);
    if (!r) goto out;
    result = -EOPNOTSUPP;
    state = lsf_stream_rx_current_locked();
    lsf_stream_classdir_copy(kobj, ticket, LSF_DEVICE_NETDEV_CLASSDIR, r, copy);
    if (!lsf_stream_classdir_registration_current_locked(state, *copy) || kobj->sd ||
        !state->virtio || kobj->parent != &state->virtio->dev.kobj ||
        !lsf_prepaid_stream_netdev_classdir_initialized(kobj) ||
        !lsf_stream_classdir_named_locked(state, ticket, kobj)) goto poison;
    result = 1; goto out;
poison:
    lsf_stream_classdir_unknown_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

static int lsf_stream_classdir_lookup_locked(const void *address, unsigned int kind,
    struct lsf_stream_classdir_registration_source *copy)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_ticket ticket;
    struct lsf_prepaid_view *r;
    lockdep_assert_held(&pool_lock);
    r = lsf_stream_classdir_raw_locked(address, kind, &ticket);
    if (!r) return 0;
    state = lsf_stream_rx_current_locked();
    lsf_stream_classdir_copy(address, ticket, kind, r, copy);
    if (!lsf_stream_classdir_source_record_locked(state, *copy, 0) ||
        (r->deferred != LSF_PREPAID_PUBLISHED && r->deferred != LSF_PREPAID_QUEUED)) {
        lsf_stream_classdir_unknown_locked(); return -EOPNOTSUPP;
    }
    return 1;
}

int lsf_factory_stream_classdir_node(const void *address,
    struct lsf_stream_classdir_registration_source *copy)
{
    unsigned long flags;
    int result;
    if (!copy) return -EINVAL;
    if (!lsf_factory_selected_consumer()) return 0;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_stream_classdir_lookup_locked(address, LSF_STREAM_CLASSDIR_NODE, copy);
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_classdir_current(struct lsf_stream_classdir_registration_source source)
{
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_stream_classdir_registration_current_locked(lsf_stream_rx_current_locked(), source);
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void *lsf_factory_stream_classdir_allocate(struct lsf_stream_classdir_registration_source source,
    unsigned long bytes, unsigned int kind)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_ticket ticket, parent = {source.class_slot, source.class_generation};
    unsigned long flags, expected, alignment;
    u64 offset;
    void *result = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    if (!lsf_stream_classdir_registration_shape(kind, &expected, &alignment) || bytes != expected ||
        !lsf_stream_classdir_registration_current_locked(state, source) ||
        (kind != LSF_STREAM_CLASSDIR_NODE && kind != LSF_STREAM_CLASSDIR_IDR) ||
        (kind == LSF_STREAM_CLASSDIR_NODE && source.kind != LSF_DEVICE_NETDEV_CLASSDIR) ||
        (kind == LSF_STREAM_CLASSDIR_IDR && source.kind != LSF_STREAM_CLASSDIR_NODE)) goto out;
    if (lsf_stream_constructor_allocate_locked(state, kind, parent, bytes, alignment,
            &ticket, &offset) != 1) goto out;
    result = (char *)page_address(factory.pages) + offset;
    memset(result, 0, bytes);
    if (!lsf_device_publish(&factory.pool, state->owner, ticket, kind)) {
        lsf_stream_classdir_unknown_locked(); result = NULL;
    }
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

char *lsf_factory_stream_classdir_name(struct lsf_stream_classdir_registration_source source,
    const char *name)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *class;
    struct lsf_prepaid_ticket ticket, parent = {source.class_slot, source.class_generation};
    unsigned long flags;
    u64 offset;
    char *result = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    class = lsf_stream_classdir_source_record_locked(state, source, LSF_PREPAID_PUBLISHED);
    if (source.kind != LSF_DEVICE_NETDEV_CLASSDIR || !class ||
        !lsf_stream_classdir_registration_current_locked(state, source) ||
        ((struct kobject *)source.address)->name != name ||
        !lsf_stream_classdir_named_locked(state, parent, source.address)) goto out;
    if (lsf_stream_constructor_allocate_locked(state, LSF_STREAM_CLASSDIR_NAME, parent,
            sizeof("net"), 1u, &ticket, &offset) != 1) goto out;
    result = (char *)page_address(factory.pages) + offset;
    memcpy(result, name, sizeof("net"));
    if (!lsf_device_publish(&factory.pool, state->owner, ticket, LSF_STREAM_CLASSDIR_NAME)) {
        lsf_stream_classdir_unknown_locked(); result = NULL;
    }
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

static int lsf_stream_classdir_member_locked(struct lsf_stream_rx_state *state,
    struct lsf_stream_classdir_registration_source source, const void *address, unsigned int kind,
    struct lsf_stream_classdir_registration_source *member)
{
    int found = lsf_stream_classdir_lookup_locked(address, kind, member);
    return found == 1 && member->class_slot == source.class_slot &&
        member->class_generation == source.class_generation &&
        lsf_stream_classdir_source_record_locked(state, *member, LSF_PREPAID_PUBLISHED);
}

/* Real __kernfs_new_node failure free site, AFTER its original idr_remove if
 * an ID was inserted. It has not acquired native parent/tree/active references. */
int lsf_factory_stream_classdir_abort_node(struct lsf_stream_classdir_registration_source source,
    struct kernfs_node *kn, const char *name)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *class;
    struct lsf_stream_classdir_registration_source node, named;
    unsigned long flags;
    int result = -EOPNOTSUPP;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    class = lsf_stream_classdir_source_record_locked(state, source, LSF_PREPAID_PUBLISHED);
    if (source.kind != LSF_DEVICE_NETDEV_CLASSDIR || !class ||
        class->security_cache_identity != LSF_STREAM_CLASSDIR_INITIALIZED || class->security_cache_location ||
        !lsf_stream_classdir_member_locked(state, source, kn, LSF_STREAM_CLASSDIR_NODE, &node) ||
        !lsf_stream_classdir_member_locked(state, source, name, LSF_STREAM_CLASSDIR_NAME, &named)) goto poison;
    if (kn->parent || kn->priv || kn->iattr || (kn->name && kn->name != name) ||
        (kn->flags & KERNFS_ACTIVATED) || atomic_read(&kn->count) < 0 ||
        atomic_read(&kn->count) > 1) goto poison;
    kn->name = NULL;
    if (!lsf_device_queue(&factory.pool, state->owner,
            (struct lsf_prepaid_ticket){node.slot, node.generation}, LSF_STREAM_CLASSDIR_NODE) ||
        !lsf_device_finish(&factory.pool, state->owner,
            (struct lsf_prepaid_ticket){node.slot, node.generation}, LSF_STREAM_CLASSDIR_NODE)) goto poison;
    result = 1; goto out;
poison:
    lsf_stream_classdir_unknown_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_classdir_abort_name(struct lsf_stream_classdir_registration_source source,
    const void *address)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *class;
    struct lsf_stream_classdir_registration_source named;
    unsigned long flags;
    unsigned int i;
    int result = -EOPNOTSUPP;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    class = lsf_stream_classdir_source_record_locked(state, source, LSF_PREPAID_PUBLISHED);
    if (source.kind != LSF_DEVICE_NETDEV_CLASSDIR || !class ||
        class->security_cache_identity != LSF_STREAM_CLASSDIR_INITIALIZED || class->security_cache_location ||
        !lsf_stream_classdir_member_locked(state, source, address, LSF_STREAM_CLASSDIR_NAME, &named)) goto poison;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        struct lsf_prepaid_view *r = &factory.pool.records[i];
        if (r->owner == state->owner.slot && r->owner_generation == state->owner.generation &&
            r->kind == LSF_STREAM_CLASSDIR_NODE && r->cache_bucket == source.class_slot &&
            r->cache_anchor == source.class_generation && r->phase != LSF_PREPAID_RETURNED) goto poison;
    }
    if (!lsf_device_queue(&factory.pool, state->owner,
            (struct lsf_prepaid_ticket){named.slot, named.generation}, LSF_STREAM_CLASSDIR_NAME) ||
        !lsf_device_finish(&factory.pool, state->owner,
            (struct lsf_prepaid_ticket){named.slot, named.generation}, LSF_STREAM_CLASSDIR_NAME)) goto poison;
    result = 1; goto out;
poison:
    lsf_stream_classdir_unknown_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_classdir_return_begin(const void *address, unsigned int kind,
    struct lsf_stream_classdir_registration_source *copy)
{
    struct lsf_stream_rx_state *state;
    unsigned long flags;
    int result;
    if (!copy || (kind != LSF_STREAM_CLASSDIR_NODE && kind != LSF_STREAM_CLASSDIR_IDR)) return -EINVAL;
    if (!lsf_factory_selected_consumer()) return 0;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_stream_classdir_lookup_locked(address, kind, copy);
    if (result == 1) {
        state = lsf_stream_rx_current_locked();
        if (!lsf_stream_classdir_source_record_locked(state, *copy, LSF_PREPAID_PUBLISHED) ||
            !lsf_device_queue(&factory.pool, state->owner,
                (struct lsf_prepaid_ticket){copy->slot, copy->generation}, kind)) {
            lsf_stream_classdir_unknown_locked(); result = -EOPNOTSUPP;
        }
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_classdir_release_name(struct lsf_stream_classdir_registration_source source,
    const void *address)
{
    struct lsf_stream_rx_state *state;
    struct lsf_stream_classdir_registration_source named;
    struct kernfs_node *kn;
    unsigned long flags;
    int result = -EOPNOTSUPP;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    if (source.kind != LSF_STREAM_CLASSDIR_NODE ||
        !lsf_stream_classdir_source_record_locked(state, source, LSF_PREPAID_QUEUED) ||
        !lsf_stream_classdir_member_locked(state, source, address, LSF_STREAM_CLASSDIR_NAME, &named)) goto poison;
    kn = (struct kernfs_node *)source.address;
    if (kn->name != address || kn->iattr) goto poison;
    kn->name = NULL;
    if (!lsf_device_queue(&factory.pool, state->owner,
            (struct lsf_prepaid_ticket){named.slot, named.generation}, LSF_STREAM_CLASSDIR_NAME) ||
        !lsf_device_finish(&factory.pool, state->owner,
            (struct lsf_prepaid_ticket){named.slot, named.generation}, LSF_STREAM_CLASSDIR_NAME)) goto poison;
    result = 1; goto out;
poison:
    lsf_stream_classdir_unknown_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_classdir_return_finish(struct lsf_stream_classdir_registration_source source)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_ticket parent = {source.class_slot, source.class_generation};
    unsigned long flags;
    int result = -EOPNOTSUPP;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    if ((source.kind != LSF_STREAM_CLASSDIR_NODE && source.kind != LSF_STREAM_CLASSDIR_IDR) ||
        !lsf_stream_classdir_source_record_locked(state, source, LSF_PREPAID_QUEUED)) goto poison;
    if (source.kind == LSF_STREAM_CLASSDIR_NODE &&
        (((struct kernfs_node *)source.address)->name || ((struct kernfs_node *)source.address)->iattr)) goto poison;
    if (!lsf_device_finish(&factory.pool, state->owner,
            (struct lsf_prepaid_ticket){source.slot, source.generation}, source.kind) ||
        lsf_stream_classdir_try_finish_locked(state, parent) < 0) goto poison;
    lsf_factory_stream_root_notify_locked(&factory.pool);
    result = 1; goto out;
poison:
    lsf_stream_classdir_unknown_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_classdir_iattrs(const struct kernfs_node *kn, int alloc)
{
    struct lsf_stream_classdir_registration_source source;
    struct lsf_stream_rx_state *state;
    unsigned long flags;
    int result;
    if (!lsf_factory_selected_consumer()) return 0;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_stream_classdir_lookup_locked(kn, LSF_STREAM_CLASSDIR_NODE, &source);
    if (result == 1) {
        state = lsf_stream_rx_current_locked();
        if (!lsf_stream_classdir_source_record_locked(state, source, LSF_PREPAID_PUBLISHED) || kn->iattr) {
            lsf_stream_classdir_unknown_locked(); result = -EOPNOTSUPP;
        } else if (alloc) result = -EOPNOTSUPP; /* Existing inherited-attrs cut, never a no-op success. */
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
