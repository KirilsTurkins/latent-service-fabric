/* SPDX-License-Identifier: GPL-2.0-only */
/* Included AFTER factory-device-firmware.c in the SAME original factory TU.
 * Reuses that existing descriptor and queue. No additional tail descriptor,
 * ledger, queue, allocation budget or pointer-based origin admission. */

/* Caller holds pool_lock. Only the original opening actor may allocate during
 * the already-fenced constructor. Late cleanup deliberately uses birth owners,
 * never this actor check or an attempt to reconstruct authority from a pointer. */
static int lsf_factory_device_core_actor(void)
{
    return factory.opened && current->mm == factory.mm &&
        task_tgid(current) == factory.tgid && current_cred() == factory.cred &&
        current->nsproxy && current->nsproxy->net_ns == factory.net;
}

/* Caller holds pool_lock. Classify the inner device/kobject address BEFORE
 * any dereference. An interior address only locates an existing whole PCI birth.
 * It never establishes a new birth or adopts an ordinary initialized device. */
static int lsf_factory_device_core_parent(const void *address,
    unsigned long displacement, struct lsf_prepaid_ticket *pci,
    const void **pci_address)
{
    unsigned long base, value = (unsigned long)address;
    if (!factory.pages)
        return 0;
    base = (unsigned long)page_address(factory.pages);
    if (value < base || value - base >= LSF_BACKING_BYTES)
        return 0;
    if (value - base < displacement)
        return -1;
    *pci_address = (const void *)(value - displacement);
    return lsf_factory_device_firmware_pci(*pci_address, pci) == 1 ? 1 : -1;
}

/* Before original device_initialize/pci_device_add can publish references.
 * Successful selected setup already owns the firmware descriptor, including
 * no-companion cases. Its actual storage now holds the finite core-tail state. */
int lsf_factory_device_core_begin(const void *address)
{
    struct lsf_factory_device_firmware *owned;
    struct lsf_prepaid_ticket pci;
    unsigned long flags;
    int error = -EOPNOTSUPP;
    spin_lock_irqsave(&pool_lock, flags);
    if (IS_ENABLED(CONFIG_DEBUG_KOBJECT_RELEASE) ||
        lsf_factory_device_firmware_pci(address, &pci) != 1 ||
        !(owned = lsf_factory_device_firmware_for_pci(address, pci)) ||
        !factory.device->constructor_active || !lsf_factory_device_core_actor() ||
        factory.pool.stopped ||
        READ_ONCE(factory.uncertain) || owned->core_initialized ||
        owned->retirement || owned->queued || owned->returned)
        goto out;
    owned->core_initialized = 1;
    error = 0;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return error;
}

