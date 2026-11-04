/* SPDX-License-Identifier: GPL-2.0-only */
/* Qualification-only selected PCI birth and original synchronous return.
 * Included after the original Node actor. No socket, bind, IRQ or funding
 * authority is produced; uncertain cleanup retains the original escrow. */
#ifndef CONFIG_LSF_STREAM_NODE_PCI_PREFIX
#error "the prefix source requires its separate default-off image"
#endif

static struct lsf_node_parent *lsf_node_prefix_parent_locked(void)
{
    struct lsf_node_parent *node;
    unsigned long base;

    lockdep_assert_held(&pool_lock);
    if (!factory.pages || !factory.opened || !factory.pool.initialized)
        return NULL;
    base = (unsigned long)page_address(factory.pages);
    node = (void *)(base + LSF_FACTORY_INFRA_OFFSET);
    return lsf_node_capacity_parent_locked(&node->capacity);
}

/* Called only after the actual private pci_dev birth, before setup or device
 * registration. No candidate pointer is dereferenced before the existing
 * whole-birth classifier authenticates its original bank record. */
int lsf_node_prefix_pci_birth(struct pci_dev *pci)
{
    struct lsf_node_parent *node;
    struct lsf_prepaid_view *record;
    struct lsf_prepaid_context *owner;
    struct lsf_prepaid_ticket ticket = {0};
    unsigned long flags, base, value = (unsigned long)pci;
    unsigned int i;
    int result = -EOPNOTSUPP;

    if (lsf_factory_device_pci_owned(pci, sizeof(*pci)) != 1)
        goto poison_unlocked;
    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_prefix_parent_locked();
    if (!node || !lsf_node_constructor_actor_current() ||
        !factory.device || !factory.device->constructor_active ||
        factory.device->constructor_task != current ||
        !factory.device->pci_attempted || factory.device->firmware.slot ||
        node->prefix_birth || node->prefix_returned || node->prefix_pci.slot ||
        node->prefix_pci.generation || !pci->bus ||
        !lsf_factory_device_selected(pci_domain_nr(pci->bus), pci->bus->number, pci->devfn) ||
        pci->vendor != LSF_DEVICE_PCI_VENDOR || pci->device != LSF_DEVICE_PCI_DEVICE)
        goto poison;
    base = (unsigned long)page_address(factory.pages);
    if (value < base || value - base >= LSF_BACKING_BYTES)
        goto poison;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->kind != LSF_DEVICE_PCI || record->offset != value - base)
            continue;
        ticket = (struct lsf_prepaid_ticket){i, record->generation};
        if (!lsf_device_record(&factory.pool, factory.device->key, ticket, LSF_DEVICE_PCI) ||
            record->deferred != LSF_PREPAID_PUBLISHED || record->bytes < sizeof(*pci) ||
            record->cache_bucket != factory.device->root.slot ||
            record->cache_anchor != factory.device->root.generation)
            goto poison;
        break;
    }
    if (!ticket.slot || i == LSF_ALLOCATION_SLOTS)
        goto poison;
    owner = &factory.pool.contexts[node->owner.slot];
    if (node->prefix_before_live >= LSF_ALLOCATION_SLOTS ||
        owner->live != node->prefix_before_live + 1u ||
        owner->cursor <= node->prefix_before_cursor)
        goto poison;
    node->prefix_pci = ticket;
    node->prefix_peak_live = owner->live;
    node->prefix_peak_cursor = owner->cursor;
    node->prefix_birth = 1u;
    result = 1;
    goto out;
poison:
    factory.pool.poisoned = 1u;
    WRITE_ONCE(factory.uncertain, 1u);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
poison_unlocked:
    spin_lock_irqsave(&pool_lock, flags);
    factory.pool.poisoned = 1u;
    WRITE_ONCE(factory.uncertain, 1u);
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Called after the original bus put and the original PCI return. Do not
 * dereference the returned pointer or create a replacement owner. */
