/* SPDX-License-Identifier: GPL-2.0-only */
/* Unselected NETDEV own-directory birth/RCU return. Original arena, original
 * real parent references; later platform notification/files remain refused. */
#include <net/lsf_stream_netdev_directory_private.h>

static_assert((unsigned int)LSF_STREAM_NETDEV_DIRECTORY_NODE == (unsigned int)LSF_DEVICE_STREAM_NETDEV_DIRECTORY_NODE);
static_assert((unsigned int)LSF_STREAM_NETDEV_DIRECTORY_NAME == (unsigned int)LSF_DEVICE_STREAM_NETDEV_DIRECTORY_NAME);
static_assert((unsigned int)LSF_STREAM_NETDEV_DIRECTORY_IDR == (unsigned int)LSF_DEVICE_STREAM_NETDEV_DIRECTORY_IDR);
static_assert((unsigned long)IFNAMSIZ == (unsigned long)sizeof(((struct net_device *)0)->name));

static void lsf_stream_netdev_directory_unknown_locked(void)
{
    lockdep_assert_held(&pool_lock);
    factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1);
}

void lsf_factory_stream_netdev_directory_retain_unknown(void)
{
    unsigned long flags;
    spin_lock_irqsave(&pool_lock, flags);
    lsf_stream_netdev_directory_unknown_locked();
    spin_unlock_irqrestore(&pool_lock, flags);
}

static int lsf_stream_netdev_directory_registration_shape(unsigned int kind,
    unsigned long *bytes, unsigned long *alignment)
{
    if (kind == LSF_STREAM_NETDEV_DIRECTORY_NODE) {
        *bytes = sizeof(struct kernfs_node); *alignment = __alignof__(struct kernfs_node);
    } else if (kind == LSF_STREAM_NETDEV_DIRECTORY_IDR) {
        *bytes = sizeof(struct radix_tree_node); *alignment = __alignof__(struct radix_tree_node);
    } else if (kind == LSF_STREAM_NETDEV_DIRECTORY_NAME) {
        *bytes = IFNAMSIZ; *alignment = 1u;
    } else return 0;
    return *bytes && *bytes <= ULONG_MAX - 63u && *alignment && *alignment <= 64u &&
        !(*alignment & (*alignment - 1u));
}

/* Discriminate ONLY this namespace before poison-sensitive authorization.
 * A zero result supplies no authority; original namespaces still validate it. */
