/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in the original factory TU after its real actor/locks/state. */
struct lsf_factory_device_state {
    struct lsf_prepaid_key key;
    struct lsf_prepaid_ticket root;
    unsigned int pci_attempted;
};

/* Caller holds factory_lock. Actual original open has acquired physical
 * backing and actor references already. This does not authenticate the still
 * missing sealed native bootstrap; selected_consumer remains NULL. */
static int lsf_factory_device_initialize(void)
{
    struct lsf_prepaid_key key;
    struct lsf_prepaid_ticket root;
    struct lsf_factory_device_state *state;
    lsf_u64 offset;
    unsigned long flags;
    int error = -ENOMEM;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.opened || !factory.pages || factory.device ||
        READ_ONCE(factory.uncertain) || !lsf_device_context_create(&factory.pool, &key) ||
        !lsf_device_allocate(&factory.pool, key, sizeof(*state), LSF_DEVICE_ROOT,
            (struct lsf_prepaid_ticket){0}, &root, &offset))
        goto poison;
    state = (void *)((char *)page_address(factory.pages) + offset);
    memset(state, 0, sizeof(*state));
    state->key = key;
    state->root = root;
    if (!lsf_device_publish(&factory.pool, key, root, LSF_DEVICE_ROOT))
        goto poison;
    factory.device = state;
    error = 0;
    goto out;
poison:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return error;
}

/* Same opening task/credentials/net and SAME original backing are required for
 * the one synchronous PCI constructor. This is not a general per-task allocator
 * override; later device callbacks require their actual inherited births. */
static int lsf_factory_device_pci_current(unsigned int domain, unsigned int bus,
                                         unsigned int devfn)
{
    return lsf_factory_device_selected(domain, bus, devfn) && factory.opened &&
        factory.pages && factory.device && !READ_ONCE(factory.uncertain) &&
        !factory.pool.stopped && current->mm == factory.mm &&
        task_tgid(current) == factory.tgid && current_cred() == factory.cred &&
        current->nsproxy && current->nsproxy->net_ns == factory.net &&
        lsf_device_record(&factory.pool, factory.device->key,
            factory.device->root, LSF_DEVICE_ROOT) &&
        !factory.pool.contexts[LSF_DEVICE_OWNER_SLOT].closed &&
        !factory.device->pci_attempted;
}

int lsf_factory_device_pci_ready(unsigned int domain, unsigned int bus,
                                unsigned int devfn)
{
    unsigned long flags;
    int ready;
    spin_lock_irqsave(&pool_lock, flags);
    ready = lsf_factory_device_pci_current(domain, bus, devfn);
    spin_unlock_irqrestore(&pool_lock, flags);
    return ready;
}

/* The original close path holds this SAME mutex before its pool fence. Do
 * not call from factory_open while it already holds the mutex. Normal device
 * probing and unrelated devices do not acquire this private lock. */
int lsf_factory_device_pci_enter(unsigned int domain, unsigned int bus,
                                unsigned int devfn)
{
    mutex_lock(&factory_lock);
    if (!lsf_factory_device_pci_ready(domain, bus, devfn)) {
        mutex_unlock(&factory_lock);
        return 0;
    }
    return 1;
}

void lsf_factory_device_pci_leave(void)
{
    mutex_unlock(&factory_lock);
}

void *lsf_factory_device_pci_allocate(unsigned int domain, unsigned int bus,
                                     unsigned int devfn, unsigned long bytes)
{
    struct lsf_prepaid_ticket ticket;
    lsf_u64 offset;
    unsigned long flags;
    void *result = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    if (lsf_factory_device_pci_current(domain, bus, devfn) &&
        lsf_device_allocate(&factory.pool, factory.device->key, bytes,
            LSF_DEVICE_PCI, factory.device->root, &ticket, &offset)) {
        result = (char *)page_address(factory.pages) + offset;
        memset(result, 0, bytes);
        if (!lsf_device_publish(&factory.pool, factory.device->key, ticket, LSF_DEVICE_PCI)) {
            factory.pool.poisoned = 1;
            WRITE_ONCE(factory.uncertain, 1);
            result = NULL;
            goto out;
        }
        /* One source-selected construction, no hidden allocator retry/reprobe.
         * Failed setup returns only its view; it cannot refund Node backing. */
        factory.device->pci_attempted = 1;
    }
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* No address is dereferenced until exact arena membership and the original
 * generation/parent/kind have been proved from the SAME birth record. A pointer
 * only locates a prior birth for RETURN; it can never establish a new owner.
 * The only callers are the unchanged original failed-setup cleanup and final
 * PCI device.release callback, AFTER their actual physical cleanup/ref puts. */
int lsf_factory_device_pci_return(const void *address)
{
    struct lsf_prepaid_ticket ticket = {0};
    struct lsf_prepaid_view *record;
    unsigned long flags, base, value = (unsigned long)address;
    unsigned int i;
    int returned = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.pages)
        goto out;
    base = (unsigned long)page_address(factory.pages);
    if (value < base || value - base >= LSF_BACKING_BYTES)
        goto out;
    returned = -1;
    if (!factory.device)
        goto poison;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->offset != value - base || record->kind != LSF_DEVICE_PCI)
            continue;
        ticket = (struct lsf_prepaid_ticket){i, record->generation};
        if (record->cache_bucket != factory.device->root.slot ||
            record->cache_anchor != factory.device->root.generation ||
            !lsf_device_queue(&factory.pool, factory.device->key, ticket, LSF_DEVICE_PCI) ||
            !lsf_device_finish(&factory.pool, factory.device->key, ticket, LSF_DEVICE_PCI))
            goto poison;
        returned = 1;
        goto out;
    }
poison:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return returned;
}

/* Only revalidates a prior whole PCI birth for the private setup call. It
 * cannot attach an existing normal device or grant a descriptor/actor scope. */
int lsf_factory_device_pci_owned(const void *address, unsigned long minimum)
{
    struct lsf_prepaid_ticket ticket;
    struct lsf_prepaid_view *record;
    unsigned long flags, base, value = (unsigned long)address;
    unsigned int i;
    int owned = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.pages)
        goto out;
    base = (unsigned long)page_address(factory.pages);
    if (value < base || value - base >= LSF_BACKING_BYTES)
        goto out;
    owned = -1;
    if (!factory.device || !minimum || factory.pool.stopped ||
        READ_ONCE(factory.uncertain) ||
        !lsf_device_record(&factory.pool, factory.device->key,
            factory.device->root, LSF_DEVICE_ROOT))
        goto poison;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->offset != value - base || record->kind != LSF_DEVICE_PCI)
            continue;
        ticket = (struct lsf_prepaid_ticket){i, record->generation};
        if (!lsf_device_record(&factory.pool, factory.device->key, ticket, LSF_DEVICE_PCI) ||
            record->deferred != LSF_PREPAID_PUBLISHED || record->bytes < minimum ||
            record->cache_bucket != factory.device->root.slot ||
            record->cache_anchor != factory.device->root.generation)
            goto poison;
        owned = 1;
        goto out;
    }
poison:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return owned;
}
