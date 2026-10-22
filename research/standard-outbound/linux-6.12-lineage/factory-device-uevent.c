/* SPDX-License-Identifier: GPL-2.0-only */
/* Uninstalled grouped consumer, wired by the maintained-source derivation.
 * Included after the real registration/sysfs helpers. Every event header and
 * shared head retains the original PCI record in the SAME NodeFixed bank.
 * This source does not certify complete callback/allocation closure. */
static_assert(LSF_DEVICE_UEVENT_ENV == LSF_DEVICE_UEVENT_KIND_ENV);
static_assert(LSF_DEVICE_UEVENT_PATH == LSF_DEVICE_UEVENT_KIND_PATH);
static_assert(LSF_DEVICE_UEVENT_SKB == LSF_DEVICE_UEVENT_KIND_SKB);
static_assert(LSF_DEVICE_UEVENT_HEAD == LSF_DEVICE_UEVENT_KIND_HEAD);
static_assert(LSF_DEVICE_UEVENT_MAX_ANCESTORS == LSF_ALLOCATION_SLOTS);

static int lsf_device_uevent_kind(unsigned int kind)
{
    return kind == LSF_DEVICE_UEVENT_ENV || kind == LSF_DEVICE_UEVENT_PATH ||
        kind == LSF_DEVICE_UEVENT_SKB || kind == LSF_DEVICE_UEVENT_HEAD;
}

void lsf_factory_device_uevent_poison(void)
{
    unsigned long flags;
    spin_lock_irqsave(&pool_lock, flags);
    lsf_factory_device_firmware_poison();
    spin_unlock_irqrestore(&pool_lock, flags);
}

/* Caller holds pool_lock. Exact known application packet/audit types delegate
 * to their unchanged original dispatcher. This is not normal-heap fallback for
 * unknown addresses, device kinds, stale records or wrong pointer types. */
static int lsf_factory_device_uevent_lookup_locked(const void *address,
    unsigned int kind, struct lsf_device_registration_source *copy)
{
    struct lsf_prepaid_view *record;
    struct lsf_prepaid_ticket ticket;
    unsigned long base, value = (unsigned long)address;
    unsigned int i;
    if (!factory.pages)
        return 0;
    base = (unsigned long)page_address(factory.pages);
    if (value < base || value - base >= LSF_BACKING_BYTES)
        return 0;
    if (!copy || !lsf_device_uevent_kind(kind) || !factory.pool.initialized || factory.pool.poisoned)
        goto invalid;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->offset != value - base || record->phase != LSF_PREPAID_LIVE)
            continue;
        if ((kind == LSF_DEVICE_UEVENT_SKB &&
             (record->kind == LSF_PREPAID_PACKET_SKB || record->kind == LSF_PREPAID_AUDIT_SKB)) ||
            (kind == LSF_DEVICE_UEVENT_HEAD &&
             (record->kind == LSF_PREPAID_PACKET_HEAD || record->kind == LSF_PREPAID_AUDIT_HEAD)))
            return 0;
        ticket = (struct lsf_prepaid_ticket){i, record->generation};
        if (!factory.device ||
            record != lsf_device_record(&factory.pool, factory.device->key, ticket, kind) ||
            record->deferred != LSF_PREPAID_PUBLISHED ||
            (kind == LSF_DEVICE_UEVENT_SKB && record->bytes < sizeof(struct sk_buff)) ||
            (kind == LSF_DEVICE_UEVENT_ENV && record->bytes < sizeof(struct kobj_uevent_env)))
            goto invalid;
        *copy = (struct lsf_device_registration_source){
            .address = address, .kind = kind, .slot = i,
            .generation = record->generation, .pci_slot = record->cache_bucket,
            .pci_generation = record->cache_anchor,
        };
        if (!lsf_factory_device_registration_parent_locked(*copy))
            goto invalid;
        return 1;
    }
invalid:
    lsf_factory_device_firmware_poison();
    return -1;
}

/* Caller holds pool_lock. Root event allocation is lent only by the exact
 * real constructor or actual core-cleanup task extent. Descendant copies use
 * their own LIVE SKB source; no callback task borrow survives external return. */
static int lsf_factory_device_uevent_current_locked(struct lsf_device_registration_source source)
{
    struct lsf_factory_device_firmware *owned;
    struct lsf_device_registration_source actual;
    /* Descriptor close deliberately sets uncertain/stopped while retaining the
     * whole bank. A real LIVE SKB descendant or exact core-tail callback may
     * still need storage. Pool poison remains a hard refusal for every birth. */
    if (factory.pool.poisoned ||
        !(owned = lsf_factory_device_registration_parent_locked(source)) ||
        !owned->core_initialized || owned->queued || owned->putting || owned->returned)
        return 0;
    if (source.kind == LSF_DEVICE_UEVENT_SKB || source.kind == LSF_DEVICE_UEVENT_ENV) {
        if (lsf_factory_device_uevent_lookup_locked(source.address, source.kind, &actual) != 1 ||
            source.slot != actual.slot || source.generation != actual.generation ||
            source.pci_slot != actual.pci_slot || source.pci_generation != actual.pci_generation)
            return 0;
        /* Only actual SKB descendants can outlive the callback task. The env
         * may construct its first SKB only inside the same root callback. */
        if (source.kind == LSF_DEVICE_UEVENT_SKB)
            return 1;
    } else if (source.kind != LSF_DEVICE_PCI ||
        !lsf_factory_device_registration_record_locked(source, LSF_PREPAID_PUBLISHED)) {
        return 0;
    }
    if (in_interrupt())
        return 0;
    if (owned->core_tail_active && !owned->core_tail_complete &&
        factory.device->core_tail_task == current)
        return 1;
    return !READ_ONCE(factory.uncertain) && factory.device->constructor_active &&
        factory.device->constructor_task == current && !factory.pool.stopped && !factory.pool.contexts[LSF_DEVICE_OWNER_SLOT].closed &&
        lsf_factory_device_core_actor() && !owned->revoked && !owned->retirement &&
        !owned->core_tail_active && !owned->core_tail_complete;
}