static struct lsf_prepaid_view *lsf_stream_netdev_directory_raw_locked(const void *address,
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


/* Metadata-only parent validation: no dereference of a dead NETDEV/classdir.
 * The actual positive VIRTIO hold remains in the original NETDEV record until
 * its original completed-tail/child drain, outside pool locks. */
static struct lsf_prepaid_view *lsf_stream_netdev_directory_parent_locked(
    struct lsf_stream_rx_state *state, struct lsf_stream_netdev_directory_source source,
    struct net_device **dev)
{
    struct lsf_prepaid_ticket parent = {source.netdev_slot, source.netdev_generation}, same;
    struct lsf_prepaid_view *r, *virtio;
    unsigned long base;
    lockdep_assert_held(&pool_lock);
    if (!state || !factory.pages) return NULL;
    r = lsf_device_record(&factory.pool, state->owner, parent, LSF_DEVICE_NETDEV);
    if (!r || r->security_cache_location != 1u) return NULL;
    base = (unsigned long)page_address(factory.pages);
    *dev = (void *)(base + r->offset);
    if (lsf_stream_netdev_record_locked(state, *dev, &same) != r ||
        same.slot != parent.slot || same.generation != parent.generation) return NULL;
    virtio = lsf_device_record(&factory.pool, state->owner,
        (struct lsf_prepaid_ticket){r->cache_bucket, r->cache_anchor}, LSF_DEVICE_VIRTIO);
    if (!virtio || virtio->bytes < sizeof(struct virtio_device) ||
        state->virtio != (void *)(base + virtio->offset)) return NULL;
    if (r->deferred == LSF_PREPAID_PUBLISHED) {
        if (r->security_cache_identity != LSF_STREAM_NETDEV_CORE &&
            r->security_cache_identity != (LSF_STREAM_NETDEV_CORE | LSF_STREAM_NETDEV_TAIL_ACTIVE))
            return NULL;
    } else if (r->deferred == LSF_PREPAID_QUEUED) {
        if (r->security_cache_identity != (LSF_STREAM_NETDEV_CORE | LSF_STREAM_NETDEV_RELEASE |
                LSF_STREAM_NETDEV_TAIL_ACTIVE) &&
            r->security_cache_identity != (LSF_STREAM_NETDEV_CORE | LSF_STREAM_NETDEV_RELEASE |
                LSF_STREAM_NETDEV_TAIL_DONE)) return NULL;
    } else return NULL;
    return r;
}

static struct lsf_prepaid_view *lsf_stream_netdev_directory_source_record_locked(
    struct lsf_stream_rx_state *state, struct lsf_stream_netdev_directory_source source,
    unsigned int deferred)
{
    struct lsf_prepaid_ticket ticket = {source.slot, source.generation};
    struct lsf_prepaid_view *r, *parent;
    struct net_device *dev;
    unsigned long bytes, alignment, base;
    lockdep_assert_held(&pool_lock);
    parent = lsf_stream_netdev_directory_parent_locked(state, source, &dev);
    if (!parent) return NULL;
    base = (unsigned long)page_address(factory.pages);
    if (source.kind == LSF_DEVICE_NETDEV) {
        if (source.slot != source.netdev_slot || source.generation != source.netdev_generation ||
            source.address != &dev->dev.kobj) return NULL; /* Address arithmetic only. */
        r = parent;
    } else {
        if (!lsf_stream_netdev_directory_registration_shape(source.kind, &bytes, &alignment)) return NULL;
        r = lsf_device_record(&factory.pool, state->owner, ticket, source.kind);
        if (!r || r->cache_bucket != source.netdev_slot || r->cache_anchor != source.netdev_generation ||
            r->bytes != ((bytes + 63u) & ~63ull) || r->offset % alignment ||
            source.address != (void *)(base + r->offset)) return NULL;
    }
    if (deferred && r->deferred != deferred) return NULL;
    return r;
}

static void lsf_stream_netdev_directory_copy(const void *address, struct lsf_prepaid_ticket ticket,
    unsigned int kind, struct lsf_prepaid_view *r,
    struct lsf_stream_netdev_directory_source *copy)
{
    *copy = (struct lsf_stream_netdev_directory_source){
        .address = address, .slot = ticket.slot, .generation = ticket.generation, .kind = kind,
        .netdev_slot = kind == LSF_DEVICE_NETDEV ? ticket.slot : r->cache_bucket,
        .netdev_generation = kind == LSF_DEVICE_NETDEV ? ticket.generation : r->cache_anchor,
    };
}


/* Constructor-only native reads. Original kobject_add holds its real classdir
 * parent reference; cleanup_glue_dir cannot delete sd while that ref exists.
 * These native parent reads are NEVER used by the late return path above. */
static int lsf_stream_netdev_directory_constructor_locked(
    struct lsf_stream_rx_state *state, struct lsf_stream_netdev_directory_source source,
    struct net_device **dev)
{
    struct lsf_prepaid_view *r, *classdir, *metadata;
    struct lsf_prepaid_ticket class_ticket, same_netdev, private_ticket;
    struct lsf_prepaid_ticket parent = {source.netdev_slot, source.netdev_generation};
    struct lsf_stream_classdir_registration_source node;
    struct kobject *kobj;
    unsigned long bytes, alignment, base;
    lockdep_assert_held(&pool_lock);
    r = lsf_stream_netdev_directory_parent_locked(state, source, dev);
    if (!r || r->deferred != LSF_PREPAID_PUBLISHED ||
        r->security_cache_identity != LSF_STREAM_NETDEV_CORE ||
        !lsf_stream_constructor_current_locked(state) ||
        !lsf_stream_netdev_core_shape(&bytes, &alignment)) return 0;
    metadata = lsf_stream_netdev_core_child_locked(state, parent, &private_ticket);
    if (!metadata || factory.pool.poisoned || READ_ONCE(factory.uncertain) ||
        lsf_device_record(&factory.pool, state->owner, private_ticket, LSF_DEVICE_NETDEV_CORE) != metadata ||
        metadata->deferred != LSF_PREPAID_PUBLISHED || metadata->offset % alignment ||
        metadata->bytes != ((bytes + 63u) & ~63ull)) return 0;
    base = (unsigned long)page_address(factory.pages);
    if ((*dev)->dev.p != (void *)(base + metadata->offset) ||
        (*dev)->dev.platform_data != *dev) return 0;
    kobj = &(*dev)->dev.kobj;
    if (!kobj->state_initialized || kobj->state_add_uevent_sent ||
        kobj->state_remove_uevent_sent || !kobj->parent ||
        !lsf_prepaid_stream_netdev_directory_type(kobj)) return 0;
    classdir = lsf_stream_classdir_record_locked(state, kobj->parent, &class_ticket, &same_netdev);
    if (!classdir || same_netdev.slot != source.netdev_slot ||
        same_netdev.generation != source.netdev_generation ||
        classdir->deferred != LSF_PREPAID_PUBLISHED ||
        classdir->security_cache_identity != LSF_STREAM_CLASSDIR_INITIALIZED ||
        classdir->security_cache_location ||
        !lsf_prepaid_stream_netdev_classdir_initialized(kobj->parent) || !kobj->parent->sd ||
        lsf_stream_classdir_lookup_locked(kobj->parent->sd, LSF_STREAM_CLASSDIR_NODE, &node) != 1 ||
        node.class_slot != class_ticket.slot || node.class_generation != class_ticket.generation ||
        !lsf_stream_classdir_registration_current_locked(state, node)) return 0;
    return 1;
}

static int lsf_stream_netdev_directory_registration_current_locked(struct lsf_stream_rx_state *state,
    struct lsf_stream_netdev_directory_source source)
{
    struct net_device *dev;
    lockdep_assert_held(&pool_lock);
    return (source.kind == LSF_DEVICE_NETDEV || source.kind == LSF_STREAM_NETDEV_DIRECTORY_NODE) &&
        lsf_stream_netdev_directory_source_record_locked(state, source, LSF_PREPAID_PUBLISHED) &&
        lsf_stream_netdev_directory_constructor_locked(state, source, &dev) &&
        !dev->dev.kobj.state_in_sysfs && !dev->dev.kobj.sd;
}


static int lsf_stream_netdev_directory_lookup_locked(const void *, unsigned int,
    struct lsf_stream_netdev_directory_source *);

static int lsf_stream_netdev_directory_named_locked(struct lsf_stream_rx_state *state,
    struct lsf_prepaid_ticket parent, struct net_device *dev, const char *name)
{
    struct lsf_prepaid_view *r;
    struct lsf_prepaid_ticket ticket;
    unsigned long base;
    unsigned int i;
    size_t length;
    lockdep_assert_held(&pool_lock);
    if (!lsf_stream_rx_address_locked(name)) return 0;
    base = (unsigned long)page_address(factory.pages);
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        r = &factory.pool.records[i];
        if (r->offset != (unsigned long)name - base) continue;
        ticket = (struct lsf_prepaid_ticket){i, r->generation};
        if (!lsf_device_record(&factory.pool, state->owner, ticket, LSF_DEVICE_NETDEV_CORE_NAME) ||
            r->bytes != ((IFNAMSIZ + 63u) & ~63ull) || r->deferred != LSF_PREPAID_PUBLISHED ||
            r->cache_bucket != parent.slot || r->cache_anchor != parent.generation) return 0;
        length = strnlen(name, IFNAMSIZ);
        return length && length < IFNAMSIZ && !memchr(name, '/', length) &&
            dev->dev.kobj.name == name && !memcmp(name, dev->name, length + 1);
    }
    return 0;
}

