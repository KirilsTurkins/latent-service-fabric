/* SPDX-License-Identifier: GPL-2.0-only */
/* Included after native irqdomain definitions; actual types and native locks. */
#include <net/lsf_stream_q35_msi_private.h>
#include <linux/msi.h>
static_assert(offsetof(struct irqchip_fwid, fwnode) == 0);

int lsf_q35_msi_geometry(unsigned int role, unsigned long name_bytes,
    unsigned long token_bytes, unsigned long *bytes, unsigned long *alignment)
{
    unsigned long requested;
    if (!bytes || !alignment || !name_bytes || name_bytes > sizeof(((struct msi_domain_template *)0)->name) ||
        token_bytes <= name_bytes || token_bytes > sizeof(((struct msi_domain_template *)0)->name) + 12u)
        return -EOPNOTSUPP;
    switch (role) {
    case LSF_Q35_MSI_TEMPLATE: return lsf_q35_msi_bundle_geometry(bytes, alignment);
    case LSF_Q35_MSI_FWNODE:
        requested = sizeof(struct irqchip_fwid); *alignment = __alignof__(struct irqchip_fwid); break;
    case LSF_Q35_MSI_DOMAIN:
        requested = struct_size((struct irq_domain *)NULL, revmap, 0);
        *alignment = __alignof__(struct irq_domain); break;
    case LSF_Q35_MSI_FWNAME:
    case LSF_Q35_MSI_NAME:
        requested = name_bytes; *alignment = 1; break;
    case LSF_Q35_MSI_TOKEN_NAME:
        requested = token_bytes; *alignment = 1; break;
    default: return -EOPNOTSUPP;
    }
    if (!*alignment || *alignment > 64u) return -EOPNOTSUPP;
    *bytes = kmalloc_size_roundup(requested);
    return *bytes >= requested && *bytes <= ULONG_MAX - 63u ? 0 : -EOPNOTSUPP;
}

struct fwnode_handle *lsf_q35_fwnode(struct device *dev,
    const struct lsf_q35_msi_plan *plan, const char *name)
{
    struct irqchip_fwid *fwid;
    char *copy;
    size_t n = strnlen(name, sizeof(((struct msi_domain_template *)0)->name));
    if (!n || n >= sizeof(((struct msi_domain_template *)0)->name)) return NULL;
    fwid = lsf_q35_msi_take(dev, plan, LSF_Q35_MSI_FWNODE);
    copy = lsf_q35_msi_take(dev, plan, LSF_Q35_MSI_FWNAME);
    if (!fwid || !copy) {
        if (copy) (void)lsf_q35_msi_retire(copy, LSF_Q35_MSI_FWNAME);
        if (fwid) (void)lsf_q35_msi_retire(fwid, LSF_Q35_MSI_FWNODE);
        return NULL;
    }
    memcpy(copy, name, n + 1u);
    fwid->type = IRQCHIP_FWNODE_NAMED;
    fwid->name = copy;
    fwid->pa = NULL;
    fwnode_init(&fwid->fwnode, &irqchip_fwnode_ops);
    return &fwid->fwnode;
}

int lsf_q35_fwnode_free(struct fwnode_handle *fwnode)
{
    struct irqchip_fwid *fwid;
    struct device *dev, *name_dev;
    int owned;
    if (!fwnode) return 0;
    fwid = container_of(fwnode, struct irqchip_fwid, fwnode);
    owned = lsf_q35_msi_classify(fwid, LSF_Q35_MSI_FWNODE, &dev);
    if (owned <= 0) return owned;
    if (fwid->type != IRQCHIP_FWNODE_NAMED || fwid->pa ||
        fwid->fwnode.ops != &irqchip_fwnode_ops ||
        lsf_q35_msi_classify(fwid->name, LSF_Q35_MSI_FWNAME, &name_dev) != 1 || name_dev != dev ||
        lsf_q35_msi_sibling(fwid, LSF_Q35_MSI_FWNODE, LSF_Q35_MSI_FWNAME, 0) != fwid->name)
        return -EOPNOTSUPP;
    /* Same native name-then-envelope free order; the bank is not reused. */
    if (lsf_q35_msi_retire(fwid->name, LSF_Q35_MSI_FWNAME) != 1) return -EOPNOTSUPP;
    return lsf_q35_msi_retire(fwid, LSF_Q35_MSI_FWNODE);
}

