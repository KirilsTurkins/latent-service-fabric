/* SPDX-License-Identifier: GPL-2.0-only */
/* Included AFTER factory-device.c. One prepaid descriptor, one real reference,
 * one existing ACPI work item. No new queue, address adoption or second ledger.
 * Both child descriptor and original PCI parent remain LIVE through actual put.
 * The existing ACPI queue/bootstrap costs are NOT yet physically qualified. */
struct lsf_factory_device_firmware {
    struct work_struct work;
    struct lsf_prepaid_ticket pci;
    const void *pci_address;
    struct acpi_device *companion;
    acpi_handle handle;
    unsigned int revoked, retirement, queued, putting, returned;
};

static void lsf_factory_device_firmware_poison(void)
{
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
}

/* Caller holds pool_lock. Every address is classified before dereference. */
static int lsf_factory_device_firmware_pci(const void *address,
    struct lsf_prepaid_ticket *ticket)
{
    struct lsf_prepaid_view *record;
    unsigned long base, value = (unsigned long)address;
    unsigned int i;
    if (!factory.pages)
        return 0;
    base = (unsigned long)page_address(factory.pages);
    if (value < base || value - base >= LSF_BACKING_BYTES)
        return 0;
    if (!factory.device)
        return -1;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->offset != value - base || record->kind != LSF_DEVICE_PCI)
            continue;
        *ticket = (struct lsf_prepaid_ticket){i, record->generation};
        if (!lsf_device_record(&factory.pool, factory.device->key, *ticket, LSF_DEVICE_PCI) ||
            record->bytes < sizeof(struct pci_dev) ||
            record->deferred != LSF_PREPAID_PUBLISHED ||
            record->cache_bucket != factory.device->root.slot ||
            record->cache_anchor != factory.device->root.generation)
            return -1;
        return 1;
    }
    return -1;
}

/* Returned records cannot be reused. Their bytes remain in the same backing;
 * recognizing that exact terminal record is NOT a second return/adoption. */
static struct lsf_factory_device_firmware *lsf_factory_device_firmware_locked(void)
{
    struct lsf_prepaid_ticket ticket;
    struct lsf_prepaid_view *record;
    if (!factory.pages || !factory.device ||
        !lsf_device_context(&factory.pool, factory.device->key))
        return NULL;
    ticket = factory.device->firmware;
    if (!ticket.slot || ticket.slot >= LSF_ALLOCATION_SLOTS || !ticket.generation)
        return NULL;
    record = &factory.pool.records[ticket.slot];
    if (record->generation != ticket.generation || record->kind != LSF_DEVICE_ACPI_REFERENCE ||
        record->owner != factory.device->key.slot ||
        record->owner_generation != factory.device->key.generation ||
        (record->phase != LSF_PREPAID_LIVE && record->phase != LSF_PREPAID_RETURNED) ||
        record->offset < LSF_FACTORY_INFRA_OFFSET ||
        record->offset - LSF_FACTORY_INFRA_OFFSET > LSF_FACTORY_INFRA_BYTES ||
        record->bytes < sizeof(struct lsf_factory_device_firmware) ||
        record->bytes > LSF_FACTORY_INFRA_BYTES - (record->offset - LSF_FACTORY_INFRA_OFFSET))
        return NULL;
    return (void *)((char *)page_address(factory.pages) + record->offset);
}

static struct lsf_factory_device_firmware *lsf_factory_device_firmware_for_pci(
    const void *address, struct lsf_prepaid_ticket pci)
{
    struct lsf_factory_device_firmware *owned = lsf_factory_device_firmware_locked();
    struct lsf_prepaid_view *record;
    if (!owned)
        return NULL;
    record = &factory.pool.records[factory.device->firmware.slot];
    if (record->cache_bucket != pci.slot || record->cache_anchor != pci.generation ||
        owned->pci.slot != pci.slot || owned->pci.generation != pci.generation ||
        owned->pci_address != address)
        return NULL;
    return owned;
}

