/* SPDX-License-Identifier: GPL-2.0-only */
/* Qualification-only observation after the original early-fixup dispatcher.
 * No callback may match and the original Node retains both prepaid records. */
#ifndef CONFIG_LSF_STREAM_NODE_PCI_FIXUP
#error "PCI early-fixup observation requires its separate default-off image"
#endif

int lsf_node_fixup_reached(struct pci_dev *pci, unsigned int entries)
{
    struct lsf_node_parent *node;
    struct lsf_prepaid_view *pci_record, *fw_record;
    struct lsf_factory_device_firmware *owned;
    struct lsf_prepaid_context *context;
    unsigned long flags;
    int result = 0;

    /* Classify the whole original PCI view before any field access. */
    if (lsf_factory_device_pci_owned(pci, sizeof(*pci)) != 1)
        goto poison_unlocked;
    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_prefix_parent_locked();
    if (!node || !lsf_node_constructor_actor_current() ||
        node->prefix_birth != 1u || node->prefix_setup != 1u ||
        node->prefix_pending || node->prefix_fixup || node->prefix_fixup_count ||
        !entries || entries > 512u || !factory.device ||
        !factory.device->constructor_active || factory.device->constructor_task != current ||
        !lsf_node_setup_records_locked(node, &pci_record, &fw_record, &owned) ||
        pci_record->phase != LSF_PREPAID_LIVE ||
        pci_record->deferred != LSF_PREPAID_PUBLISHED ||
        fw_record->phase != LSF_PREPAID_LIVE ||
        fw_record->deferred != LSF_PREPAID_PUBLISHED ||
        owned->pci_address != pci || owned->retirement || owned->queued ||
        owned->putting || owned->returned || owned->revoked || owned->put_error ||
        !pci->bus || !lsf_factory_device_selected(pci_domain_nr(pci->bus),
            pci->bus->number, pci->devfn) ||
        pci->vendor != LSF_DEVICE_PCI_VENDOR || pci->device != LSF_DEVICE_PCI_DEVICE ||
        pci->hdr_type != node->prefix_header || pci->class != node->prefix_class ||
        pci->cfg_size != node->prefix_config_size || pci_dev_is_added(pci) ||
        ACPI_COMPANION(&pci->dev) != owned->companion ||
        !!owned->companion != node->prefix_companion)
        goto poison;
    context = &factory.pool.contexts[node->owner.slot];
    if (context->live != node->prefix_peak_live || context->cursor != node->prefix_peak_cursor)
        goto poison;
    node->prefix_fixup_count = entries;
    node->prefix_fixup = 1u;
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
