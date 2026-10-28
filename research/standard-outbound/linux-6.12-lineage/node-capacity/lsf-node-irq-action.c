/* SPDX-License-Identifier: GPL-2.0-only */
/* Included after pinned kernel/irq/manage.c: its real threading predicates and
 * irqaction layout are visible. This is not an IRQ/funding admission issuer. */
#include <net/lsf_node_capacity_private.h>

int lsf_node_irq_action_layout(struct lsf_node_capacity_extent *out)
{
    if (!out || sizeof(struct irqaction) > PAGE_SIZE ||
        __alignof__(struct irqaction) > PAGE_SIZE)
        return -EOPNOTSUPP;
    out[LSF_NODE_IRQ_ACTION] = (struct lsf_node_capacity_extent){
        sizeof(struct irqaction), __alignof__(struct irqaction)};
    return 0;
}

int lsf_node_irq_action_prepare(struct lsf_node_capacity *owner)
{
    unsigned int index;

    if (lsf_node_capacity_checkpoint(owner))
        return -EOPNOTSUPP;
    for (index = 0; index < LSF_NODE_CAPACITY_VECTORS; ++index) {
        owner->irq_actions[index] = lsf_node_capacity_take(owner, LSF_NODE_IRQ_ACTION,
            sizeof(struct irqaction), __alignof__(struct irqaction));
        if (!owner->irq_actions[index])
            return -ENOMEM;
    }
    return lsf_node_capacity_checkpoint(owner);
}

static int lsf_node_irq_action_select(struct irq_desc *desc, irq_handler_t handler,
    irq_handler_t thread_fn, unsigned long flags, struct irqaction **out)
{
    struct lsf_node_capacity *owner;
    struct irqaction *action;
    int selected;

    selected = lsf_node_irq_device_owner(desc, &owner);
    if (selected != 1)
        return selected;
    /* Match the REAL pre-setup branches; do not add NO_THREAD, alter flags,
     * call the forcing helper early, or infer that a NULL thread_fn is enough.
     * Native task/thread/stack birth and optional timings are not closed here. */
    if (thread_fn || irq_settings_is_nested_thread(desc) ||
        IS_ENABLED(CONFIG_IRQ_TIMINGS) ||
        (irq_settings_can_thread(desc) && force_irqthreads() &&
         !(flags & (IRQF_NO_THREAD | IRQF_PERCPU | IRQF_ONESHOT)) &&
         handler != irq_default_primary_handler))
        return -EOPNOTSUPP;
    action = lsf_node_capacity_action_take(owner, desc);
    if (!action)
        return -ENOMEM;
    /* The exact original action ticket/view preceded its very first field. */
    memset(action, 0, sizeof(*action));
    *out = action;
    return 1;
}

int lsf_node_irq_action_free(struct irqaction *action)
{
    /* Called at the original kfree sites only after native IRQ/proc rundown.
     * Known failed/closed provenance must never fall through to slab free. */
    return lsf_node_capacity_native_free(action, LSF_NODE_IRQ_ACTION);
}