int lsf_factory_stream_netdev_directory_kobject(const struct kobject *kobj,
    struct lsf_stream_netdev_directory_source *copy)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_ticket ticket;
    struct lsf_prepaid_view *r;
    struct net_device *dev;
    unsigned long flags;
    int kind, result = -EOPNOTSUPP;
    if (!copy) return -EINVAL;
    if (!lsf_factory_selected_consumer()) return 0;
    kind = lsf_factory_stream_netdev_core_classify(kobj, 1);
    if (kind <= 0) return kind; /* Other typed/outside namespaces retain original dispatch. */
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    r = lsf_stream_netdev_core_parent_locked(state, kobj, 1, &ticket, &dev);
    if (!r) goto poison;
    lsf_stream_netdev_directory_copy(kobj, ticket, LSF_DEVICE_NETDEV, r, copy);
    if (!lsf_stream_netdev_directory_registration_current_locked(state, *copy) ||
        !lsf_stream_netdev_directory_named_locked(state, ticket, dev, kobj->name)) goto poison;
    result = 1; goto out;
poison:
    lsf_stream_netdev_directory_unknown_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Called only after real kobject_add succeeds, BEFORE platform notification.
 * Positive means a deliberately unsupported next boundary, with safe original
 * directory unwind. Negative retains original native refs; never clean unknown.
 * No notifier or ADD event has run, so no paired REMOVE action is fabricated. */
