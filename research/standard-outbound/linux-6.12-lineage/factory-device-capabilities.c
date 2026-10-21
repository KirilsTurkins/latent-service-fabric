/* SPDX-License-Identifier: GPL-2.0-only */
/* Included AFTER factory-device-core.c in the SAME original factory TU.
 * No new descriptors/table: actual saved-capability objects are children of
 * their already-born whole PCI device in the original infrastructure bank. */

/* Caller holds pool_lock. Allocation belongs only to the actual original
 * constructor and its opening actor. This does not authenticate an installed
 * platform or permit future capability requests to fall back to normal heap. */
static int lsf_factory_device_capabilities_current(const void *address,
    struct lsf_prepaid_ticket *pci)
{
    struct lsf_factory_device_firmware *owned;
    int result = lsf_factory_device_firmware_pci(address, pci);
    if (!result)
        return 0;
    if (result < 0 ||
        !(owned = lsf_factory_device_firmware_for_pci(address, *pci)) ||
        !owned->core_initialized || !factory.device->constructor_active ||
        !lsf_factory_device_core_actor() || factory.pool.stopped ||
        READ_ONCE(factory.uncertain) || owned->retirement || owned->queued ||
        owned->returned || owned->core_tail_active || owned->core_tail_complete)
        return -1;
    return 1;
}

int lsf_factory_device_capabilities_owned(const void *address)
{
    struct lsf_prepaid_ticket pci;
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_factory_device_capabilities_current(address, &pci);
    if (result < 0)
        lsf_factory_device_firmware_poison();
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void *lsf_factory_device_capability_allocate(const void *address,
    unsigned long bytes)
{
    struct lsf_prepaid_ticket pci, ticket;
    unsigned long flags;
    lsf_u64 offset;
    void *result = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    if (!bytes || lsf_factory_device_capabilities_current(address, &pci) != 1)
        goto poison;
    /* The actual maintained allocator supplies its checked sizeof+payload.
     * Admission and publication precede every byte/address exposure. Fixed
     * 192 KiB/256-record exhaustion returns NULL, without retry or refund. */
    if (!lsf_device_allocate(&factory.pool, factory.device->key, bytes,
            LSF_DEVICE_CAP_SAVE, pci, &ticket, &offset))
        goto out;
    result = (char *)page_address(factory.pages) + offset;
    memset(result, 0, bytes);
    if (!lsf_device_publish(&factory.pool, factory.device->key, ticket,
            LSF_DEVICE_CAP_SAVE)) {
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

/* Actual pci_free_cap_save_buffers supplies BOTH its PCI device and each
 * original hlist member. A pointer only locates an existing birth. It cannot
 * adopt an outside child or return another device's private allocation.
 * Normal device/outside child preserves upstream kfree, including ordinary
 * final callbacks after our private factory has closed or poisoned. */
int lsf_factory_device_capability_return(const void *address, const void *child)
{
    struct lsf_prepaid_ticket pci, ticket;
    struct lsf_prepaid_view *record;
    unsigned long flags, base, value = (unsigned long)child;
    unsigned int i;
    int parent, result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.pages)
        goto out;
    base = (unsigned long)page_address(factory.pages);
    parent = lsf_factory_device_firmware_pci(address, &pci);
    if (value < base || value - base >= LSF_BACKING_BYTES) {
        if (!parent)
            goto out;
        goto poison;
    }
    if (parent != 1)
        goto poison;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->offset != value - base || record->kind != LSF_DEVICE_CAP_SAVE)
            continue;
        ticket = (struct lsf_prepaid_ticket){i, record->generation};
        if (record->cache_bucket != pci.slot || record->cache_anchor != pci.generation ||
            !lsf_device_queue(&factory.pool, factory.device->key, ticket, LSF_DEVICE_CAP_SAVE) ||
            !lsf_device_finish(&factory.pool, factory.device->key, ticket, LSF_DEVICE_CAP_SAVE))
            goto poison;
        result = 1;
        goto out;
    }
poison:
    lsf_factory_device_firmware_poison();
    result = -1;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
