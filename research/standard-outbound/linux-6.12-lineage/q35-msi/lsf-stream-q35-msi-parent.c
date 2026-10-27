/* SPDX-License-Identifier: GPL-2.0-only */
/* No IOMMU/remapping fallback: require the ACTUAL native x86 vector parent. */
#include <net/lsf_stream_q35_msi_private.h>
int lsf_q35_x86_parent_known(const struct irq_domain *parent)
{
#if defined(CONFIG_IRQ_REMAP) || defined(CONFIG_GENERIC_IRQ_DEBUGFS) || defined(CONFIG_X86_X2APIC)
    return 0;
#else
    return parent && parent == x86_pci_msi_default_domain &&
        lsf_q35_x86_vector_known(parent) && parent->msi_parent_ops == &x86_vector_msi_parent_ops &&
        parent->bus_token == DOMAIN_BUS_ANY && !parent->parent && parent->root == parent &&
        (parent->flags & IRQ_DOMAIN_FLAG_MSI_PARENT) && !parent->exit &&
        !parent->msi_parent_ops->prefix;
#endif
}