int lsf_factory_stream_netdev_directory_added(const struct device *device)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_ticket ticket;
    struct lsf_stream_netdev_directory_source source, node;
    struct lsf_prepaid_view *r;
    struct net_device *dev;
    const struct kobject *kobj;
    unsigned long flags;
    int kind, result = -EOPNOTSUPP;
    if (!lsf_factory_selected_consumer()) return 0;
    kind = lsf_factory_stream_netdev_core_classify(device, 0);
    if (kind <= 0) return kind;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    r = lsf_stream_netdev_core_parent_locked(state, device, 0, &ticket, &dev);
    if (!r) goto poison;
    kobj = &dev->dev.kobj;
    lsf_stream_netdev_directory_copy(kobj, ticket, LSF_DEVICE_NETDEV, r, &source);
    if (!lsf_stream_netdev_directory_constructor_locked(state, source, &dev) ||
        !kobj->state_in_sysfs || !kobj->sd ||
        !lsf_stream_netdev_directory_named_locked(state, ticket, dev, kobj->name) ||
        lsf_stream_netdev_directory_lookup_locked(kobj->sd, LSF_STREAM_NETDEV_DIRECTORY_NODE, &node) != 1 ||
        node.netdev_slot != ticket.slot || node.netdev_generation != ticket.generation ||
        !lsf_stream_netdev_directory_source_record_locked(state, node, LSF_PREPAID_PUBLISHED) ||
        kobj->sd->priv != kobj || kobj->sd->parent != kobj->parent->sd ||
        kobj->sd->iattr || !S_ISDIR(kobj->sd->mode)) goto poison;
    result = 1; goto out;
poison:
    lsf_stream_netdev_directory_unknown_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

static int lsf_stream_netdev_directory_lookup_locked(const void *address, unsigned int kind,
    struct lsf_stream_netdev_directory_source *copy)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_ticket ticket;
    struct lsf_prepaid_view *r;
    lockdep_assert_held(&pool_lock);
    r = lsf_stream_netdev_directory_raw_locked(address, kind, &ticket);
    if (!r) return 0;
    state = lsf_stream_rx_current_locked();
    lsf_stream_netdev_directory_copy(address, ticket, kind, r, copy);
    if (!lsf_stream_netdev_directory_source_record_locked(state, *copy, 0) ||
        (r->deferred != LSF_PREPAID_PUBLISHED && r->deferred != LSF_PREPAID_QUEUED)) {
        lsf_stream_netdev_directory_unknown_locked(); return -EOPNOTSUPP;
    }
    return 1;
}

