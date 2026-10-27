/* SPDX-License-Identifier: GPL-2.0-only */
/* Exact selected MSI-X BAR, using the existing Root/PAT/PTE/view owner. */
#include <net/lsf_stream_q35_msi_private.h>
#include <net/lsf_stream_constructor_mmio_private.h>

void __iomem *lsf_q35_msix_map(struct pci_dev *dev, unsigned int nr_entries)
{
    resource_size_t physical;
    u32 table;
    unsigned long flags;
    u8 bir;
    if (!nr_entries || nr_entries > PCI_MSIX_FLAGS_QSIZE + 1u ||
        lsf_factory_stream_mmio_pci_selected(dev) != 1) return NULL;
    pci_read_config_dword(dev, dev->msix_cap + PCI_MSIX_TABLE, &table);
    bir = (u8)(table & PCI_MSIX_TABLE_BIR);
    if (bir >= PCI_STD_NUM_BARS) return NULL;
    flags = pci_resource_flags(dev, bir);
    if (!(flags & IORESOURCE_MEM) || (flags & IORESOURCE_UNSET) ||
        check_add_overflow(pci_resource_start(dev, bir),
            (resource_size_t)(table & PCI_MSIX_TABLE_OFFSET), &physical)) return NULL;
    /* This does not access an MSI-X register. Reserve/map the true table
     * BEFORE its hardware enable, then preserve the native register sequence. */
    return lsf_prepaid_stream_ioremap(dev, physical, nr_entries * PCI_MSIX_ENTRY_SIZE);
}

static int lsf_q35_msix_interrupts_closed(struct pci_dev *dev,
    struct msix_entry *entries, int nvec, struct irq_affinity *affd)
{
    /* Actual virtio_find_vqs selects NULL affinity, no entries array and 2/3
     * vectors. Descriptor, sparse-IRQ/per-CPU and irqaction births are NOT paid
     * by this stage. Refuse BEFORE all of them, without a legacy fallback. */
    if (entries || affd || (nvec != 2 && nvec != 3)) return -EOPNOTSUPP;
    /* Original failure cleanup: empty descriptors/domain first, actual table
     * unmap and alias clear next. No pool lock spans the native cleanup. */
    msi_lock_descs(&dev->dev);
    if (!lsf_q35_msi_empty_locked(&dev->dev)) {
        msi_unlock_descs(&dev->dev);
        lsf_factory_stream_constructor_retain_unknown(); return -EOPNOTSUPP;
    }
    pci_free_msi_irqs(dev);
    msi_unlock_descs(&dev->dev);
    return -EOPNOTSUPP;
}

/* Native capability-init clone: closed edits, original register/unwind order. */
static int lsf_q35_msix_capability_init(struct pci_dev *dev, struct msix_entry *entries,
				int nvec, struct irq_affinity *affd)
{
	int ret, tsize;
	u16 control;
	void __iomem *paid;
	unsigned int prepaid_tsize;

	if (entries || affd || (nvec != 2 && nvec != 3) || dev->msix_base ||
	    !lsf_q35_x86_parent_known(dev_get_msi_domain(&dev->dev)) ||
	    lsf_q35_msi_current(&dev->dev) != 1) return -EOPNOTSUPP;
	pci_read_config_word(dev, dev->msix_cap + PCI_MSIX_FLAGS, &control);
	prepaid_tsize = msix_table_size(control);
	paid = lsf_q35_msix_map(dev, prepaid_tsize);
	if (!paid) return -ENOMEM;

	/*
	 * Some devices require MSI-X to be enabled before the MSI-X
	 * registers can be accessed.  Mask all the vectors to prevent
	 * interrupts coming in before they're fully set up.
	 */
	pci_msix_clear_and_set_ctrl(dev, 0, PCI_MSIX_FLAGS_MASKALL |
				    PCI_MSIX_FLAGS_ENABLE);

	/* Mark it enabled so setup functions can query it */
	dev->msix_enabled = 1;

	pci_read_config_word(dev, dev->msix_cap + PCI_MSIX_FLAGS, &control);
	/* Request & Map MSI-X table region */
	tsize = msix_table_size(control);
	if (tsize != prepaid_tsize) { ret = -EOPNOTSUPP; goto out_disable; }
	dev->msix_base = paid;
	paid = NULL;
	if (!dev->msix_base) {
		ret = -ENOMEM;
		goto out_disable;
	}

	ret = lsf_q35_msix_interrupts_closed(dev, entries, nvec, affd);
	if (ret)
		goto out_disable;

	/* Disable INTX */
	pci_intx_for_msi(dev, 0);

	if (!pci_msi_domain_supports(dev, MSI_FLAG_NO_MASK, DENY_LEGACY)) {
		/*
		 * Ensure that all table entries are masked to prevent
		 * stale entries from firing in a crash kernel.
		 *
		 * Done late to deal with a broken Marvell NVME device
		 * which takes the MSI-X mask bits into account even
		 * when MSI-X is disabled, which prevents MSI delivery.
		 */
		msix_mask_all(dev->msix_base, tsize);
	}
	pci_msix_clear_and_set_ctrl(dev, PCI_MSIX_FLAGS_MASKALL, 0);

	pcibios_free_irq(dev);
	return 0;

out_disable:
	dev->msix_enabled = 0;
	pci_msix_clear_and_set_ctrl(dev, PCI_MSIX_FLAGS_MASKALL | PCI_MSIX_FLAGS_ENABLE, 0);
	if (paid) iounmap(paid);

	return ret;
}