static void lsf_factory_device_firmware_put(struct work_struct *work)
{
    struct lsf_factory_device_firmware *owned;
    struct acpi_device *companion;
    struct pci_dev *pci;
    struct lsf_prepaid_ticket pci_ticket;
    unsigned long flags;
    int finished = 0;
    spin_lock_irqsave(&pool_lock, flags);
    owned = lsf_factory_device_firmware_locked();
    if (!owned || &owned->work != work || !owned->retirement || !owned->queued ||
        owned->putting || owned->returned || factory.device->constructor_active ||
        factory.pool.records[factory.device->firmware.slot].deferred != LSF_PREPAID_QUEUED ||
        lsf_factory_device_firmware_pci(owned->pci_address, &pci_ticket) != 1 ||
        !lsf_factory_device_firmware_for_pci(owned->pci_address, pci_ticket))
        goto poison;
    owned->putting = 1;
    companion = owned->companion;
    pci = (struct pci_dev *)owned->pci_address;
    spin_unlock_irqrestore(&pool_lock, flags);

    /* This real work callback owns NO factory/ACPI/pool mutex or spinlock.
     * Original failed-setup/final PCI cleanup has already run. Never leave a
     * raw firmware pointer published after dropping its last owned reference. */
    if (companion) {
        if (ACPI_COMPANION(&pci->dev) == companion)
            ACPI_COMPANION_SET(&pci->dev, NULL);
        else if (dev_fwnode(&pci->dev))
            goto poison_unlocked;
        acpi_dev_put(companion);
    }

    /* No dereference of companion after put. A concurrent invalidation may
     * revoke currentness, but cannot retire/reuse this descriptor or PCI view. */
    spin_lock_irqsave(&pool_lock, flags);
    owned = lsf_factory_device_firmware_locked();
    if (!owned || &owned->work != work || !owned->putting || owned->returned ||
        owned->companion != companion ||
        !lsf_factory_device_firmware_for_pci(pci, owned->pci))
        goto poison;
    owned->companion = NULL;
    owned->handle = NULL;
    if (!lsf_device_finish(&factory.pool, factory.device->key,
            factory.device->firmware, LSF_DEVICE_ACPI_REFERENCE))
        goto poison;
    owned->returned = 1;
    finished = 1;
    spin_unlock_irqrestore(&pool_lock, flags);
    if (finished)
        (void)lsf_factory_device_pci_return(pci);
    return;
poison_unlocked:
    spin_lock_irqsave(&pool_lock, flags);
poison:
    lsf_factory_device_firmware_poison();
    spin_unlock_irqrestore(&pool_lock, flags);
}

static void lsf_factory_device_firmware_schedule(void)
{
    struct lsf_factory_device_firmware *owned;
    struct work_struct *work = NULL;
    unsigned long flags;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.device || !factory.device->firmware.slot)
        goto out;
    owned = lsf_factory_device_firmware_locked();
    if (!owned)
        goto poison;
    if (factory.device->constructor_active || !owned->retirement || owned->queued || owned->returned)
        goto out;
    if (!lsf_device_queue(&factory.pool, factory.device->key,
            factory.device->firmware, LSF_DEVICE_ACPI_REFERENCE))
        goto poison;
    owned->queued = 1;
    work = &owned->work;
    spin_unlock_irqrestore(&pool_lock, flags);
    /* Exact original ordered queue. One preallocated work record, no retry.
     * A stopped/unavailable queue retains BOTH physical reference and parent. */
    if (lsf_prepaid_acpi_queue_reference_put(work))
        return;
    spin_lock_irqsave(&pool_lock, flags);
poison:
    lsf_factory_device_firmware_poison();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
}

int lsf_factory_device_firmware_constructor_enter(void)
{
    unsigned long flags;
    int entered = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (factory.device && !factory.device->constructor_active) {
        factory.device->constructor_active = 1;
        entered = 1;
    } else {
        lsf_factory_device_firmware_poison();
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return entered;
}

void lsf_factory_device_firmware_constructor_leave(void)
{
    unsigned long flags;
    /* Caller has ALREADY unlocked factory_lock; no final put can be queued by
     * setup-failure return until this exact constructor-active fence clears. */
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.device || !factory.device->constructor_active) {
        lsf_factory_device_firmware_poison();
        spin_unlock_irqrestore(&pool_lock, flags);
        return;
    }
    factory.device->constructor_active = 0;
    spin_unlock_irqrestore(&pool_lock, flags);
    lsf_factory_device_firmware_schedule();
}