int lsf_factory_device_uevent_kobject(const void *kobject,
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
            .address = address, .kind = LSF_DEVICE_PCI, .slot = pci.slot,
            .generation = pci.generation, .pci_slot = pci.slot, .pci_generation = pci.generation,
        };
        /* Classification is not authority. The real emitting path separately
         * checks current before callback/allocation. Unsupported synthetic or
         * show operations can refuse a known private device without lending
         * a constructor borrow or fabricating a pointer-origin certificate. */
    }
    if (result < 0)
        lsf_factory_device_firmware_poison();
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_device_uevent_birth(const void *address, unsigned int kind,
    struct lsf_device_registration_source *copy)
{
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_factory_device_uevent_lookup_locked(address, kind, copy);
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_device_uevent_current(struct lsf_device_registration_source source)
{
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_factory_device_uevent_current_locked(source);
    if (!result)
        lsf_factory_device_firmware_poison();
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void *lsf_factory_device_uevent_allocate(struct lsf_device_registration_source source,
    unsigned long bytes, unsigned int kind)
{
    struct lsf_prepaid_ticket parent = {source.pci_slot, source.pci_generation}, ticket;
    unsigned long flags;
    lsf_u64 offset;
    void *result = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    if (!bytes || !lsf_device_uevent_kind(kind) ||
        (kind == LSF_DEVICE_UEVENT_ENV && bytes != sizeof(struct kobj_uevent_env)) ||
        (kind == LSF_DEVICE_UEVENT_SKB && bytes != sizeof(struct sk_buff)) ||
        (kind == LSF_DEVICE_UEVENT_PATH && (bytes < 2 || bytes > PATH_MAX)) ||
        (kind == LSF_DEVICE_UEVENT_HEAD &&
         (bytes < SKB_DATA_ALIGN(sizeof(struct skb_shared_info)) ||
          bytes > LSF_DEVICE_UEVENT_MAX_HEAD_BYTES)) ||
        ((source.kind == LSF_DEVICE_UEVENT_SKB || source.kind == LSF_DEVICE_UEVENT_ENV) &&
         kind != LSF_DEVICE_UEVENT_SKB && kind != LSF_DEVICE_UEVENT_HEAD) ||
        !lsf_factory_device_uevent_current_locked(source))
        goto poison;
    if (!lsf_device_allocate(&factory.pool, factory.device->key, bytes, kind,
            parent, &ticket, &offset))
        goto out;
    result = (char *)page_address(factory.pages) + offset;
    memset(result, 0, bytes);
    /* This explicit transition must revalidate the unchanged LIVE original
     * parent even during drain. The old new-root publication API stays closed. */
    if (!lsf_device_uevent_publish(&factory.pool, factory.device->key, ticket, kind, parent)) {
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

int lsf_factory_device_uevent_return(const void *address, unsigned int kind)
{
    struct lsf_device_registration_source source;
    struct lsf_prepaid_ticket ticket;
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_factory_device_uevent_lookup_locked(address, kind, &source);
    if (result == 1) {
        ticket = (struct lsf_prepaid_ticket){source.slot, source.generation};
        if (!lsf_device_queue(&factory.pool, factory.device->key, ticket, kind) ||
            !lsf_device_finish(&factory.pool, factory.device->key, ticket, kind)) {
            lsf_factory_device_firmware_poison();
            result = -1;
        }
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    if (result == 1)
        lsf_factory_device_firmware_schedule();
    return result;
}

int lsf_factory_device_uevent_head_current(const void *address, unsigned long bytes,
    struct lsf_device_registration_source *copy)
{
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_factory_device_uevent_lookup_locked(address, LSF_DEVICE_UEVENT_HEAD, copy);
    if (result == 1 && (!bytes || bytes > factory.pool.records[copy->slot].bytes)) {
        lsf_factory_device_firmware_poison();
        result = -1;
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Actual admitted span before any path string read in another TU. This reads
 * only the existing typed birth record; no caller-provided length/byte-cost
 * can enlarge it or authorize a new owner. The callback still owns the path. */
int lsf_factory_device_uevent_path_bytes(const void *address,
    struct lsf_device_registration_source *copy, unsigned long *bytes)
{
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = bytes ? lsf_factory_device_uevent_lookup_locked(address,
        LSF_DEVICE_UEVENT_PATH, copy) : -1;
    if (result == 1) {
        *bytes = factory.pool.records[copy->slot].bytes;
        if (*bytes < 2 || *bytes > PATH_MAX) {
            lsf_factory_device_firmware_poison();
            result = -1;
        }
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