int lsf_factory_device_core_owned(const void *device)
{
    struct lsf_factory_device_firmware *owned;
    struct lsf_prepaid_ticket pci;
    const void *address;
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_factory_device_core_parent(device, offsetof(struct pci_dev, dev),
        &pci, &address);
    if (!result)
        goto out;
    if (result < 0 ||
        !(owned = lsf_factory_device_firmware_for_pci(address, pci)) ||
        !owned->core_initialized || !factory.device->constructor_active ||
        !lsf_factory_device_core_actor() ||
        factory.pool.stopped || READ_ONCE(factory.uncertain) ||
        owned->retirement || owned->queued || owned->returned ||
        owned->core_tail_active || owned->core_tail_complete)
        goto poison;
    result = 1;
    goto out;
poison:
    lsf_factory_device_firmware_poison();
    result = -1;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void *lsf_factory_device_core_allocate(const void *device, unsigned long bytes)
{
    struct lsf_factory_device_firmware *owned;
    struct lsf_prepaid_ticket pci, ticket;
    const void *address;
    lsf_u64 offset;
    unsigned long flags;
    void *result = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    if (lsf_factory_device_core_parent(device, offsetof(struct pci_dev, dev),
            &pci, &address) != 1 ||
        !(owned = lsf_factory_device_firmware_for_pci(address, pci)) ||
        !owned->core_initialized || !factory.device->constructor_active ||
        !lsf_factory_device_core_actor() ||
        factory.pool.stopped || READ_ONCE(factory.uncertain) ||
        owned->retirement || owned->queued || owned->returned ||
        owned->core_tail_active || owned->core_tail_complete ||
        owned->core_private.slot || !bytes)
        goto poison;
    /* Actual sole caller supplies sizeof(struct device_private), not a cost
     * estimate. Allocate and publish from the original bank BEFORE dev->p. */
    if (!lsf_device_allocate(&factory.pool, factory.device->key, bytes,
            LSF_DEVICE_CORE_PRIVATE, factory.device->firmware, &ticket, &offset))
        goto out;
    result = (char *)page_address(factory.pages) + offset;
    memset(result, 0, bytes);
    if (!lsf_device_publish(&factory.pool, factory.device->key, ticket,
            LSF_DEVICE_CORE_PRIVATE)) {
        result = NULL;
        goto poison;
    }
    owned->core_private = ticket;
    goto out;
poison:
    lsf_factory_device_firmware_poison();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Caller holds pool_lock and already has the exact original descriptor. A
 * terminal child retains the same immutable birth fields; no record/address
 * reuse is possible in this live generation. Zero is only the genuine no-child
 * case, not an allowance for a malformed ticket or a missing live child. */
static int lsf_factory_device_core_child_retired(
    const struct lsf_factory_device_firmware *owned)
{
    struct lsf_prepaid_ticket ticket = owned->core_private;
    struct lsf_prepaid_view *record;
    if (!ticket.slot)
        return !ticket.generation;
    if (ticket.slot >= LSF_ALLOCATION_SLOTS || !ticket.generation)
        return 0;
    record = &factory.pool.records[ticket.slot];
    return record->phase == LSF_PREPAID_RETURNED &&
        record->generation == ticket.generation && record->kind == LSF_DEVICE_CORE_PRIVATE &&
        record->owner == factory.device->key.slot &&
        record->owner_generation == factory.device->key.generation &&
        record->cache_bucket == factory.device->firmware.slot &&
        record->cache_anchor == factory.device->firmware.generation &&
        record->offset >= LSF_FACTORY_INFRA_OFFSET && record->bytes &&
        record->offset - LSF_FACTORY_INFRA_OFFSET <= LSF_FACTORY_INFRA_BYTES &&
        record->bytes <= LSF_FACTORY_INFRA_BYTES -
            (record->offset - LSF_FACTORY_INFRA_OFFSET);
}

/* Exactly either original device_add's name_error free (constructor still
 * fenced) or device_release's final kfree(p) AFTER the real PCI release callback.
 * The PCI and existing descriptor retain the bank through the kobject tail. */
int lsf_factory_device_core_return(const void *device, const void *address)
{
    struct lsf_factory_device_firmware *owned;
    struct lsf_prepaid_view *record;
    struct lsf_prepaid_ticket pci, ticket;
    const void *pci_address;
    unsigned long flags, base, value = (unsigned long)address;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.pages)
        goto out;
    base = (unsigned long)page_address(factory.pages);
    result = lsf_factory_device_core_parent(device, offsetof(struct pci_dev, dev),
        &pci, &pci_address);
    if (!result) {
        /* A genuinely ordinary device does not authorize returning a private
         * child either. Only two genuinely outside values keep normal free. */
        if (value >= base && value - base < LSF_BACKING_BYTES)
            goto poison;
        goto out;
    }
    if (result < 0 ||
        !(owned = lsf_factory_device_firmware_for_pci(pci_address, pci)) ||
        !owned->core_initialized || owned->queued || owned->returned ||
        owned->core_tail_complete ||
        !((owned->core_tail_active && owned->retirement) ||
          (!owned->core_tail_active && !owned->retirement &&
           factory.device->constructor_active)))
        goto poison;
    if (!address) {
        if (!lsf_factory_device_core_child_retired(owned))
            goto poison;
        result = 0; /* Original kfree(NULL), including real name_error cleanup. */
        goto out;
    }
    if (value < base || value - base >= LSF_BACKING_BYTES)
        goto poison;
    ticket = owned->core_private;
    record = lsf_device_record(&factory.pool, factory.device->key, ticket,
        LSF_DEVICE_CORE_PRIVATE);
    if (!record || record->offset != value - base ||
        record->deferred != LSF_PREPAID_PUBLISHED ||
        record->cache_bucket != factory.device->firmware.slot ||
        record->cache_anchor != factory.device->firmware.generation ||
        !lsf_device_queue(&factory.pool, factory.device->key, ticket,
            LSF_DEVICE_CORE_PRIVATE) ||
        !lsf_device_finish(&factory.pool, factory.device->key, ticket,
            LSF_DEVICE_CORE_PRIVATE))
        goto poison;
    result = 1;
    goto out;
poison:
    lsf_factory_device_firmware_poison();
    result = -1;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_device_core_tail_enter(const void *kobject)
{
    struct lsf_factory_device_firmware *owned;
    struct lsf_prepaid_ticket pci;
    const void *address;
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_factory_device_core_parent(kobject,
        offsetof(struct pci_dev, dev) + offsetof(struct device, kobj), &pci, &address);
    if (!result)
        goto out;
    if (result < 0 ||
        !(owned = lsf_factory_device_firmware_for_pci(address, pci)) ||
        !owned->core_initialized || owned->retirement || owned->queued ||
        owned->returned || owned->core_tail_active || owned->core_tail_complete)
        goto poison;
    owned->core_tail_active = 1;
    result = 1;
    goto out;
poison:
    lsf_factory_device_firmware_poison();
    result = -1;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void lsf_factory_device_core_tail_finish(const void *kobject)
{
    struct lsf_factory_device_firmware *owned;
    struct lsf_prepaid_ticket pci;
    const void *address;
    unsigned long flags;
    spin_lock_irqsave(&pool_lock, flags);
    if (lsf_factory_device_core_parent(kobject,
            offsetof(struct pci_dev, dev) + offsetof(struct device, kobj), &pci, &address) != 1 ||
        !(owned = lsf_factory_device_firmware_for_pci(address, pci)) ||
        !owned->core_initialized || !owned->core_tail_active || !owned->retirement ||
        owned->queued || owned->returned || owned->core_tail_complete)
        goto poison;
    if (!lsf_factory_device_core_child_retired(owned))
        goto poison;
    /* No kobject/device dereference: original type release may have logically
     * freed them. Exact parent birth and the prepaid descriptor retain storage.
     * All original core/name/parent cleanup has now returned without our locks. */
    owned->core_tail_active = 0;
    owned->core_tail_complete = 1;
    spin_unlock_irqrestore(&pool_lock, flags);
    lsf_factory_device_firmware_schedule();
    return;
poison:
    lsf_factory_device_firmware_poison();
    spin_unlock_irqrestore(&pool_lock, flags);
}
