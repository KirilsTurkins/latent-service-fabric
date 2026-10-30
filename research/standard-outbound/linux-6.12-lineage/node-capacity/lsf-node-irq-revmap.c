/* SPDX-License-Identifier: GPL-2.0-only */
#include <linux/radix-tree.h>
/* Include in actual kernel/irq/irqdomain.c after existing selected helpers.
 * Exact original child + x86 vector roots, never a caller-selected root class.
 */
#include <net/lsf_node_capacity_private.h>
#include <net/lsf_stream_q35_msi_private.h>
extern struct irq_domain *x86_vector_domain;

int lsf_node_radix_root_role(struct lsf_node_capacity *owner,
    struct radix_tree_root *root)
{
    struct irq_domain *source = lsf_node_irq_current_domain(owner);

    if (!source)
        return -EOPNOTSUPP;
    if (source->parent != x86_vector_domain || !x86_vector_domain ||
        x86_vector_domain->parent || source->root != x86_vector_domain ||
        source->revmap_size || x86_vector_domain->revmap_size ||
        irq_domain_is_nomap(source) || irq_domain_is_nomap(x86_vector_domain))
        return -EOPNOTSUPP;
    lockdep_assert_held(&source->root->mutex);
    if (root == &source->revmap_tree)
        return LSF_NODE_RADIX_PRIVATE;
    if (root == &x86_vector_domain->revmap_tree)
        return LSF_NODE_RADIX_SHARED;
    return -EOPNOTSUPP;
}

struct lsf_node_revmap_pair {
    struct radix_tree_root *root;
    struct irq_data *data;
    unsigned long index;
};

int lsf_node_irq_revmap_prepare(struct irq_domain *domain,
    unsigned int virq, unsigned int nr_irqs)
{
    struct lsf_node_revmap_pair pairs[LSF_NODE_CAPACITY_VECTORS * 2u], swap;
    struct lsf_node_capacity *owner, *actual;
    struct irq_domain *source;
    struct irq_desc *desc;
    struct irq_data *child, *parent;
    unsigned int i, j, count = 0, first, index;
    int selected = lsf_node_irq_current_owner(&owner), error;

    if (selected != 1)
        return selected < 0 ? selected : -EOPNOTSUPP;
    source = lsf_node_irq_current_domain(owner);
    if (!source || source != domain || !nr_irqs ||
        nr_irqs > LSF_NODE_CAPACITY_VECTORS || virq > UINT_MAX - (nr_irqs - 1u) ||
        lsf_node_radix_root_role(owner, &source->revmap_tree) != LSF_NODE_RADIX_PRIVATE)
        return -EOPNOTSUPP;
    lockdep_assert_held(&domain->root->mutex);
    /* Authenticate the real descriptor and its saved PCI+domain lineage
     * before reading child fields. Parent allocation has the same slot and
     * original generation, not merely a reused Linux virq number. */
    for (i = 0; i < nr_irqs; ++i) {
        desc = irq_to_desc(virq + i);
        if (!desc || lsf_node_irq_device_owner(desc, &actual) != 1 || actual != owner ||
            lsf_node_irq_aux_index(desc, LSF_NODE_IRQ_DESC, &actual, &first) != 1 ||
            actual != owner)
            return -EOPNOTSUPP;
        child = &desc->irq_data;
        parent = child->parent_data;
        if (!parent || lsf_node_irq_aux_index(parent, LSF_NODE_IRQ_PARENT_DATA,
            &actual, &index) != 1 || actual != owner || index != first)
            return -EOPNOTSUPP;
        if (child->domain != source || parent->domain != x86_vector_domain ||
            parent->parent_data || child->irq != virq + i || parent->irq != child->irq ||
            child->common != parent->common || child->common != &desc->irq_common_data ||
            !child->chip || !parent->chip || !parent->chip_data)
            return -EOPNOTSUPP;
        pairs[count++] = (struct lsf_node_revmap_pair){
            &source->revmap_tree, child, child->hwirq};
        pairs[count++] = (struct lsf_node_revmap_pair){
            &x86_vector_domain->revmap_tree, parent, parent->hwirq};
    }
    /* Each root's highest actual hwirq is prepared first. No later prepare
     * can raise that root's height and invalidate an earlier low-key path. */
    for (i = 0; i < count; ++i) {
        for (j = i + 1; j < count; ++j)
            if (pairs[i].root == pairs[j].root && pairs[i].index == pairs[j].index)
                return -EEXIST;
    }
    for (i = 0; i < count; ++i) {
        for (j = i + 1; j < count; ++j) {
            if (pairs[j].index > pairs[i].index) {
                swap = pairs[i]; pairs[i] = pairs[j]; pairs[j] = swap;
            }
        }
    }
    for (i = 0; i < count; ++i) {
        error = lsf_node_radix_prepare_slot(owner, pairs[i].root, pairs[i].index);
        if (error)
            return error;
    }
    /* No mutation or allocation follows this final proof until the original
     * publication loop, under this SAME mutex. Native insert_entries only
     * stores the non-internal data pointer and updates counts. */
    for (i = 0; i < count; ++i) {
        if (radix_tree_is_internal_node(pairs[i].data) ||
            lsf_node_radix_ready_slot(pairs[i].root, pairs[i].index) != 1)
            return -EIO;
    }
    return 0;
}

/* Called before the prior q35 remove_allowed empty-root guard. It is not
 * called from the allocation failure branch which already holds root mutex. */
int lsf_node_irq_revmap_prune(struct irq_domain *domain)
{
    struct device *device;
    int result = lsf_q35_msi_classify(domain, LSF_Q35_MSI_DOMAIN, &device);

    if (result <= 0)
        return result;
    /* No domain payload read before the exact original typed classifier. */
    if (domain->parent != x86_vector_domain || !x86_vector_domain ||
        domain->root != x86_vector_domain || x86_vector_domain->parent ||
        domain->revmap_size)
        return -EOPNOTSUPP;
    mutex_lock(&domain->root->mutex);
    result = domain->mapcount ? -EOPNOTSUPP :
        lsf_node_radix_prune_private(&domain->revmap_tree);
    if (!result && !radix_tree_empty(&domain->revmap_tree))
        result = -EOPNOTSUPP;
    mutex_unlock(&domain->root->mutex);
    return result;
}
