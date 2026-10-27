/* SPDX-License-Identifier: GPL-2.0-only */
/* Included after native MSI definitions. Only the actual PCI-MSIX template. */
#include <net/lsf_stream_q35_msi_private.h>

int lsf_q35_msi_bundle_geometry(unsigned long *bytes, unsigned long *alignment)
{
    if (!bytes || !alignment || __alignof__(struct msi_domain_template) > 64u)
        return -EOPNOTSUPP;
    *bytes = kmalloc_size_roundup(sizeof(struct msi_domain_template));
    *alignment = __alignof__(struct msi_domain_template);
    return *bytes >= sizeof(struct msi_domain_template) ? 0 : -EOPNOTSUPP;
}

int lsf_q35_msi_ops_known(const struct irq_domain_ops *ops, const void *data)
{
    const struct msi_domain_info *info = data;
    const struct msi_domain_template *bundle;
    struct device *dev;
    if (!info || ops != &msi_domain_ops) return 0;
    bundle = container_of(info, struct msi_domain_template, info);
    return lsf_q35_msi_classify(bundle, LSF_Q35_MSI_TEMPLATE, &dev) == 1 &&
        info->chip == &bundle->chip && info->ops == &bundle->ops &&
        info->bus_token == DOMAIN_BUS_PCI_DEVICE_MSIX && !info->data && !info->chip_data &&
        info->hwsize && info->hwsize <= PCI_MSIX_FLAGS_QSIZE + 1u &&
        !(info->flags & (MSI_FLAG_USE_DEV_FWNODE | MSI_FLAG_PARENT_PM_DEV));
}

int lsf_q35_msi_domain_known(struct device *dev, const struct irq_domain *domain)
{
    struct device *actual;
    const struct msi_domain_template *bundle;
    if (lsf_q35_msi_classify(domain, LSF_Q35_MSI_DOMAIN, &actual) != 1 || actual != dev)
        return 0;
    bundle = lsf_q35_msi_sibling(domain, LSF_Q35_MSI_DOMAIN, LSF_Q35_MSI_TEMPLATE, 0);
    return bundle && domain->host_data == &bundle->info &&
        lsf_q35_msi_ops_known(domain->ops, domain->host_data) &&
        lsf_q35_x86_parent_known(domain->parent) && domain->root == domain->parent->root &&
        (!domain->dev || domain->dev == dev) && !domain->exit && !domain->gc &&
        !domain->mapcount && !domain->revmap_size && radix_tree_empty(&domain->revmap_tree) &&
        lsf_q35_domain_links_known(domain) &&
        (domain->bus_token == DOMAIN_BUS_ANY || domain->bus_token == DOMAIN_BUS_PCI_DEVICE_MSIX) &&
        (domain->flags & (IRQ_DOMAIN_FLAG_MSI | IRQ_DOMAIN_FLAG_MSI_DEVICE)) ==
            (IRQ_DOMAIN_FLAG_MSI | IRQ_DOMAIN_FLAG_MSI_DEVICE) &&
        !(domain->flags & IRQ_DOMAIN_FLAG_DESTROY_GC);
}

int lsf_q35_msi_current(struct device *dev)
{
    struct irq_domain *domain;
    unsigned int role;
    int result;
    if (lsf_prepaid_stream_msi_resource_classify(dev, dev->msi.data, &role) != 1 ||
        role != LSF_STREAM_MSI_CONTEXT) return -EOPNOTSUPP;
    msi_lock_descs(dev);
    domain = msi_get_device_domain(dev, MSI_DEFAULT_DOMAIN);
    result = !domain ? 0 : lsf_q35_msi_domain_known(dev, domain) &&
        domain->bus_token == DOMAIN_BUS_PCI_DEVICE_MSIX ? 1 : -EOPNOTSUPP;
    msi_unlock_descs(dev);
    return result;
}

int lsf_q35_msi_empty_locked(struct device *dev)
{
    struct irq_domain *domain;
    unsigned int role;
    if (lsf_prepaid_stream_msi_resource_classify(dev, dev->msi.data, &role) != 1 ||
        role != LSF_STREAM_MSI_CONTEXT) return 0;
    lockdep_assert_held(&dev->msi.data->mutex);
    domain = msi_get_device_domain(dev, MSI_DEFAULT_DOMAIN);
    return lsf_q35_msi_domain_known(dev, domain) &&
        xa_empty(&dev->msi.data->__domains[MSI_DEFAULT_DOMAIN].store);
}