int lsf_factory_stream_netdev_directory_node(const void *address,
    struct lsf_stream_netdev_directory_source *copy)
{
    unsigned long flags;
    int result;
    if (!copy) return -EINVAL;
    if (!lsf_factory_selected_consumer()) return 0;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_stream_netdev_directory_lookup_locked(address, LSF_STREAM_NETDEV_DIRECTORY_NODE, copy);
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_netdev_directory_current(struct lsf_stream_netdev_directory_source source)
{
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_stream_netdev_directory_registration_current_locked(lsf_stream_rx_current_locked(), source);
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void *lsf_factory_stream_netdev_directory_allocate(struct lsf_stream_netdev_directory_source source,
    unsigned long bytes, unsigned int kind)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_ticket ticket, parent = {source.netdev_slot, source.netdev_generation};
    unsigned long flags, expected, alignment;
    u64 offset;
    void *result = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    if (!lsf_stream_netdev_directory_registration_shape(kind, &expected, &alignment) || bytes != expected ||
        !lsf_stream_netdev_directory_registration_current_locked(state, source) ||
        (kind != LSF_STREAM_NETDEV_DIRECTORY_NODE && kind != LSF_STREAM_NETDEV_DIRECTORY_IDR) ||
        (kind == LSF_STREAM_NETDEV_DIRECTORY_NODE && source.kind != LSF_DEVICE_NETDEV) ||
        (kind == LSF_STREAM_NETDEV_DIRECTORY_IDR && source.kind != LSF_STREAM_NETDEV_DIRECTORY_NODE)) goto out;
    if (lsf_stream_constructor_allocate_locked(state, kind, parent, bytes, alignment,
            &ticket, &offset) != 1) goto out;
    result = (char *)page_address(factory.pages) + offset;
    memset(result, 0, bytes);
    if (!lsf_device_publish(&factory.pool, state->owner, ticket, kind)) {
        lsf_stream_netdev_directory_unknown_locked(); result = NULL;
    }
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}


char *lsf_factory_stream_netdev_directory_name(struct lsf_stream_netdev_directory_source source,
    const char *name)
{
    struct lsf_stream_rx_state *state;
    struct net_device *dev;
    struct lsf_prepaid_ticket ticket, parent = {source.netdev_slot, source.netdev_generation};
    unsigned long flags;
    unsigned int i;
    size_t length;
    u64 offset;
    char *result = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    if (source.kind != LSF_DEVICE_NETDEV ||
        !lsf_stream_netdev_directory_source_record_locked(state, source, LSF_PREPAID_PUBLISHED) ||
        !lsf_stream_netdev_directory_registration_current_locked(state, source) ||
        !lsf_stream_netdev_directory_constructor_locked(state, source, &dev) ||
        !lsf_stream_netdev_directory_named_locked(state, parent, dev, name)) goto out;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        const struct lsf_prepaid_view *r = &factory.pool.records[i];
        if (r->owner == state->owner.slot && r->owner_generation == state->owner.generation &&
            r->cache_bucket == parent.slot && r->cache_anchor == parent.generation &&
            r->kind == LSF_STREAM_NETDEV_DIRECTORY_NAME && r->phase != LSF_PREPAID_EMPTY) goto out;
    }
    length = strnlen(name, IFNAMSIZ);
    if (!length || length == IFNAMSIZ) goto out;
    if (lsf_stream_constructor_allocate_locked(state, LSF_STREAM_NETDEV_DIRECTORY_NAME, parent,
            IFNAMSIZ, __alignof__(dev->name), &ticket, &offset) != 1) goto out;
    result = (char *)page_address(factory.pages) + offset;
    memset(result, 0, IFNAMSIZ); memcpy(result, name, length + 1);
    if (!lsf_device_publish(&factory.pool, state->owner, ticket, LSF_STREAM_NETDEV_DIRECTORY_NAME)) {
        lsf_stream_netdev_directory_unknown_locked(); result = NULL;
    }
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

static int lsf_stream_netdev_directory_member_locked(struct lsf_stream_rx_state *state,
    struct lsf_stream_netdev_directory_source source, const void *address, unsigned int kind,
    struct lsf_stream_netdev_directory_source *member)
{
    int found = lsf_stream_netdev_directory_lookup_locked(address, kind, member);
    return found == 1 && member->netdev_slot == source.netdev_slot &&
        member->netdev_generation == source.netdev_generation &&
        lsf_stream_netdev_directory_source_record_locked(state, *member, LSF_PREPAID_PUBLISHED);
}

/* Real __kernfs_new_node failure free site, AFTER its original idr_remove if
 * an ID was inserted. It has not acquired native parent/tree/active references. */
int lsf_factory_stream_netdev_directory_abort_node(struct lsf_stream_netdev_directory_source source,
    struct kernfs_node *kn, const char *name)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *parent_record;
    struct lsf_stream_netdev_directory_source node, named;
    unsigned long flags;
    int result = -EOPNOTSUPP;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    parent_record = lsf_stream_netdev_directory_source_record_locked(state, source, LSF_PREPAID_PUBLISHED);
    if (source.kind != LSF_DEVICE_NETDEV || !parent_record ||
        parent_record->security_cache_identity != LSF_STREAM_NETDEV_CORE || parent_record->security_cache_location != 1u ||
        !lsf_stream_netdev_directory_member_locked(state, source, kn, LSF_STREAM_NETDEV_DIRECTORY_NODE, &node) ||
        !lsf_stream_netdev_directory_member_locked(state, source, name, LSF_STREAM_NETDEV_DIRECTORY_NAME, &named)) goto poison;
    if (kn->parent || kn->priv || kn->iattr || (kn->name && kn->name != name) ||
        (kn->flags & KERNFS_ACTIVATED) || atomic_read(&kn->count) < 0 ||
        atomic_read(&kn->count) > 1) goto poison;
    kn->name = NULL;
    if (!lsf_device_queue(&factory.pool, state->owner,
            (struct lsf_prepaid_ticket){node.slot, node.generation}, LSF_STREAM_NETDEV_DIRECTORY_NODE) ||
        !lsf_device_finish(&factory.pool, state->owner,
            (struct lsf_prepaid_ticket){node.slot, node.generation}, LSF_STREAM_NETDEV_DIRECTORY_NODE)) goto poison;
    result = 1; goto out;
poison:
    lsf_stream_netdev_directory_unknown_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_netdev_directory_abort_name(struct lsf_stream_netdev_directory_source source,
    const void *address)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *parent_record;
    struct lsf_stream_netdev_directory_source named;
    unsigned long flags;
    unsigned int i;
    int result = -EOPNOTSUPP;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    parent_record = lsf_stream_netdev_directory_source_record_locked(state, source, LSF_PREPAID_PUBLISHED);
    if (source.kind != LSF_DEVICE_NETDEV || !parent_record ||
        parent_record->security_cache_identity != LSF_STREAM_NETDEV_CORE || parent_record->security_cache_location != 1u ||
        !lsf_stream_netdev_directory_member_locked(state, source, address, LSF_STREAM_NETDEV_DIRECTORY_NAME, &named)) goto poison;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        struct lsf_prepaid_view *r = &factory.pool.records[i];
        if (r->owner == state->owner.slot && r->owner_generation == state->owner.generation &&
            r->kind == LSF_STREAM_NETDEV_DIRECTORY_NODE && r->cache_bucket == source.netdev_slot &&
            r->cache_anchor == source.netdev_generation && r->phase != LSF_PREPAID_RETURNED) goto poison;
    }
    if (!lsf_device_queue(&factory.pool, state->owner,
            (struct lsf_prepaid_ticket){named.slot, named.generation}, LSF_STREAM_NETDEV_DIRECTORY_NAME) ||
        !lsf_device_finish(&factory.pool, state->owner,
            (struct lsf_prepaid_ticket){named.slot, named.generation}, LSF_STREAM_NETDEV_DIRECTORY_NAME)) goto poison;
    result = 1; goto out;
