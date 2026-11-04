/* SPDX-License-Identifier: GPL-2.0-only */
/* Qualification-only PCI setup prefix. The existing Node and its records
 * own every view; queued firmware retirement is not a completed return. */
#ifndef CONFIG_LSF_STREAM_NODE_PCI_SETUP
#error "PCI setup observation requires its separate default-off image"
#endif

#include <linux/sched.h>
#include <linux/sched/signal.h>

/* Called with pool_lock. The stored tickets locate existing records only;
 * neither the callback nor an address can create or adopt an owner. */
static int lsf_node_setup_records_locked(struct lsf_node_parent *node,
    struct lsf_prepaid_view **pci_record, struct lsf_prepaid_view **fw_record,
    struct lsf_factory_device_firmware **firmware)
{
    struct lsf_prepaid_view *pci, *fw;
    struct lsf_factory_device_firmware *owned;
    unsigned long base, address;

    lockdep_assert_held(&pool_lock);
    if (!node || !factory.device || !node->prefix_pci.slot ||
        node->prefix_pci.slot >= LSF_ALLOCATION_SLOTS ||
        !node->prefix_pci.generation || !node->prefix_firmware.slot ||
        node->prefix_firmware.slot >= LSF_ALLOCATION_SLOTS ||
        !node->prefix_firmware.generation ||
        node->prefix_pci.slot == node->prefix_firmware.slot ||
        factory.device->firmware.slot != node->prefix_firmware.slot ||
        factory.device->firmware.generation != node->prefix_firmware.generation ||
        factory.device->key.slot != node->owner.slot ||
        factory.device->key.generation != node->owner.generation)
        return 0;
    pci = &factory.pool.records[node->prefix_pci.slot];
    fw = &factory.pool.records[node->prefix_firmware.slot];
    if (pci->kind != LSF_DEVICE_PCI ||
        pci->generation != node->prefix_pci.generation ||
        pci->owner != node->owner.slot ||
        pci->owner_generation != node->owner.generation ||
        pci->offset < LSF_FACTORY_INFRA_OFFSET ||
        pci->offset - LSF_FACTORY_INFRA_OFFSET > LSF_FACTORY_INFRA_BYTES ||
        pci->bytes < sizeof(struct pci_dev) ||
        pci->bytes > LSF_FACTORY_INFRA_BYTES - (pci->offset - LSF_FACTORY_INFRA_OFFSET) ||
        (pci->phase != LSF_PREPAID_LIVE && pci->phase != LSF_PREPAID_RETURNED) ||
        pci->cache_bucket != factory.device->root.slot ||
        pci->cache_anchor != factory.device->root.generation ||
        fw->kind != LSF_DEVICE_ACPI_REFERENCE ||
        fw->generation != node->prefix_firmware.generation ||
        fw->owner != node->owner.slot ||
        fw->owner_generation != node->owner.generation ||
        fw->cache_bucket != node->prefix_pci.slot ||
        fw->cache_anchor != node->prefix_pci.generation ||
        (fw->phase != LSF_PREPAID_LIVE && fw->phase != LSF_PREPAID_RETURNED))
        return 0;
    owned = lsf_factory_device_firmware_locked();
    if (!owned || owned->pci.slot != node->prefix_pci.slot ||
        owned->pci.generation != node->prefix_pci.generation ||
        owned->core_initialized || owned->core_tail_active ||
        owned->core_tail_complete || owned->core_private.slot ||
        owned->core_private.generation)
        return 0;
    base = (unsigned long)page_address(factory.pages);
    address = (unsigned long)owned->pci_address;
    if (address < base || address - base != pci->offset)
        return 0;
    *pci_record = pci;
    *fw_record = fw;
    *firmware = owned;
    return 1;
}

/* Called from the real paid setup after class/config discovery, before early
 * fixups or BAR probing. The whole PCI view is authenticated before reads. */
int lsf_node_setup_reached(struct pci_dev *pci)
{
    struct lsf_node_parent *node;
    struct lsf_prepaid_view *pci_record, *fw_record;
    struct lsf_factory_device_firmware *owned;
    struct lsf_prepaid_context *context;
    unsigned long flags;
    int result = 0;

    if (lsf_factory_device_pci_owned(pci, sizeof(*pci)) != 1)
        goto poison_unlocked;
    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_prefix_parent_locked();
    if (!node || !lsf_node_constructor_actor_current() ||
        !node->prefix_birth || node->prefix_setup || node->prefix_pending ||
        !factory.device || !factory.device->constructor_active ||
        factory.device->constructor_task != current ||
        !factory.device->firmware.slot || !factory.device->firmware.generation)
        goto poison;
    node->prefix_firmware = factory.device->firmware;
    if (!lsf_node_setup_records_locked(node, &pci_record, &fw_record, &owned) ||
        pci_record->phase != LSF_PREPAID_LIVE ||
        pci_record->deferred != LSF_PREPAID_PUBLISHED ||
        fw_record->phase != LSF_PREPAID_LIVE ||
        fw_record->deferred != LSF_PREPAID_PUBLISHED ||
        owned->pci_address != pci || owned->retirement || owned->queued ||
        owned->putting || owned->returned || owned->revoked || owned->put_error ||
        !pci->bus || !lsf_factory_device_selected(pci_domain_nr(pci->bus),
            pci->bus->number, pci->devfn) ||
        pci->vendor != LSF_DEVICE_PCI_VENDOR || pci->device != LSF_DEVICE_PCI_DEVICE ||
        pci->hdr_type != PCI_HEADER_TYPE_NORMAL ||
        (pci->class >> 8) != PCI_CLASS_NETWORK_ETHERNET ||
        (pci->cfg_size != PCI_CFG_SPACE_SIZE && pci->cfg_size != PCI_CFG_SPACE_EXP_SIZE) ||
        pci_dev_is_added(pci) || !dev_name(&pci->dev) ||
        !is_kernel_rodata((unsigned long)dev_name(&pci->dev)) ||
        strcmp(dev_name(&pci->dev), LSF_DEVICE_PCI_NAME) ||
        ACPI_COMPANION(&pci->dev) != owned->companion)
        goto poison;
    context = &factory.pool.contexts[node->owner.slot];
    if (node->prefix_before_live > LSF_ALLOCATION_SLOTS - 2u ||
        context->live != node->prefix_before_live + 2u ||
        context->cursor <= node->prefix_peak_cursor ||
        context->cursor > LSF_FACTORY_INFRA_BYTES)
        goto poison;
    node->prefix_peak_live = context->live;
    node->prefix_peak_cursor = context->cursor;
    node->prefix_header = pci->hdr_type;
    node->prefix_class = pci->class;
    node->prefix_config_size = pci->cfg_size;
    node->prefix_companion = owned->companion ? 1u : 0u;
    node->prefix_setup = 1u;
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
    goto poison;
}

