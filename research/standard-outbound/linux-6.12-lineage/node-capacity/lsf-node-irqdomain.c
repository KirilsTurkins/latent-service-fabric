/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in actual kernel/irq/irqdomain.c. */
#include <net/lsf_node_capacity_private.h>
#include <asm/hw_irq.h>
/* Exact global definition is in authenticated native vector.c. */
extern struct irq_domain *x86_vector_domain;
int lsf_node_irqdomain_layout(struct lsf_node_capacity_extent *out)
{
    if (!out || sizeof(struct irq_data) > PAGE_SIZE || __alignof__(struct irq_data) > PAGE_SIZE)
        return -EOPNOTSUPP;
    out[LSF_NODE_IRQ_PARENT_DATA] = (struct lsf_node_capacity_extent){
        sizeof(struct irq_data), __alignof__(struct irq_data)};
    return 0;
}

static int lsf_node_parent_data(struct irq_domain *domain, struct irq_data *child,
    struct irq_data **result)
{
    struct lsf_node_capacity *owner, *actual;
    struct irq_domain *source;
    struct irq_desc *desc;
    unsigned int index;
    int selected, known;

    *result = NULL;
    selected = lsf_node_irq_current_owner(&owner);
    if (selected < 0)
        return selected;
    /* Native caller's child comes from the actual sparse descriptor. Never
     * gain Node authority from irq-number equality or copied common fields. */
    desc = container_of(child, struct irq_desc, irq_data);
    known = lsf_node_irq_aux_index(desc, LSF_NODE_IRQ_DESC, &actual, &index);
    if (known < 0)
        return known;
    if (!known) {
        /* A deeper Node-owned parent is not an ordinary allocation origin. */
        known = lsf_node_irq_aux_index(child, LSF_NODE_IRQ_PARENT_DATA, &actual, &index);
        return (selected || known) ? -EOPNOTSUPP : 0;
    }
    if (selected != 1 || actual != owner || child != &desc->irq_data)
        return -EOPNOTSUPP;
    source = lsf_node_irq_current_domain(owner);
    if (!source || child->domain != source || child->parent_data ||
        source->parent != domain || domain != x86_vector_domain || domain->parent)
        return -EOPNOTSUPP;
    *result = lsf_node_irq_aux_take(owner, LSF_NODE_IRQ_PARENT_DATA, desc);
    return *result ? 1 : -ENOMEM;
}

static void lsf_node_parent_data_free(struct irq_data *data)
{
    struct lsf_node_capacity *owner;
    unsigned int index;
    int selected = lsf_node_irq_aux_index(data, LSF_NODE_IRQ_PARENT_DATA, &owner, &index);
    if (selected == 1) {
        /* Native unlink/reset already removed chip-data and parent aliases. */
        if (data->parent_data || data->chip_data) {
            lsf_node_irq_aux_uncertain(data, LSF_NODE_IRQ_PARENT_DATA);
            return;
        }
        lsf_node_irq_aux_retire(data, LSF_NODE_IRQ_PARENT_DATA);
    } else if (!selected) {
        kfree(data);
    }
}

static int lsf_node_refuse_domain_reparent(unsigned int virq)
{
    struct lsf_node_capacity *owner;
    unsigned int index;
    int selected = lsf_node_irq_aux_index(irq_to_desc(virq), LSF_NODE_IRQ_DESC, &owner, &index);
    return selected ? -EOPNOTSUPP : 0;
}
