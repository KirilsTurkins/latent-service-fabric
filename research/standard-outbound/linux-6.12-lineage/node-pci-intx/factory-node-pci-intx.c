/* SPDX-License-Identifier: GPL-2.0-only */
/* Review-only, default-off q35 PCI INTx qualification custody.
 * This does not install a consumer, fund shared IRQ state, or prove retirement. */
#ifndef CONFIG_LSF_STREAM_NODE_PCI_INTX
#error "PCI INTx custody requires its distinct qualification image"
#endif

/* The original syscall retains its file, Node actor, device Root, both exact
 * live prepaid records and constructor task. This helper never uses an input
 * address until the existing whole-object classifier has accepted it. */
static struct lsf_node_parent *lsf_node_intx_bound_locked(struct pci_dev *pci)
{
    struct lsf_node_parent *node;
    struct lsf_prepaid_view *pci_record, *fw_record;
    struct lsf_factory_device_firmware *owned;
    struct lsf_prepaid_context *context;

    lockdep_assert_held(&pool_lock);
    node = lsf_node_prefix_parent_locked();
    if (!node || !current->nsproxy || !factory.device ||
        factory.pool.poisoned || factory.pool.stopped || READ_ONCE(factory.uncertain) ||
        node->state != LSF_NODE_ATTACHED_UNQUALIFIED || !node->expires_ns ||
        node->prefix_attempted != 1u || node->prefix_active != 1u ||
        node->prefix_task != current || node->prefix_birth != 1u ||
        node->prefix_setup != 1u || node->prefix_pending || node->prefix_returned ||
        node->prefix_fixup != 1u || !node->prefix_fixup_count ||
        node->prefix_fixup_count > 512u ||
        node->mm != current->mm || node->tgid != task_tgid(current) ||
        node->cred != current_cred() || node->net != current->nsproxy->net_ns ||
        !factory.device->constructor_active || factory.device->constructor_task != current ||
        !lsf_node_setup_records_locked(node, &pci_record, &fw_record, &owned) ||
        pci_record->phase != LSF_PREPAID_LIVE ||
        pci_record->deferred != LSF_PREPAID_PUBLISHED ||
        fw_record->phase != LSF_PREPAID_LIVE ||
        fw_record->deferred != LSF_PREPAID_PUBLISHED ||
        owned->pci_address != pci || owned->retirement || owned->queued ||
        owned->putting || owned->returned || owned->revoked || owned->put_error)
        return NULL;
    context = &factory.pool.contexts[node->owner.slot];
    if (context->poisoned || context->closed || node->capacity.device_closed ||
        context->live != node->prefix_peak_live || context->cursor != node->prefix_peak_cursor ||
        !pci->bus || !lsf_factory_device_selected(pci_domain_nr(pci->bus),
            pci->bus->number, pci->devfn) ||
        pci->vendor != LSF_DEVICE_PCI_VENDOR || pci->device != LSF_DEVICE_PCI_DEVICE ||
        pci->hdr_type != node->prefix_header || pci->class != node->prefix_class ||
        pci->cfg_size != node->prefix_config_size || pci_dev_is_added(pci))
        return NULL;
    return node;
}

static void lsf_node_intx_poison_locked(void)
{
    lockdep_assert_held(&pool_lock);
    factory.pool.poisoned = 1u;
    WRITE_ONCE(factory.uncertain, 1u);
}

void lsf_node_intx_fault(void)
{
    unsigned long flags;
    spin_lock_irqsave(&pool_lock, flags);
    lsf_node_intx_poison_locked();
    spin_unlock_irqrestore(&pool_lock, flags);
}

int lsf_node_intx_begin(struct pci_dev *pci)
{
    struct lsf_node_parent *node;
    unsigned long flags;
    int result = 0;

    if (lsf_factory_device_pci_owned(pci, sizeof(*pci)) != 1)
        goto fault;
    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_intx_bound_locked(pci);
    if (!node || !lsf_node_constructor_actor_current() ||
        node->prefix_intx_phase != LSF_NODE_INTX_EMPTY ||
        node->prefix_intx_saved || node->prefix_intx_pin || node->prefix_intx_line)
        goto poison;
    node->prefix_intx_phase = LSF_NODE_INTX_ARMED;
    result = 1;
    goto out;
poison:
    lsf_node_intx_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
fault:
    lsf_node_intx_fault();
    return 0;
}