/* The original return has requested firmware retirement, but constructor
 * scope still prevents its queue from running. Both records must remain live. */
void lsf_node_setup_pending(struct pci_dev *pci, int setup_error, int requested)
{
    struct lsf_node_parent *node;
    struct lsf_prepaid_view *pci_record, *fw_record;
    struct lsf_factory_device_firmware *owned;
    unsigned long flags;

    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_prefix_parent_locked();
    if (!node || !lsf_node_constructor_actor_current() ||
        !node->prefix_birth || !node->prefix_setup || node->prefix_pending ||
        setup_error != -ECANCELED || requested != 1 || !factory.device ||
        !factory.device->constructor_active || factory.device->constructor_task != current ||
        !lsf_node_setup_records_locked(node, &pci_record, &fw_record, &owned) ||
        owned->pci_address != pci || !owned->retirement || owned->queued ||
        owned->putting || owned->returned || owned->put_error ||
        pci_record->phase != LSF_PREPAID_LIVE ||
        pci_record->deferred != LSF_PREPAID_PUBLISHED ||
        fw_record->phase != LSF_PREPAID_LIVE ||
        fw_record->deferred != LSF_PREPAID_PUBLISHED)
        goto poison;
    node->prefix_pending = 1u;
    spin_unlock_irqrestore(&pool_lock, flags);
    return;
poison:
    factory.pool.poisoned = 1u;
    WRITE_ONCE(factory.uncertain, 1u);
    spin_unlock_irqrestore(&pool_lock, flags);
}

/* A missing intentional stop must never continue into PCI device_add. */
void lsf_node_setup_unexpected(void)
{
    unsigned long flags;
    spin_lock_irqsave(&pool_lock, flags);
    factory.pool.poisoned = 1u;
    WRITE_ONCE(factory.uncertain, 1u);
    spin_unlock_irqrestore(&pool_lock, flags);
}

/* The same syscall retains its file. Constructor authority has already been
 * revoked and no mutex, spinlock or PCI rescan lock is held here. The existing
 * Node deadline bounds a cooperative wait; no new queue or allocation exists.
 * Child-returned / PCI-live is still pending, never a success. */
static int lsf_node_setup_wait(struct lsf_node_parent *expected)
{
    struct lsf_node_parent *node;
    struct lsf_prepaid_view *pci, *fw;
    struct lsf_factory_device_firmware *owned;
    struct lsf_prepaid_context *context;
    unsigned long flags;
    int result;

    for (;;) {
        if (fatal_signal_pending(current))
            return -EINTR;
        spin_lock_irqsave(&pool_lock, flags);
        node = lsf_node_prefix_parent_locked();
        result = -EIO;
        if (!node || node != expected || node->prefix_active ||
            node->prefix_waiting != 1u || node->prefix_task ||
            !node->prefix_birth || !node->prefix_setup || !node->prefix_pending ||
            node->prefix_returned || !lsf_node_device_actor_current() ||
            !factory.device || factory.device->constructor_active ||
            factory.device->constructor_task || factory.pool.poisoned ||
            READ_ONCE(factory.uncertain) ||
            !lsf_node_setup_records_locked(node, &pci, &fw, &owned) ||
            !owned->retirement || !owned->queued || owned->revoked || owned->put_error)
            goto unlock;
        if (fw->phase == LSF_PREPAID_LIVE && !owned->returned &&
            pci->phase == LSF_PREPAID_LIVE) {
            result = 1; /* Original work still owns both records. */
            goto unlock;
        }
        if (fw->phase == LSF_PREPAID_RETURNED && owned->returned &&
            !owned->companion && !owned->handle && pci->phase == LSF_PREPAID_LIVE) {
            result = 1; /* Child finished; PCI callback has not finished yet. */
            goto unlock;
        }
        if (fw->phase != LSF_PREPAID_RETURNED || !owned->returned ||
            owned->companion || owned->handle || pci->phase != LSF_PREPAID_RETURNED)
            goto unlock;
        context = &factory.pool.contexts[node->owner.slot];
        if (context->live != node->prefix_before_live ||
            context->cursor != node->prefix_peak_cursor)
            goto unlock;
        node->prefix_after_live = context->live;
        node->prefix_after_cursor = context->cursor;
        node->prefix_returned = 1u;
        result = 0;
unlock:
        spin_unlock_irqrestore(&pool_lock, flags);
        if (result != 1)
            return result;
        /* lsf_node_device_actor_current rechecks the original expiry on every
         * iteration; a terminal signal or poisoned owner cannot renew it. */
        cond_resched();
    }
}
