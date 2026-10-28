/* SPDX-License-Identifier: GPL-2.0-only */
/* Parent composition fragment: include after the existing Node record helpers.
 * IRQ_ACTION is appended role22; no existing role/record/context is renumbered. */

struct irqaction *lsf_node_capacity_action_take(struct lsf_node_capacity *owner,
    struct irq_desc *desc)
{
    struct lsf_node_parent *node;
    struct lsf_node_capacity *actual;
    struct lsf_prepaid_view *record;
    struct irqaction *action = NULL;
    unsigned long flags;
    unsigned int index;

    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_capacity_parent_locked(owner);
    if (!lsf_node_capacity_open_locked(node) || !owner->pcpu_prepared ||
        lsf_node_irq_device_owner_locked(desc, &actual) != 1 || actual != owner)
        goto out;
    if (lsf_node_capacity_record_locked(desc, LSF_NODE_IRQ_DESC, &actual, &record) != 1 ||
        actual != owner || record->deferred != LSF_PREPAID_PUBLISHED)
        goto out;
    for (index = 0; index < LSF_NODE_CAPACITY_VECTORS; ++index) {
        if (owner->irq_descs[index] != desc)
            continue;
        if (!(owner->irq_claimed & BIT(index)) ||
            (owner->irq_action_claimed & BIT(index)) ||
            lsf_node_capacity_record_locked(owner->irq_actions[index], LSF_NODE_IRQ_ACTION,
                &actual, &record) != 1 || actual != owner ||
            record->deferred != LSF_PREPAID_PRIVATE)
            goto out;
        record->deferred = LSF_PREPAID_PUBLISHED;
        owner->irq_action_claimed |= BIT(index);
        action = owner->irq_actions[index];
        break;
    }
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return action;
}

int lsf_node_capacity_action_close_private(struct lsf_node_capacity *owner,
    unsigned int index)
{
    struct lsf_node_parent *node;
    struct lsf_node_capacity *actual;
    struct lsf_prepaid_view *record;
    struct lsf_prepaid_context *context;
    unsigned long flags;
    void *address = NULL;
    int result = -EIO;

    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_capacity_parent_locked(owner);
    if (!node || index >= LSF_NODE_CAPACITY_VECTORS)
        goto poison;
    context = &factory.pool.contexts[node->owner.slot];
    if (!context->closed || factory.pool.poisoned || context->poisoned ||
        READ_ONCE(factory.uncertain))
        goto out;
    if (!owner->irq_actions[index] || (owner->irq_action_claimed & BIT(index)) ||
        (owner->irq_action_returned & BIT(index))) {
        result = 0;
        goto out;
    }
    if (lsf_node_capacity_record_locked(owner->irq_actions[index], LSF_NODE_IRQ_ACTION,
            &actual, &record) != 1 || actual != owner ||
        record->deferred != LSF_PREPAID_PRIVATE)
        goto poison;
    /* Never-claimed storage has no native __setup_irq/handler/proc aliases.
     * Only its private logical record returns; the actual page stays charged.
     */
    owner->irq_action_returned |= BIT(index);
    address = owner->irq_actions[index];
    spin_unlock_irqrestore(&pool_lock, flags);
    return lsf_node_capacity_native_free(address, LSF_NODE_IRQ_ACTION);
poison:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
