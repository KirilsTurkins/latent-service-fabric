/* SPDX-License-Identifier: GPL-2.0-only */
/* WIP grouped registration consumer, included after the real core helpers.
 * Uses only the original owner/key/records/infrastructure extent. There is no
 * per-task allocator override, external factory registration or second ledger. */

static_assert(LSF_DEVICE_KERNFS_NODE == LSF_REGISTRATION_KIND_NODE);
static_assert(LSF_DEVICE_KERNFS_NAME == LSF_REGISTRATION_KIND_NAME);
static_assert(LSF_DEVICE_IDR_NODE == LSF_REGISTRATION_KIND_IDR_NODE);

/* Called in the original pci_leave BEFORE mutex_unlock. The deferred-cleanup
 * active fence remains until its original post-unlock leave, but it no longer
 * lends allocation/mutation authority. The pointer is compared, never derefed. */
int lsf_factory_device_registration_constructor_revoke(void)
{
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (factory.device && factory.device->constructor_active &&
        factory.device->constructor_task == current) {
        factory.device->constructor_task = NULL;
        result = 1;
    } else {
        lsf_factory_device_firmware_poison();
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

static int lsf_device_registration_kind(unsigned int kind)
{
    return kind == LSF_DEVICE_KERNFS_NODE || kind == LSF_DEVICE_KERNFS_NAME ||
        kind == LSF_DEVICE_IDR_NODE;
}

/* SAME pool_lock serializes every child birth/publication and the original
 * schedule's no-child -> queued transition. Include every actual live direct
 * PCI child, not only currently known registration kinds. Nested descendants
 * retain their own live parent through lsf_device_finish's existing check.
 * The one firmware descriptor itself is deliberately excluded; it is the
 * continuation whose dispatch is being gated, not evidence of quiescence. */
static int lsf_factory_device_registration_pending_locked(void)
{
    struct lsf_factory_device_firmware *owned;
    struct lsf_prepaid_ticket pci;
    unsigned int i;
    if (!factory.device || !(owned = lsf_factory_device_firmware_locked()) ||
        lsf_factory_device_firmware_pci(owned->pci_address, &pci) != 1 ||
        !lsf_factory_device_firmware_for_pci(owned->pci_address, pci))
        return 1;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        const struct lsf_prepaid_view *record = &factory.pool.records[i];
        if (i != factory.device->firmware.slot && record->phase == LSF_PREPAID_LIVE &&
            record->owner == factory.device->key.slot &&
            record->owner_generation == factory.device->key.generation &&
            record->cache_bucket == pci.slot && record->cache_anchor == pci.generation)
            return 1;
    }
    return 0;
}

/* Caller holds pool_lock. All registration births retain the original whole
 * PCI object, even when an IDR tree node outlives its original kernfs entry.
 * An individual entry's idr_remove cannot transfer or discharge that owner. */
static struct lsf_factory_device_firmware *
lsf_factory_device_registration_parent_locked(
    struct lsf_device_registration_source source)
{
    struct lsf_prepaid_ticket pci = {source.pci_slot, source.pci_generation};
    struct lsf_prepaid_view *record;
    const void *address;
    if (!factory.pages || !factory.device)
        return NULL;
    record = lsf_device_record(&factory.pool, factory.device->key, pci, LSF_DEVICE_PCI);
    if (!record || record->bytes < sizeof(struct pci_dev) ||
        record->deferred != LSF_PREPAID_PUBLISHED ||
        record->cache_bucket != factory.device->root.slot ||
        record->cache_anchor != factory.device->root.generation)
        return NULL;
    address = (char *)page_address(factory.pages) + record->offset;
    return lsf_factory_device_firmware_for_pci(address, pci);
}

/* Caller holds pool_lock. Exact address/kind/generation precede all object
 * dereferences. A returned/incomplete/source-mismatched record is not current. */
static struct lsf_prepaid_view *lsf_factory_device_registration_record_locked(
    struct lsf_device_registration_source source, unsigned int deferred)
{
    struct lsf_prepaid_ticket ticket = {source.slot, source.generation};
    struct lsf_prepaid_view *record;
    if (!factory.pages || !factory.device ||
        (source.kind != LSF_DEVICE_PCI && !lsf_device_registration_kind(source.kind)))
        return NULL;
    record = lsf_device_record(&factory.pool, factory.device->key, ticket, source.kind);
    if (!record || record->deferred != deferred ||
        (char *)page_address(factory.pages) + record->offset != source.address)
        return NULL;
    if ((source.kind == LSF_DEVICE_PCI && record->bytes < sizeof(struct pci_dev)) ||
        (source.kind == LSF_DEVICE_KERNFS_NODE && record->bytes < sizeof(struct kernfs_node)) ||
        (source.kind == LSF_DEVICE_IDR_NODE && record->bytes < sizeof(struct radix_tree_node)))
        return NULL;
    if (source.kind == LSF_DEVICE_PCI) {
        if (source.slot != source.pci_slot || source.generation != source.pci_generation)
            return NULL;
    } else if (record->cache_bucket != source.pci_slot ||
        record->cache_anchor != source.pci_generation) {
        return NULL;
    }
    if (!lsf_factory_device_registration_parent_locked(source))
        return NULL;
    return record;
}

int lsf_factory_device_registration_kobject(const void *kobject,
    struct lsf_device_registration_source *copy)
{
    struct lsf_prepaid_ticket pci;
    const void *address;
    unsigned long flags;
    int result;
    if (!copy)
        return -1;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_factory_device_core_parent(kobject,
        offsetof(struct pci_dev, dev) + offsetof(struct device, kobj), &pci, &address);
    if (result == 1) {
        *copy = (struct lsf_device_registration_source){
            .address = address, .kind = LSF_DEVICE_PCI,
            .slot = pci.slot, .generation = pci.generation,
            .pci_slot = pci.slot, .pci_generation = pci.generation,
        };
        if (!lsf_factory_device_registration_record_locked(*copy, LSF_PREPAID_PUBLISHED))
            result = -1;
    }
    if (result < 0)
        lsf_factory_device_firmware_poison();
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Caller holds pool_lock. The actual node/header pointer locates a prior
 * original birth. It never supplies a new source merely by matching an arena. */
static int lsf_factory_device_registration_lookup_locked(const void *address,
    unsigned int kind, struct lsf_device_registration_source *copy)
{
    struct lsf_prepaid_view *record;
    unsigned long base, value = (unsigned long)address;
    unsigned int i;
    if (!factory.pages)
        return 0;
    base = (unsigned long)page_address(factory.pages);
    if (value < base || value - base >= LSF_BACKING_BYTES)
        return 0;
    if (!factory.device || !lsf_device_registration_kind(kind))
        return -1;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->offset != value - base || record->kind != kind)
            continue;
        *copy = (struct lsf_device_registration_source){
            .address = address, .kind = kind, .slot = i,
            .generation = record->generation, .pci_slot = record->cache_bucket,
            .pci_generation = record->cache_anchor,
        };
        return lsf_factory_device_registration_record_locked(*copy,
            LSF_PREPAID_PUBLISHED) ? 1 : -1;
    }
    return -1;
}