struct irq_domain *lsf_q35_domain_create(const struct irq_domain_info *info)
{
    struct irqchip_fwid *fwid;
    struct irq_domain *domain;
    struct device *dev;
    char *name;
    size_t n;
    if (!info || !info->fwnode || info->size || info->direct_max || info->name_suffix ||
        info->init || info->exit || info->dgc_info || info->virq_base || info->hwirq_base ||
        info->hwirq_max != ~0U ||
        info->domain_flags != (IRQ_DOMAIN_FLAG_MSI_DEVICE | IRQ_DOMAIN_FLAG_MSI) ||
        info->bus_token != DOMAIN_BUS_ANY || !lsf_q35_x86_parent_known(info->parent))
        return ERR_PTR(-EOPNOTSUPP);
    fwid = container_of(info->fwnode, struct irqchip_fwid, fwnode);
    if (lsf_q35_msi_classify(fwid, LSF_Q35_MSI_FWNODE, &dev) != 1 ||
        fwid->type != IRQCHIP_FWNODE_NAMED || fwid->fwnode.ops != &irqchip_fwnode_ops ||
        fwid->name != lsf_q35_msi_sibling(fwid, LSF_Q35_MSI_FWNODE, LSF_Q35_MSI_FWNAME, 0) ||
        !lsf_q35_msi_ops_known(info->ops, info->host_data)) return ERR_PTR(-EOPNOTSUPP);
    domain = lsf_q35_msi_sibling(fwid, LSF_Q35_MSI_FWNODE, LSF_Q35_MSI_DOMAIN, 1);
    name = lsf_q35_msi_sibling(fwid, LSF_Q35_MSI_FWNODE, LSF_Q35_MSI_NAME, 1);
    if (!domain || !name) {
        if (name) (void)lsf_q35_msi_retire(name, LSF_Q35_MSI_NAME);
        if (domain) (void)lsf_q35_msi_retire(domain, LSF_Q35_MSI_DOMAIN);
        return ERR_PTR(-ENOMEM);
    }
    n = strnlen(fwid->name, sizeof(((struct msi_domain_template *)0)->name));
    if (!n || n >= sizeof(((struct msi_domain_template *)0)->name)) {
        (void)lsf_q35_msi_retire(name, LSF_Q35_MSI_NAME);
        (void)lsf_q35_msi_retire(domain, LSF_Q35_MSI_DOMAIN);
        return ERR_PTR(-EOPNOTSUPP);
    }
    memcpy(name, fwid->name, n + 1u);
    domain->name = name;
    domain->flags |= IRQ_DOMAIN_NAME_ALLOCATED;
    domain->fwnode = fwnode_handle_get(info->fwnode);
    fwnode_dev_initialized(domain->fwnode, true);
    INIT_RADIX_TREE(&domain->revmap_tree, GFP_KERNEL);
    domain->ops = info->ops;
    domain->host_data = info->host_data;
    domain->bus_token = info->bus_token;
    domain->hwirq_max = info->hwirq_max;
    domain->revmap_size = info->size;
    mutex_init(&domain->mutex);
    domain->root = domain;
    irq_domain_check_hierarchy(domain);
    return domain;
}

int lsf_q35_domain_bus_token(struct irq_domain *domain, unsigned int token)
{
    struct device *dev;
    char *name, *old;
    int owned = lsf_q35_msi_classify(domain, LSF_Q35_MSI_DOMAIN, &dev);
    if (owned <= 0) return owned;
    if (token != DOMAIN_BUS_PCI_DEVICE_MSIX || !lsf_q35_x86_parent_known(domain->parent))
        return -EOPNOTSUPP;
    if (domain->bus_token == token) return 1;
    mutex_lock(&irq_domain_mutex);
    if (domain->bus_token != DOMAIN_BUS_ANY ||
        domain->name != lsf_q35_msi_sibling(domain, LSF_Q35_MSI_DOMAIN, LSF_Q35_MSI_NAME, 0) ||
        strnlen(domain->name, sizeof(((struct msi_domain_template *)0)->name)) >=
            sizeof(((struct msi_domain_template *)0)->name)) {
        mutex_unlock(&irq_domain_mutex); return -EOPNOTSUPP;
    }
    domain->bus_token = token;
    name = lsf_q35_msi_sibling(domain, LSF_Q35_MSI_DOMAIN, LSF_Q35_MSI_TOKEN_NAME, 1);
    if (!name) { mutex_unlock(&irq_domain_mutex); return -EOPNOTSUPP; }
    snprintf(name, sizeof(((struct msi_domain_template *)0)->name) + 12u, "%s-%d", domain->name, token);
    old = (char *)domain->name;
    domain->name = name;
    domain->flags |= IRQ_DOMAIN_NAME_ALLOCATED;
    if (lsf_q35_msi_retire(old, LSF_Q35_MSI_NAME) != 1) {
        mutex_unlock(&irq_domain_mutex); return -EOPNOTSUPP;
    }
    mutex_unlock(&irq_domain_mutex);
    return 1;
}