poison:
    lsf_stream_netdev_directory_unknown_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_netdev_directory_return_begin(const void *address, unsigned int kind,
    struct lsf_stream_netdev_directory_source *copy)
{
    struct lsf_stream_rx_state *state;
    unsigned long flags;
    int result;
    if (!copy || (kind != LSF_STREAM_NETDEV_DIRECTORY_NODE && kind != LSF_STREAM_NETDEV_DIRECTORY_IDR)) return -EINVAL;
    if (!lsf_factory_selected_consumer()) return 0;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_stream_netdev_directory_lookup_locked(address, kind, copy);
    if (result == 1) {
        state = lsf_stream_rx_current_locked();
        if (!lsf_stream_netdev_directory_source_record_locked(state, *copy, LSF_PREPAID_PUBLISHED) ||
            !lsf_device_queue(&factory.pool, state->owner,
                (struct lsf_prepaid_ticket){copy->slot, copy->generation}, kind)) {
            lsf_stream_netdev_directory_unknown_locked(); result = -EOPNOTSUPP;
        }
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_netdev_directory_release_name(struct lsf_stream_netdev_directory_source source,
    const void *address)
{
    struct lsf_stream_rx_state *state;
    struct lsf_stream_netdev_directory_source named;
    struct kernfs_node *kn;
    unsigned long flags;
    int result = -EOPNOTSUPP;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    if (source.kind != LSF_STREAM_NETDEV_DIRECTORY_NODE ||
        !lsf_stream_netdev_directory_source_record_locked(state, source, LSF_PREPAID_QUEUED) ||
        !lsf_stream_netdev_directory_member_locked(state, source, address, LSF_STREAM_NETDEV_DIRECTORY_NAME, &named)) goto poison;
    kn = (struct kernfs_node *)source.address;
    if (kn->name != address || kn->iattr) goto poison;
    kn->name = NULL;
    if (!lsf_device_queue(&factory.pool, state->owner,
            (struct lsf_prepaid_ticket){named.slot, named.generation}, LSF_STREAM_NETDEV_DIRECTORY_NAME) ||
        !lsf_device_finish(&factory.pool, state->owner,
            (struct lsf_prepaid_ticket){named.slot, named.generation}, LSF_STREAM_NETDEV_DIRECTORY_NAME)) goto poison;
    result = 1; goto out;
poison:
    lsf_stream_netdev_directory_unknown_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_netdev_directory_return_finish(struct lsf_stream_netdev_directory_source source)
{
    struct lsf_stream_rx_state *state;
    unsigned long flags;
    int result = -EOPNOTSUPP;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    if ((source.kind != LSF_STREAM_NETDEV_DIRECTORY_NODE && source.kind != LSF_STREAM_NETDEV_DIRECTORY_IDR) ||
        !lsf_stream_netdev_directory_source_record_locked(state, source, LSF_PREPAID_QUEUED)) goto poison;
    if (source.kind == LSF_STREAM_NETDEV_DIRECTORY_NODE &&
        (((struct kernfs_node *)source.address)->name || ((struct kernfs_node *)source.address)->iattr)) goto poison;
    if (!lsf_device_finish(&factory.pool, state->owner,
            (struct lsf_prepaid_ticket){source.slot, source.generation}, source.kind)) goto poison;
    lsf_factory_stream_root_notify_locked(&factory.pool);
    result = 1; goto out;
poison:
    lsf_stream_netdev_directory_unknown_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_netdev_directory_iattrs(const struct kernfs_node *kn, int alloc)
{
    struct lsf_stream_netdev_directory_source source;
    struct lsf_stream_rx_state *state;
    unsigned long flags;
    int result;
    if (!lsf_factory_selected_consumer()) return 0;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_stream_netdev_directory_lookup_locked(kn, LSF_STREAM_NETDEV_DIRECTORY_NODE, &source);
    if (result == 1) {
        state = lsf_stream_rx_current_locked();
        if (!lsf_stream_netdev_directory_source_record_locked(state, source, LSF_PREPAID_PUBLISHED) || kn->iattr) {
            lsf_stream_netdev_directory_unknown_locked(); result = -EOPNOTSUPP;
        } else if (alloc) result = -EOPNOTSUPP; /* Existing inherited-attrs cut, never a no-op success. */
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
