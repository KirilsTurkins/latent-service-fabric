/* SPDX-License-Identifier: GPL-2.0-only */
/* Included after native MSI definitions; no irq_desc or vector is allocated. */
#include <net/lsf_stream_msi_descriptor_private.h>
#include <net/lsf_stream_q35_msi_private.h>

int lsf_msi_desc_geometry(unsigned long *bytes, unsigned long *alignment)
{
    if (!bytes || !alignment || __alignof__(struct msi_desc) > 64u) return -EOPNOTSUPP;
    *bytes = kmalloc_size_roundup(sizeof(struct msi_desc));
    *alignment = __alignof__(struct msi_desc);
    return *bytes >= sizeof(struct msi_desc) ? 0 : -EOPNOTSUPP;
}

unsigned long lsf_msi_store_offset(void)
{
    return offsetof(struct msi_device_data, __domains[MSI_DEFAULT_DOMAIN].store);
}

int lsf_msi_descriptor_prepare(struct pci_dev *dev, unsigned int nvec,
    struct lsf_msi_store_plan *plan)
{
    int result = -EOPNOTSUPP;
    unsigned int role;
    struct irq_domain *domain;
    struct msi_domain_info *info;
    if (!dev || !plan || (nvec != 2u && nvec != 3u) ||
        lsf_prepaid_stream_msi_resource_classify(&dev->dev, dev->dev.msi.data, &role) != 1 ||
        role != LSF_STREAM_MSI_CONTEXT) return result;
    msi_lock_descs(&dev->dev);
    domain = msi_get_device_domain(&dev->dev, MSI_DEFAULT_DOMAIN);
    if (!lsf_q35_msi_empty_locked(&dev->dev) ||
        !lsf_q35_msi_domain_known(&dev->dev, domain)) goto out;
    info = domain->host_data;
    if (info && info->ops &&
        !info->ops->domain_free_irqs && !info->ops->msi_post_free &&
        (info->flags & MSI_FLAG_FREE_MSI_DESCS))
        result = lsf_msi_store_prepare(&dev->dev, nvec, plan);
out:
    msi_unlock_descs(&dev->dev);
    return result;
}

struct msi_desc *lsf_msi_descriptor_allocate(struct device *dev, unsigned int domid,
    const struct msi_desc *init)
{
    struct msi_desc *desc;
    struct xarray *xa;
    if (domid != MSI_DEFAULT_DOMAIN || !init || init->affinity || init->nvec_used != 1u ||
        init->msi_index >= 3u || !init->pci.msi_attrib.is_msix || init->irq ||
        init->pci.msi_attrib.is_virtual || !init->pci.msi_attrib.is_64 ||
        init->pci.msi_attrib.default_irq != to_pci_dev(dev)->irq ||
        init->pci.mask_base != to_pci_dev(dev)->msix_base ||
        !lsf_q35_msi_domain_known(dev, msi_get_device_domain(dev, domid))) return NULL;
    lockdep_assert_held(&dev->msi.data->mutex);
    xa = &dev->msi.data->__domains[domid].store;
    if (xa_load(xa, init->msi_index)) return NULL;
    /* Exact native increasing explicit indices; never MSI_ANY_INDEX/affinity. */
    if (init->msi_index && !xa_load(xa, init->msi_index - 1u)) return NULL;
    desc = lsf_msi_store_take(dev, init->msi_index);
    if (!desc) return NULL;
    desc->dev = dev;
    desc->nvec_used = init->nvec_used;
    desc->msi_index = init->msi_index;
    /* Native type-specific initialization and actual MMIO-derived mask state. */
    desc->pci = init->pci;
    return desc;
}

int lsf_msi_descriptor_insert_allowed(struct device *dev, const struct msi_desc *desc,
    unsigned int domid, unsigned int index)
{
    struct device *actual;
    if (domid != MSI_DEFAULT_DOMAIN || index >= 3u ||
        lsf_msi_store_classify(desc, index, &actual) != 1 || actual != dev) return 0;
    return desc->dev == dev && desc->msi_index == index && desc->nvec_used == 1u &&
        !desc->affinity && !desc->irq && desc->pci.msi_attrib.is_msix &&
        lsf_q35_msi_domain_known(dev, msi_get_device_domain(dev, domid));
}

int lsf_msi_xa_insert_allowed(const struct xarray *xa, unsigned long index, const void *entry)
{
    const struct msi_desc *desc = entry;
    struct device *actual;
    if (index >= 3u || lsf_msi_store_classify(entry, (unsigned int)index, &actual) != 1)
        return 0;
    if (xa != &actual->msi.data->__domains[MSI_DEFAULT_DOMAIN].store) return 0;
    lockdep_assert_held(&actual->msi.data->mutex);
    return lsf_msi_descriptor_insert_allowed(actual, desc, MSI_DEFAULT_DOMAIN, (unsigned int)index);
}

int lsf_msi_descriptor_free(struct msi_desc *desc)
{
    struct device *actual;
    int selected = lsf_msi_store_classify(desc, LSF_MSI_ANY_DESC_ROLE, &actual);
    if (!selected) return 0;
    if (selected < 0 || desc->dev != actual || desc->affinity || desc->irq ||
        desc->nvec_used != 1u || desc->msi_index >= 3u) goto retain;
    /* Preserve native free order. The authenticated affinity is actually NULL;
     * the complete descriptor extent retires only at native kfree(desc). */
    kfree(desc->affinity);
    return lsf_msi_store_retire(desc, desc->msi_index);
retain:
    lsf_factory_stream_constructor_retain_unknown();
    return -EOPNOTSUPP;
}

int lsf_msi_descriptor_setup(struct pci_dev *dev, int nvec, int type)
{
    struct xarray *xa;
    struct msi_desc *desc;
    unsigned long index;
    unsigned int count = 0;
    if (type != PCI_CAP_ID_MSIX || (nvec != 2 && nvec != 3) ||
        !lsf_q35_msi_domain_known(&dev->dev,
            msi_get_device_domain(&dev->dev, MSI_DEFAULT_DOMAIN))) return -EOPNOTSUPP;
    /* pci_msi_setup_msi_irqs is called with the native descriptor mutex held.
     * Do not recursively acquire it, call a domain allocator, or reserve a
     * vector just to discover an unsupported per-CPU/Maple/sysfs effect. */
    lockdep_assert_held(&dev->dev.msi.data->mutex);
    xa = &dev->dev.msi.data->__domains[MSI_DEFAULT_DOMAIN].store;
    xa_for_each(xa, index, desc) {
        if (index != count || !lsf_msi_descriptor_insert_allowed(&dev->dev, desc,
            MSI_DEFAULT_DOMAIN, (unsigned int)index)) goto retain;
        ++count;
    }
    if (count != (unsigned int)nvec) goto retain;
    return -EOPNOTSUPP; /* Exact closed boundary BEFORE irq_domain_alloc_descs. */
retain:
    lsf_factory_stream_constructor_retain_unknown();
    return -EOPNOTSUPP;
}
