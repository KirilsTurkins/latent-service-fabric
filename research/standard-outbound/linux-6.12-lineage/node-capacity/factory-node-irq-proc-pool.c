/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in the original factory TU after Node record helpers. These are
 * affine native births from the SAME Node cursor, not a separate proc bank. */
void *lsf_node_irq_proc_allocate(struct lsf_node_capacity *owner,
    struct irq_desc *desc, unsigned int position, bool name)
{
    struct lsf_node_parent *node;
    struct lsf_node_capacity *actual;
    struct lsf_prepaid_view *record;
    enum lsf_node_capacity_role role = name ? LSF_NODE_PROC_NAME : LSF_NODE_PROC_PDE;
    void *address = NULL;
    unsigned long flags;
    unsigned int index;

    if (position >= LSF_NODE_IRQ_PROC_ENTRIES || (name && position != 8u))
        return NULL;
    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_capacity_parent_locked(owner);
    if (!lsf_node_capacity_open_locked(node) || !owner->pcpu_prepared ||
        lsf_node_irq_device_owner_locked(desc, &actual) != 1 || actual != owner ||
        lsf_node_capacity_record_locked(desc, LSF_NODE_IRQ_DESC, &actual, &record) != 1 ||
        actual != owner || record->deferred != LSF_PREPAID_PUBLISHED)
        goto out;
    for (index = 0; index < LSF_NODE_CAPACITY_VECTORS; ++index) {
        if (owner->irq_descs[index] != desc)
            continue;
        if (!(owner->irq_action_claimed & BIT(index)))
            goto out;
        if (name) {
            if (!(owner->irq_proc_claimed[index] & BIT(position)) ||
                (owner->irq_name_claimed & BIT(index)))
                goto out;
            owner->irq_name_claimed |= BIT(index);
        } else {
            if (owner->irq_proc_claimed[index] & BIT(position))
                goto out;
            owner->irq_proc_claimed[index] |= BIT(position);
        }
        spin_unlock_irqrestore(&pool_lock, flags);
        /* Existing reserve pays the exact exclusive page extent BEFORE native
         * allocation/zeroing. Failure never reopens this affine source slot. */
        address = lsf_node_capacity_take(owner, role,
            owner->extent[role].bytes, owner->extent[role].alignment);
        if (!address)
            return NULL;
        spin_lock_irqsave(&pool_lock, flags);
        node = lsf_node_capacity_parent_locked(owner);
        if (!lsf_node_capacity_open_locked(node) ||
            lsf_node_irq_device_owner_locked(desc, &actual) != 1 || actual != owner ||
            lsf_node_capacity_record_locked(address, role, &actual, &record) != 1 ||
            actual != owner || record->deferred != LSF_PREPAID_PRIVATE) {
            /* Real allocated output stays charged; no unowned free/fallback. */
            address = NULL;
            goto out;
        }
        if (name)
            owner->irq_proc_names[index] = address;
        else
            owner->irq_proc_entries[index][position] = address;
        record->deferred = LSF_PREPAID_PUBLISHED;
        goto out;
    }
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return address;
}

int lsf_node_irq_proc_classify(const void *address)
{
    struct lsf_node_capacity *owner;
    struct lsf_prepaid_view *record, *found;
    unsigned long flags, at = (unsigned long)address;
    unsigned int slot;
    int result = 0;

    spin_lock_irqsave(&pool_lock, flags);
    /* Only original native extents, including returned/interior addresses.
     * Existing STREAM logical PDE views in the original bank are NOT adopted.
     * The following exact-role lookup poisons wrong-type/duplicate addresses. */
    for (slot = 2; slot < LSF_ALLOCATION_SLOTS; ++slot) {
        record = &factory.pool.records[slot];
        if (record->phase != LSF_PREPAID_EMPTY &&
            record->kind > LSF_NODE_CAPACITY_NATIVE_BASE &&
            record->kind < LSF_NODE_CAPACITY_NATIVE_BASE + LSF_NODE_CAPACITY_ROLES &&
            record->offset != LSF_NODE_CAPACITY_UNBOUND &&
            at >= record->offset && at - record->offset < record->bytes) {
            result = lsf_node_capacity_record_locked(address, LSF_NODE_PROC_PDE,
                &owner, &found);
            break;
        }
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_irq_proc_name_pair(const void *pde, const void *name)
{
    struct lsf_node_capacity *owner, *name_owner;
    struct lsf_prepaid_view *record, *name_record;
    unsigned long flags;
    unsigned int index;
    int result = -EIO;

    spin_lock_irqsave(&pool_lock, flags);
    if (lsf_node_capacity_record_locked(pde, LSF_NODE_PROC_PDE, &owner, &record) != 1 ||
        lsf_node_capacity_record_locked(name, LSF_NODE_PROC_NAME, &name_owner,
            &name_record) != 1 || name_owner != owner)
        goto out;
    for (index = 0; index < LSF_NODE_CAPACITY_VECTORS; ++index)
        if (owner->irq_proc_entries[index][8] == pde &&
            owner->irq_proc_names[index] == name &&
            (owner->irq_name_claimed & BIT(index))) {
            result = 1;
            break;
        }
out:
    if (result != 1) {
        factory.pool.poisoned = 1;
        WRITE_ONCE(factory.uncertain, 1);
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