/* Every forward config access reuses the original expiry-enforcing actor. */
int lsf_node_intx_forward(struct pci_dev *pci)
{
    struct lsf_node_parent *node;
    unsigned long flags;
    int result = 0;

    if (lsf_factory_device_pci_owned(pci, sizeof(*pci)) != 1)
        return 0;
    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_intx_bound_locked(pci);
    if (node && lsf_node_constructor_actor_current() &&
        (node->prefix_intx_phase == LSF_NODE_INTX_ARMED ||
         node->prefix_intx_phase == LSF_NODE_INTX_PREFLIGHTED ||
         node->prefix_intx_phase == LSF_NODE_INTX_TOGGLE_MAY_HAVE_RUN ||
         node->prefix_intx_phase == LSF_NODE_INTX_RESTORE_WRITTEN))
        result = 1;
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_intx_preflight(struct pci_dev *pci, u16 original)
{
    struct lsf_node_parent *node;
    unsigned long flags;
    int result = 0;

    if (lsf_factory_device_pci_owned(pci, sizeof(*pci)) != 1)
        return 0;
    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_intx_bound_locked(pci);
    if (node && lsf_node_constructor_actor_current() &&
        node->prefix_intx_phase == LSF_NODE_INTX_ARMED &&
        !(original & PCI_COMMAND_INTX_DISABLE) && (original & PCI_COMMAND_MASTER)) {
        node->prefix_intx_saved = original;
        node->prefix_intx_phase = LSF_NODE_INTX_PREFLIGHTED;
        result = 1;
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Publish the original word and mark possible mutation BEFORE the real write.
 * An error from that write is not proof it failed to reach the device. */
int lsf_node_intx_prepare_toggle(struct pci_dev *pci, u16 original)
{
    struct lsf_node_parent *node;
    unsigned long flags;
    int result = 0;

    if (lsf_factory_device_pci_owned(pci, sizeof(*pci)) != 1)
        return 0;
    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_intx_bound_locked(pci);
    if (node && lsf_node_constructor_actor_current() &&
        node->prefix_intx_phase == LSF_NODE_INTX_PREFLIGHTED &&
        node->prefix_intx_saved == original) {
        node->prefix_intx_phase = LSF_NODE_INTX_TOGGLE_MAY_HAVE_RUN;
        result = 1;
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Single restore claim: only the original actor, exact still-live records and
 * exact saved word may restore. Deliberately does not renew or test expiry;
 * it grants no other config write and cannot be used for forward progress. */
int lsf_node_intx_claim_restore(struct pci_dev *pci, u16 original)
{
    struct lsf_node_parent *node;
    unsigned long flags;
    int result = 0;

    if (lsf_factory_device_pci_owned(pci, sizeof(*pci)) != 1)
        return 0;
    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_intx_bound_locked(pci);
    if (node && node->prefix_intx_phase == LSF_NODE_INTX_TOGGLE_MAY_HAVE_RUN &&
        node->prefix_intx_saved == original) {
        node->prefix_intx_phase = LSF_NODE_INTX_RESTORE_CLAIMED;
        result = 1;
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_intx_restore_written(struct pci_dev *pci, u16 original)
{
    struct lsf_node_parent *node;
    unsigned long flags;
    int result = 0;

    if (lsf_factory_device_pci_owned(pci, sizeof(*pci)) != 1)
        return 0;
    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_intx_bound_locked(pci);
    if (node && node->prefix_intx_phase == LSF_NODE_INTX_RESTORE_CLAIMED &&
        node->prefix_intx_saved == original) {
        node->prefix_intx_phase = LSF_NODE_INTX_RESTORE_WRITTEN;
        result = 1;
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_intx_observed(struct pci_dev *pci, u16 restored, u8 pin, u8 line)
{
    struct lsf_node_parent *node;
    unsigned long flags;
    int result = 0;

    if (lsf_factory_device_pci_owned(pci, sizeof(*pci)) != 1)
        return 0;
    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_intx_bound_locked(pci);
    if (node && lsf_node_constructor_actor_current() &&
        node->prefix_intx_phase == LSF_NODE_INTX_RESTORE_WRITTEN &&
        node->prefix_intx_saved == restored && pin > 0u && pin <= 4u &&
        pci->pin == pin && pci->irq == line) {
        node->prefix_intx_pin = pin;
        node->prefix_intx_line = line;
        node->prefix_intx_phase = LSF_NODE_INTX_OBSERVED;
        result = 1;
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