int lsf_factory_device_firmware_begin(const void *address)
{
    struct lsf_factory_device_firmware *owned;
    struct lsf_prepaid_ticket pci, ticket;
    lsf_u64 offset;
    unsigned long flags;
    int error = -EOPNOTSUPP;
    spin_lock_irqsave(&pool_lock, flags);
    if (lsf_factory_device_firmware_pci(address, &pci) != 1 ||
        !factory.device->constructor_active || factory.device->firmware.slot ||
        factory.pool.stopped || READ_ONCE(factory.uncertain) ||
        !lsf_device_allocate(&factory.pool, factory.device->key, sizeof(*owned),
            LSF_DEVICE_ACPI_REFERENCE, pci, &ticket, &offset))
        goto out;
    owned = (void *)((char *)page_address(factory.pages) + offset);
    memset(owned, 0, sizeof(*owned));
    owned->pci = pci;
    owned->pci_address = address;
    INIT_WORK(&owned->work, lsf_factory_device_firmware_put);
    if (!lsf_device_publish(&factory.pool, factory.device->key, ticket, LSF_DEVICE_ACPI_REFERENCE)) {
        lsf_factory_device_firmware_poison();
        goto out;
    }
    factory.device->firmware = ticket;
    error = 0;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return error;
}

int lsf_factory_device_firmware_get(const void *address, struct acpi_device *adev)
{
    struct lsf_factory_device_firmware *owned;
    struct lsf_prepaid_ticket pci;
    unsigned long flags;
    int error = -EOPNOTSUPP;
    spin_lock_irqsave(&pool_lock, flags);
    if (lsf_factory_device_firmware_pci(address, &pci) != 1 ||
        !(owned = lsf_factory_device_firmware_for_pci(address, pci)) ||
        owned->companion || owned->retirement || owned->returned || owned->revoked ||
        READ_ONCE(factory.uncertain) || !adev)
        goto out;
    /* The exact original iterator has a live device/kobject reference here.
     * Original acpi_dev_get -> get_device -> kobject_get only increments kref;
     * it invokes no callback, allocator or final put under this spinlock. */
    owned->companion = acpi_dev_get(adev);
    owned->handle = adev->handle;
    if (owned->companion != adev) {
        lsf_factory_device_firmware_poison();
        goto out;
    }
    error = 0;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return error;
}

int lsf_factory_device_firmware_current(const void *address, struct acpi_device *adev)
{
    struct lsf_factory_device_firmware *owned;
    struct lsf_prepaid_ticket pci;
    unsigned long flags;
    int current_reference = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (lsf_factory_device_firmware_pci(address, &pci) == 1 &&
        (owned = lsf_factory_device_firmware_for_pci(address, pci)) &&
        !owned->revoked && !owned->retirement && !owned->returned &&
        !READ_ONCE(factory.uncertain) && owned->companion == adev &&
        (!adev || owned->handle == adev->handle))
        current_reference = 1;
    spin_unlock_irqrestore(&pool_lock, flags);
    return current_reference;
}

/* Called under the SAME original deletion mutex BEFORE handle invalidation.
 * Pointer/handle only match a reference already born from the real iterator;
 * no caller can use this to create/adopt authority. Revocation is NOT free. */
void lsf_factory_device_firmware_invalidate(struct acpi_device *adev, const void *handle)
{
    struct lsf_factory_device_firmware *owned;
    unsigned long flags;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.device || !factory.device->firmware.slot)
        goto out;
    owned = lsf_factory_device_firmware_locked();
    if (!owned) {
        lsf_factory_device_firmware_poison();
        goto out;
    }
    if (!owned->returned && owned->companion == adev) {
        if (owned->handle != handle)
            lsf_factory_device_firmware_poison();
        owned->revoked = 1;
        WRITE_ONCE(factory.uncertain, 1);
    }
out:
    spin_unlock_irqrestore(&pool_lock, flags);
}

/* Nonzero consumes private PCI return WITHOUT retiring it. Actual final put
 * and child finish happen in the work callback, then original PCI return runs.
 * Zero leaves unchanged normal/outside/no-reference return paths in control. */
int lsf_factory_device_firmware_retire(const void *address)
{
    struct lsf_factory_device_firmware *owned;
    struct lsf_prepaid_ticket pci;
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_factory_device_firmware_pci(address, &pci);
    if (!result)
        goto out;
    if (result < 0)
        goto poison;
    result = 0;
    if (!factory.device->firmware.slot)
        goto out;
    owned = lsf_factory_device_firmware_for_pci(address, pci);
    if (!owned)
        goto poison;
    if (owned->returned)
        goto out;
    if (owned->retirement)
        goto poison;
    owned->retirement = 1;
    spin_unlock_irqrestore(&pool_lock, flags);
    lsf_factory_device_firmware_schedule();
    return 1;
poison:
    lsf_factory_device_firmware_poison();
    result = -1;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