bool lsf_q35_msi_create(struct device *dev, unsigned int domid,
    const struct msi_domain_template *template, unsigned int hwsize,
    void *domain_data, void *chip_data)
{
    struct irq_domain *domain, *parent = dev->msi.domain;
    struct fwnode_handle *fwnode = NULL;
    struct msi_domain_template *bundle;
    const struct msi_parent_ops *pops;
    struct lsf_q35_msi_plan plan = {};
    unsigned int role;
    char name[sizeof(template->name)] = {}, token_name[sizeof(template->name) + 12u] = {};
    if (domid != MSI_DEFAULT_DOMAIN || domain_data || chip_data || !hwsize ||
        hwsize > PCI_MSIX_FLAGS_QSIZE + 1u || !lsf_q35_msi_template_known(template) ||
        !lsf_q35_x86_parent_known(parent) ||
        lsf_prepaid_stream_msi_resource_classify(dev, dev->msi.data, &role) != 1 ||
        role != LSF_STREAM_MSI_CONTEXT) return false;
    pops = parent->msi_parent_ops;
    snprintf(name, sizeof(name), "%s%s-%s", pops->prefix ? : "", template->chip.name, dev_name(dev));
    snprintf(token_name, sizeof(token_name), "%s-%d", name, template->info.bus_token);
    if (lsf_q35_msi_prepare(dev, strlen(name) + 1u, strlen(token_name) + 1u, &plan) != 1)
        return false;
    bundle = lsf_q35_msi_take(dev, &plan, LSF_Q35_MSI_TEMPLATE);
    if (!bundle) goto discard;
    memcpy(bundle, template, sizeof(*bundle));
    bundle->info.hwsize = hwsize;
    bundle->info.chip = &bundle->chip;
    bundle->info.ops = &bundle->ops;
    bundle->info.data = domain_data;
    bundle->info.chip_data = chip_data;
    memcpy(bundle->name, name, sizeof(name));
    bundle->chip.name = bundle->name;
    fwnode = lsf_q35_fwnode(dev, &plan, bundle->name);
    if (!fwnode) goto free_bundle;
    /* Native context setup is already complete and paid; no new lookup adoption. */
    msi_lock_descs(dev);
    if (WARN_ON_ONCE(msi_get_device_domain(dev, domid))) goto fail;
    if (!pops->init_dev_msi_info(dev, parent, parent, &bundle->info)) goto fail;
    domain = __msi_create_irq_domain(fwnode, &bundle->info, IRQ_DOMAIN_FLAG_MSI_DEVICE, parent);
    if (!domain) goto fail;
    if (!lsf_q35_msi_domain_known(dev, domain) || domain->bus_token != DOMAIN_BUS_PCI_DEVICE_MSIX) {
        /* It may already be on the native domain list: never free aliases or
         * refund on an uncertain partial publication. The SAME bank is kept. */
        lsf_factory_stream_constructor_retain_unknown();
        msi_unlock_descs(dev);
        lsf_q35_msi_discard(dev, &plan);
        return false;
    }
    domain->dev = dev;
    dev->msi.data->__domains[domid].domain = domain;
    msi_unlock_descs(dev);
    lsf_q35_msi_discard(dev, &plan);
    return true;
fail:
    msi_unlock_descs(dev);
    if (lsf_q35_fwnode_free(fwnode) != 1) {
        lsf_factory_stream_constructor_retain_unknown(); goto discard;
    }
free_bundle:
    (void)lsf_q35_msi_retire(bundle, LSF_Q35_MSI_TEMPLATE);
discard:
    lsf_q35_msi_discard(dev, &plan);
    return false;
}

void lsf_q35_msi_remove(struct device *dev, unsigned int domid)
{
    struct irq_domain *domain;
    struct fwnode_handle *fwnode;
    struct msi_domain_template *bundle;
    msi_lock_descs(dev);
    domain = msi_get_device_domain(dev, domid);
    if (!domain) goto unlock;
    if (domid != MSI_DEFAULT_DOMAIN || !lsf_q35_msi_domain_known(dev, domain) ||
        lsf_q35_domain_remove_allowed(domain) != 1 ||
        !xa_empty(&dev->msi.data->__domains[domid].store)) {
        lsf_factory_stream_constructor_retain_unknown(); goto unlock;
    }
    bundle = container_of(domain->host_data, struct msi_domain_template, info);
    fwnode = domain->fwnode;
    dev->msi.data->__domains[domid].domain = NULL;
    if (lsf_q35_domain_remove(domain) != 1 || lsf_q35_fwnode_free(fwnode) != 1) {
        lsf_factory_stream_constructor_retain_unknown(); goto unlock;
    }
    (void)lsf_q35_msi_retire(bundle, LSF_Q35_MSI_TEMPLATE);
unlock:
    msi_unlock_descs(dev);
}