void lsf_node_prefix_pci_returned(int returned)
{
    struct lsf_node_parent *node;
    struct lsf_prepaid_view *record;
    struct lsf_prepaid_context *owner;
    unsigned long flags;

    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_prefix_parent_locked();
    if (!node || node->prefix_active != 1u || node->prefix_task != current ||
        node->prefix_birth != 1u || node->prefix_returned || returned != 1 ||
        !factory.device || factory.device->firmware.slot ||
        !node->prefix_pci.slot || node->prefix_pci.slot >= LSF_ALLOCATION_SLOTS ||
        !node->prefix_pci.generation)
        goto poison;
    record = &factory.pool.records[node->prefix_pci.slot];
    owner = &factory.pool.contexts[node->owner.slot];
    if (record->phase != LSF_PREPAID_RETURNED || record->kind != LSF_DEVICE_PCI ||
        record->generation != node->prefix_pci.generation ||
        record->owner != node->owner.slot || record->owner_generation != node->owner.generation ||
        record->cache_bucket != factory.device->root.slot ||
        record->cache_anchor != factory.device->root.generation ||
        owner->live != node->prefix_before_live || owner->cursor != node->prefix_peak_cursor)
        goto poison;
    node->prefix_after_live = owner->live;
    node->prefix_after_cursor = owner->cursor;
    node->prefix_returned = 1u;
    spin_unlock_irqrestore(&pool_lock, flags);
    return;
poison:
    factory.pool.poisoned = 1u;
    WRITE_ONCE(factory.uncertain, 1u);
    spin_unlock_irqrestore(&pool_lock, flags);
}

/* Caller holds the original factory mutex and a syscall reference to file.
 * It drops the mutex only after recording the exact current task; the PCI
 * entry acquires that same mutex. Other Node writes refuse while active. */
static int lsf_node_prefix_execute(struct file *file, struct lsf_node_parent *node)
{
    struct lsf_node_parent *after;
    struct lsf_prepaid_context *owner;
    unsigned long flags;
    int error;

    lockdep_assert_held(&factory_lock);
    if (!lsf_node_actor(file, node))
        return -EPERM;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_node_device_actor_current() || !factory.device ||
        !node->capacity.pcpu_prepared || node->prefix_attempted || node->prefix_active ||
        node->prefix_task || factory.device->pci_attempted || factory.device->constructor_active ||
        factory.device->constructor_task || factory.device->firmware.slot) {
        spin_unlock_irqrestore(&pool_lock, flags);
        return -EOPNOTSUPP;
    }
    owner = &factory.pool.contexts[node->owner.slot];
    if (owner->live >= LSF_ALLOCATION_SLOTS || owner->cursor > LSF_FACTORY_INFRA_BYTES) {
        spin_unlock_irqrestore(&pool_lock, flags);
        return -EOPNOTSUPP;
    }
    node->prefix_before_live = owner->live;
    node->prefix_before_cursor = owner->cursor;
    node->prefix_attempted = 1u;
    node->prefix_active = 1u;
    node->prefix_task = current;
    spin_unlock_irqrestore(&pool_lock, flags);

    mutex_unlock(&factory_lock);
    error = lsf_node_boot_pci_prefix();
    mutex_lock(&factory_lock);
    spin_lock_irqsave(&pool_lock, flags);
    after = lsf_node_prefix_parent_locked();
    if (after != node || !after || after->prefix_active != 1u ||
        after->prefix_attempted != 1u || after->prefix_task != current)
        goto poison;
    /* Revoke the borrowed task even after a failed or expired attempt. */
    after->prefix_active = 0u;
    after->prefix_task = NULL;
    if (error || after->prefix_birth != 1u || after->prefix_returned != 1u ||
        !lsf_node_device_actor_current() || factory.pool.poisoned ||
        READ_ONCE(factory.uncertain))
        goto poison;
    spin_unlock_irqrestore(&pool_lock, flags);
    pr_notice("LSFQ35PCIPREFIX1 bdf=0000:00:03.0 vendor=1af4 device=1041 born=1 returned=1 registered=0 scopeRevoked=1 slot=%u generation=%llu live=%u,%u,%u cursor=%llu,%llu,%llu\n",
        after->prefix_pci.slot, (unsigned long long)after->prefix_pci.generation,
        after->prefix_before_live, after->prefix_peak_live, after->prefix_after_live,
        (unsigned long long)after->prefix_before_cursor,
        (unsigned long long)after->prefix_peak_cursor,
        (unsigned long long)after->prefix_after_cursor);
    return 0;
poison:
    factory.pool.poisoned = 1u;
    WRITE_ONCE(factory.uncertain, 1u);
    spin_unlock_irqrestore(&pool_lock, flags);
    return -EIO;
}