int lsf_factory_device_registration_node(const void *node,
    struct lsf_device_registration_source *copy)
{
    unsigned long flags;
    int result;
    if (!copy)
        return -1;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_factory_device_registration_lookup_locked(node, LSF_DEVICE_KERNFS_NODE, copy);
    if (result < 0)
        lsf_factory_device_firmware_poison();
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Caller holds pool_lock. This guard is required even if the IDR can mutate
 * using an existing node without allocating. The process-wide actor tuple and
 * an active boolean alone do not establish this exact mutex-scoped task. */
static int lsf_factory_device_registration_current_locked(
    struct lsf_device_registration_source source)
{
    struct lsf_factory_device_firmware *owned;
    return (source.kind == LSF_DEVICE_PCI || source.kind == LSF_DEVICE_KERNFS_NODE) &&
        lsf_factory_device_registration_record_locked(source, LSF_PREPAID_PUBLISHED) &&
        (owned = lsf_factory_device_registration_parent_locked(source)) &&
        owned->core_initialized && factory.device->constructor_active &&
        factory.device->constructor_task == current && !in_interrupt() &&
        lsf_factory_device_core_actor() && !factory.pool.stopped &&
        !factory.pool.contexts[LSF_DEVICE_OWNER_SLOT].closed &&
        !READ_ONCE(factory.uncertain) && !owned->revoked && !owned->retirement &&
        !owned->queued && !owned->returned && !owned->core_tail_active &&
        !owned->core_tail_complete;
}

int lsf_factory_device_registration_current(struct lsf_device_registration_source source)
{
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_factory_device_registration_current_locked(source);
    if (!result)
        lsf_factory_device_firmware_poison();
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void *lsf_factory_device_registration_allocate(
    struct lsf_device_registration_source source, unsigned long bytes, unsigned int kind)
{
    struct lsf_prepaid_ticket pci = {source.pci_slot, source.pci_generation}, ticket;
    unsigned long flags;
    lsf_u64 offset;
    void *result = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    if (__alignof__(struct kernfs_node) > 64 || __alignof__(struct radix_tree_node) > 64)
        goto out;
    if (!bytes || !lsf_device_registration_kind(kind) ||
        (source.kind != LSF_DEVICE_PCI && source.kind != LSF_DEVICE_KERNFS_NODE) ||
        (kind == LSF_DEVICE_IDR_NODE && source.kind != LSF_DEVICE_KERNFS_NODE) ||
        !lsf_factory_device_registration_current_locked(source))
        goto poison;
    if (!lsf_device_allocate(&factory.pool, factory.device->key, bytes, kind,
            pci, &ticket, &offset))
        goto out;
    result = (char *)page_address(factory.pages) + offset;
    memset(result, 0, bytes);
    if (!lsf_device_publish(&factory.pool, factory.device->key, ticket, kind)) {
        result = NULL;
        goto poison;
    }
    goto out;
poison:
    lsf_factory_device_firmware_poison();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Each real callback enters BEFORE touching the object. The local copy keeps
 * all identities needed after actual cleanup; no freed pointer is dereferenced. */
int lsf_factory_device_registration_return_begin(const void *address, unsigned int kind,
    struct lsf_device_registration_source *copy)
{
    struct lsf_prepaid_ticket ticket;
    unsigned long flags;
    int result;
    if (!copy)
        return -1;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_factory_device_registration_lookup_locked(address, kind, copy);
    if (result == 1) {
        ticket = (struct lsf_prepaid_ticket){copy->slot, copy->generation};
        if (!lsf_device_queue(&factory.pool, factory.device->key, ticket, kind))
            result = -1;
    }
    if (result < 0)
        lsf_factory_device_firmware_poison();
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* The actual callsite must have completed original free/RCU cleanup and hold
 * NO registration/cache/tree/pool lock. Finishing a logical view never frees
 * the bank. Only after releasing pool_lock can the one existing continuation
 * reconsider its original admission fence; no new work item or timer exists. */
int lsf_factory_device_registration_return_finish(struct lsf_device_registration_source source)
{
    struct lsf_prepaid_ticket ticket = {source.slot, source.generation};
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_device_registration_kind(source.kind) ||
        !lsf_factory_device_registration_record_locked(source, LSF_PREPAID_QUEUED) ||
        !lsf_device_finish(&factory.pool, factory.device->key, ticket, source.kind))
        goto poison;
    result = 1;
    goto out;
poison:
    lsf_factory_device_firmware_poison();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    if (result)
        lsf_factory_device_firmware_schedule();
    return result;
}