int lsf_q35_domain_remove_allowed(const struct irq_domain *domain)
{
    struct device *dev;
    int owned = lsf_q35_msi_classify(domain, LSF_Q35_MSI_DOMAIN, &dev);
    if (owned <= 0) return owned;
    return !domain->exit && !domain->mapcount && !domain->revmap_size &&
        radix_tree_empty(&domain->revmap_tree) && !domain->gc &&
        !(domain->flags & IRQ_DOMAIN_FLAG_DESTROY_GC) &&
        lsf_q35_x86_parent_known(domain->parent) && lsf_q35_msi_domain_known(dev, domain) ? 1 : -EOPNOTSUPP;
}

int lsf_q35_domain_links_known(const struct irq_domain *domain)
{
    struct device *dev;
    const struct msi_domain_template *bundle;
    const struct irqchip_fwid *fwid;
    const char *name;
    unsigned int role;
    char token[sizeof(bundle->name) + 12u] = {};
    if (lsf_q35_msi_classify(domain, LSF_Q35_MSI_DOMAIN, &dev) != 1) return 0;
    bundle = lsf_q35_msi_sibling(domain, LSF_Q35_MSI_DOMAIN, LSF_Q35_MSI_TEMPLATE, 0);
    fwid = lsf_q35_msi_sibling(domain, LSF_Q35_MSI_DOMAIN, LSF_Q35_MSI_FWNODE, 0);
    name = lsf_q35_msi_sibling(domain, LSF_Q35_MSI_DOMAIN, LSF_Q35_MSI_FWNAME, 0);
    if (!bundle || !fwid || !name || domain->fwnode != &fwid->fwnode ||
        fwid->type != IRQCHIP_FWNODE_NAMED || fwid->pa || fwid->name != name ||
        fwid->fwnode.ops != &irqchip_fwnode_ops ||
        strnlen(bundle->name, sizeof(bundle->name)) >= sizeof(bundle->name) ||
        strncmp(name, bundle->name, sizeof(bundle->name))) return 0;
    if (domain->bus_token == DOMAIN_BUS_ANY) role = LSF_Q35_MSI_NAME;
    else if (domain->bus_token == DOMAIN_BUS_PCI_DEVICE_MSIX) role = LSF_Q35_MSI_TOKEN_NAME;
    else return 0;
    name = lsf_q35_msi_sibling(domain, LSF_Q35_MSI_DOMAIN, role, 0);
    if (!name || domain->name != name) return 0;
    if (role == LSF_Q35_MSI_NAME) return !strncmp(name, bundle->name, sizeof(bundle->name));
    snprintf(token, sizeof(token), "%s-%d", bundle->name, DOMAIN_BUS_PCI_DEVICE_MSIX);
    return !strncmp(name, token, sizeof(token));
}

int lsf_q35_domain_free(struct irq_domain *domain)
{
    struct device *dev, *name_dev;
    unsigned int role = LSF_Q35_MSI_NAME;
    int owned = lsf_q35_msi_classify(domain, LSF_Q35_MSI_DOMAIN, &dev);
    if (owned <= 0) return owned;
    if (lsf_q35_msi_classify(domain->name, role, &name_dev) != 1) {
        role = LSF_Q35_MSI_TOKEN_NAME;
        if (lsf_q35_msi_classify(domain->name, role, &name_dev) != 1) return -EOPNOTSUPP;
    }
    if (name_dev != dev || domain->name != lsf_q35_msi_sibling(domain, LSF_Q35_MSI_DOMAIN, role, 0))
        return -EOPNOTSUPP;
    fwnode_dev_initialized(domain->fwnode, false);
    fwnode_handle_put(domain->fwnode);
    if (lsf_q35_msi_retire(domain->name, role) != 1) return -EOPNOTSUPP;
    return lsf_q35_msi_retire(domain, LSF_Q35_MSI_DOMAIN);
}

int lsf_q35_domain_remove(struct irq_domain *domain)
{
    int known = lsf_q35_domain_remove_allowed(domain);
    if (known != 1) return known;
    /* Exact native removal order. No pool lock spans native domain operations;
     * the selected configuration has no generic IRQ debugfs allocation. */
    mutex_lock(&irq_domain_mutex);
    debugfs_remove_domain_dir(domain);
    if (!radix_tree_empty(&domain->revmap_tree)) {
        mutex_unlock(&irq_domain_mutex); return -EOPNOTSUPP;
    }
    list_del(&domain->link);
    if (unlikely(irq_default_domain == domain)) irq_set_default_host(NULL);
    mutex_unlock(&irq_domain_mutex);
    pr_debug("Removed domain %s\n", domain->name);
    return lsf_q35_domain_free(domain);
}
