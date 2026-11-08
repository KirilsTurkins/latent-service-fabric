/* SPDX-License-Identifier: GPL-2.0-only */
/* One selected, guard-verified unimplemented BAR word; not general BAR sizing. */
#ifndef CONFIG_LSF_STREAM_NODE_PCI_BAR3
#error "BAR3 custody requires its distinct qualification image"
#endif

extern int lsf_node_bar3_prepare(struct pci_dev *pci, u32 saved);
extern int lsf_node_bar3_forward(struct pci_dev *pci);
extern int lsf_node_bar3_claim_restore(struct pci_dev *pci, u32 *saved);
extern int lsf_node_bar3_restore_written(struct pci_dev *pci, u32 saved);
extern int lsf_node_bar3_observed(struct pci_dev *pci, u32 value);

/* The read is made immediately before this transition. Once published, a
 * failed config write is treated as if the mutation may have reached QEMU. */
int lsf_node_bar3_prepare(struct pci_dev *pci, u32 saved)
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
        node->prefix_intx_saved == LSF_Q35_INTX_ORIGINAL_COMMAND &&
        node->prefix_bar3_phase == LSF_NODE_BAR3_EMPTY &&
        !node->prefix_bar3_saved && !saved) {
        node->prefix_bar3_saved = saved;
        node->prefix_bar3_phase = LSF_NODE_BAR3_WRITE_MAY_HAVE_RUN;
        result = 1;
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_bar3_forward(struct pci_dev *pci)
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
        node->prefix_intx_saved == LSF_Q35_INTX_ORIGINAL_COMMAND &&
        !node->prefix_bar3_saved &&
        (node->prefix_bar3_phase == LSF_NODE_BAR3_WRITE_MAY_HAVE_RUN ||
         node->prefix_bar3_phase == LSF_NODE_BAR3_RESTORE_WRITTEN))
        result = 1;
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Restore does not extend the original deadline. Only the original task and
 * still-live original records can claim this exact saved word, once. */
int lsf_node_bar3_claim_restore(struct pci_dev *pci, u32 *saved)
{
    struct lsf_node_parent *node;
    unsigned long flags;
    int result = 0;

    if (!saved || lsf_factory_device_pci_owned(pci, sizeof(*pci)) != 1)
        return 0;
    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_intx_bound_locked(pci);
    if (node && node->prefix_intx_phase == LSF_NODE_INTX_RESTORE_WRITTEN &&
        node->prefix_intx_saved == LSF_Q35_INTX_ORIGINAL_COMMAND &&
        node->prefix_bar3_phase == LSF_NODE_BAR3_WRITE_MAY_HAVE_RUN &&
        !node->prefix_bar3_saved) {
        *saved = node->prefix_bar3_saved;
        node->prefix_bar3_phase = LSF_NODE_BAR3_RESTORE_CLAIMED;
        result = 1;
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_bar3_restore_written(struct pci_dev *pci, u32 saved)
{
    struct lsf_node_parent *node;
    unsigned long flags;
    int result = 0;

    if (lsf_factory_device_pci_owned(pci, sizeof(*pci)) != 1)
        return 0;
    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_intx_bound_locked(pci);
    if (node && node->prefix_intx_phase == LSF_NODE_INTX_RESTORE_WRITTEN &&
        node->prefix_bar3_phase == LSF_NODE_BAR3_RESTORE_CLAIMED &&
        !saved && node->prefix_bar3_saved == saved) {
        node->prefix_bar3_phase = LSF_NODE_BAR3_RESTORE_WRITTEN;
        result = 1;
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_bar3_observed(struct pci_dev *pci, u32 value)
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
        node->prefix_bar3_phase == LSF_NODE_BAR3_RESTORE_WRITTEN &&
        !value && node->prefix_bar3_saved == value) {
        node->prefix_bar3_phase = LSF_NODE_BAR3_OBSERVED;
        result = 1;
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
