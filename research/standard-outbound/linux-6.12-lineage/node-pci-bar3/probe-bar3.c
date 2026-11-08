/* SPDX-License-Identifier: GPL-2.0-only */
/* This qualification-only sequence requires the separate QEMU BAR3 guard.
 * It does not replace __pci_read_base or authorize any implemented BAR. */
#ifdef CONFIG_LSF_STREAM_NODE_PCI_BAR3
extern int lsf_node_bar3_prepare(struct pci_dev *pci, u32 saved);
extern int lsf_node_bar3_forward(struct pci_dev *pci);
extern int lsf_node_bar3_claim_restore(struct pci_dev *pci, u32 *saved);
extern int lsf_node_bar3_restore_written(struct pci_dev *pci, u32 saved);
extern int lsf_node_bar3_observed(struct pci_dev *pci, u32 value);

static int lsf_pci_bar3_checked(struct pci_dev *dev)
{
    u32 original, value, saved;
    int error, good = 1;

    if (!lsf_node_intx_forward(dev) ||
        pci_read_config_dword(dev, PCI_BASE_ADDRESS_3, &original) || original ||
        !lsf_node_bar3_prepare(dev, original))
        goto fault;

    /* From here the original Node owns a possible write, even if the config
     * API reports an error or the original deadline expires. */
    error = pci_write_config_dword(dev, PCI_BASE_ADDRESS_3, ~0u);
    if (error || !lsf_node_bar3_forward(dev) ||
        pci_read_config_dword(dev, PCI_BASE_ADDRESS_3, &value) || value)
        good = 0;

    if (!lsf_node_bar3_claim_restore(dev, &saved))
        goto fault;
    error = pci_write_config_dword(dev, PCI_BASE_ADDRESS_3, saved);
    if (error || !lsf_node_bar3_restore_written(dev, saved))
        goto fault;
    if (!good || !lsf_node_bar3_forward(dev) ||
        pci_read_config_dword(dev, PCI_BASE_ADDRESS_3, &value) ||
        value != saved || !lsf_node_bar3_observed(dev, value))
        goto fault;
    return 1;
fault:
    lsf_node_intx_fault();
    return 0;
}
#endif
