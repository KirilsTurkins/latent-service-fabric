/* SPDX-License-Identifier: GPL-2.0-only */
/* Included after factory-node-capacity.c in the SAME Node factory TU.
 * All aliases and tickets live in the precharged real Node parent. Physical
 * pages use original reserve/commit; bit custody is not a second byte ledger.
 * There is no NodeFunding/NodeRetired or physical matrix release constructor.
 */
static int lsf_node_irq_aux_poison_locked(void)
{
    lockdep_assert_held(&pool_lock);
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
    return -EIO;
}

static int lsf_node_irq_aux_index_locked(const void *address,
    enum lsf_node_capacity_role role, struct lsf_node_capacity **owner,
    unsigned int *index, struct lsf_prepaid_view **record)
{
    unsigned int i, matches = 0;
    void *expected;
    int selected;

    selected = lsf_node_capacity_record_locked(address, role, owner, record);
    if (selected != 1)
        return selected;
    for (i = 0; i < LSF_NODE_CAPACITY_VECTORS; ++i) {
        if (role == LSF_NODE_IRQ_DESC)
            expected = (*owner)->irq_descs[i];
        else if (role == LSF_NODE_IRQ_PARENT_DATA)
            expected = (*owner)->irq_parent_data[i];
        else if (role == LSF_NODE_IRQ_APIC)
            expected = (*owner)->irq_apic[i];
        else
            return lsf_node_irq_aux_poison_locked();
        if (address == expected) { *index = i; matches++; }
    }
    return matches == 1 ? 1 : lsf_node_irq_aux_poison_locked();
}

int lsf_node_irq_aux_index(const void *address, enum lsf_node_capacity_role role,
    struct lsf_node_capacity **owner, unsigned int *index)
{
    struct lsf_prepaid_view *record;
    unsigned long flags;
    int result;

    if (!owner || !index)
        return -EINVAL;
    *owner = NULL;
    *index = 0;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_node_irq_aux_index_locked(address, role, owner, index, &record);
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

static struct lsf_node_native_ticket lsf_node_irq_aux_ticket(
    struct lsf_prepaid_view *record, enum lsf_node_capacity_role role)
{
    return (struct lsf_node_native_ticket){record - factory.pool.records,
        role, record->generation, record->bytes, 64};
}

static int lsf_node_irq_aux_ticket_locked(const struct lsf_node_native_ticket *ticket,
    const struct lsf_prepaid_view *record, enum lsf_node_capacity_role role)
{
    return ticket->slot == record - factory.pool.records && ticket->role == role &&
        ticket->generation == record->generation && ticket->bytes == record->bytes &&
        ticket->alignment == 64;
}

int lsf_node_irq_aux_prepare(struct lsf_node_capacity *owner)
{
    unsigned int i;
    enum lsf_node_capacity_role role;
    void **array;

    lockdep_assert_held(&factory_lock);
    if (lsf_node_capacity_checkpoint(owner))
        return -EOPNOTSUPP;
    for (role = LSF_NODE_IRQ_PARENT_DATA; role <= LSF_NODE_IRQ_APIC; ++role) {
        array = role == LSF_NODE_IRQ_PARENT_DATA ? owner->irq_parent_data : owner->irq_apic;
        for (i = 0; i < LSF_NODE_CAPACITY_VECTORS; ++i) {
            if (array[i])
                return -EIO; /* No retry, page adoption or changed geometry. */
            array[i] = lsf_node_capacity_take(owner, role,
                owner->extent[role].bytes, owner->extent[role].alignment);
            if (!array[i])
                return -ENOMEM;
        }
    }
    return lsf_node_capacity_checkpoint(owner);
}

int lsf_node_vector_begin(struct lsf_node_capacity *owner, unsigned int index,
    struct irq_matrix *matrix)
{
    struct lsf_node_parent *node;
    struct lsf_node_capacity *actual;
    struct lsf_prepaid_view *record;
    struct lsf_node_vector_slot *slot;
    unsigned int found;
    unsigned long flags;
    int result = -EOPNOTSUPP;

    /* Caller holds actual vector_lock. No allocator runs under pool_lock. */
    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_capacity_parent_locked(owner);
    if (!lsf_node_capacity_open_locked(node) || !matrix ||
        index >= LSF_NODE_CAPACITY_VECTORS || owner->irq_aux_prepared ||
        owner->irq_apic_claimed || owner->irq_parent_claimed ||
        lsf_node_irq_aux_index_locked(owner->irq_apic[index], LSF_NODE_IRQ_APIC,
            &actual, &found, &record) != 1 || actual != owner || found != index ||
        record->deferred != LSF_PREPAID_PRIVATE)
        goto out;
    slot = &owner->vector_slots[index];
    if (slot->phase || slot->apic.generation || slot->desc.generation || slot->matrix)
        goto out;
    slot->apic = lsf_node_irq_aux_ticket(record, LSF_NODE_IRQ_APIC);
    slot->matrix = matrix;
    slot->phase = LSF_NODE_VECTOR_INTENT; /* Precedes the real native bit birth. */
    result = 0;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_vector_commit(struct lsf_node_capacity *owner, unsigned int index,
    struct irq_matrix *matrix, int vector, unsigned int cpu)
{
    struct lsf_node_parent *node;
    struct lsf_node_capacity *actual;
    struct lsf_prepaid_view *record;
    struct lsf_node_vector_slot *slot;
    unsigned int found;
    unsigned long flags;
    int result = -EIO;

    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_capacity_parent_locked(owner);
    if (!node || index >= LSF_NODE_CAPACITY_VECTORS ||
        lsf_node_irq_aux_index_locked(owner->irq_apic[index], LSF_NODE_IRQ_APIC,
            &actual, &found, &record) != 1 || actual != owner || found != index)
        goto poison;
    slot = &owner->vector_slots[index];
    if (slot->phase != LSF_NODE_VECTOR_INTENT || slot->matrix != matrix ||
        !lsf_node_irq_aux_ticket_locked(&slot->apic, record, LSF_NODE_IRQ_APIC))
        goto poison;
    if (vector < 0) { result = vector; goto out; }
    /* Capture ACTUAL native output before expiry/currentness checks. */
    slot->vector = vector;
    slot->cpu = cpu;
    slot->phase = LSF_NODE_VECTOR_HELD;
    if (cpu != 0 || !vector)
        goto poison;
    result = lsf_node_capacity_open_locked(node) ? 0 : -EOPNOTSUPP;
    goto out;
poison:
    lsf_node_irq_aux_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_irq_aux_ready(struct lsf_node_capacity *owner)
{
    struct lsf_node_parent *node;
    struct lsf_node_capacity *actual;
    struct lsf_prepaid_view *record;
    unsigned long flags;
    unsigned int i, found;
    int result = -EIO;

    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_capacity_parent_locked(owner);
    if (!lsf_node_capacity_open_locked(node) || owner->irq_aux_prepared)
        goto out;
    for (i = 0; i < LSF_NODE_CAPACITY_VECTORS; ++i) {
        if (owner->vector_slots[i].phase != LSF_NODE_VECTOR_HELD ||
            lsf_node_irq_aux_index_locked(owner->irq_parent_data[i], LSF_NODE_IRQ_PARENT_DATA,
                &actual, &found, &record) != 1 || actual != owner || found != i ||
            record->deferred != LSF_PREPAID_PRIVATE ||
            lsf_node_irq_aux_index_locked(owner->irq_apic[i], LSF_NODE_IRQ_APIC,
                &actual, &found, &record) != 1 || actual != owner || found != i ||
            record->deferred != LSF_PREPAID_PRIVATE ||
            !lsf_node_irq_aux_ticket_locked(&owner->vector_slots[i].apic, record, LSF_NODE_IRQ_APIC))
            goto out;
    }
    owner->irq_aux_prepared = 1;
    result = 0; /* This is not complete NodeFunding or a runtime fit receipt. */
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void *lsf_node_irq_aux_take(struct lsf_node_capacity *owner,
    enum lsf_node_capacity_role role, const void *parent)
{
    struct lsf_node_parent *node;
    struct lsf_node_capacity *actual;
    struct lsf_prepaid_view *parent_record, *record, *desc_record;
    struct lsf_node_vector_slot *slot;
    enum lsf_node_capacity_role parent_role;
    unsigned int index, found, *claimed;
    unsigned long flags;
    void *address = NULL;

    if (role != LSF_NODE_IRQ_PARENT_DATA && role != LSF_NODE_IRQ_APIC)
        return NULL;
    parent_role = role == LSF_NODE_IRQ_PARENT_DATA ? LSF_NODE_IRQ_DESC : LSF_NODE_IRQ_PARENT_DATA;
    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_capacity_parent_locked(owner);
    if (!lsf_node_capacity_open_locked(node) || !owner->irq_aux_prepared ||
        lsf_node_irq_aux_index_locked(parent, parent_role, &actual, &index, &parent_record) != 1 ||
        actual != owner || parent_record->deferred != LSF_PREPAID_PUBLISHED ||
        lsf_node_irq_aux_index_locked(owner->irq_descs[index], LSF_NODE_IRQ_DESC,
            &actual, &found, &desc_record) != 1 || actual != owner || found != index ||
        desc_record->deferred != LSF_PREPAID_PUBLISHED)
        goto out;
    address = role == LSF_NODE_IRQ_PARENT_DATA ? owner->irq_parent_data[index] : owner->irq_apic[index];
    claimed = role == LSF_NODE_IRQ_PARENT_DATA ? &owner->irq_parent_claimed : &owner->irq_apic_claimed;
    if ((*claimed & BIT(index)) ||
        lsf_node_irq_aux_index_locked(address, role, &actual, &found, &record) != 1 ||
        actual != owner || found != index || record->deferred != LSF_PREPAID_PRIVATE) {
        address = NULL;
        goto out;
    }
    if (role == LSF_NODE_IRQ_APIC) {
        slot = &owner->vector_slots[index];
        if (slot->phase != LSF_NODE_VECTOR_HELD ||
            !lsf_node_irq_aux_ticket_locked(&slot->apic, record, LSF_NODE_IRQ_APIC)) {
            address = NULL;
            goto out;
        }
        slot->desc = lsf_node_irq_aux_ticket(desc_record, LSF_NODE_IRQ_DESC);
        slot->phase = LSF_NODE_VECTOR_BOUND;
    }
    *claimed |= BIT(index);
    record->deferred = LSF_PREPAID_PUBLISHED;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return address;
}

/* Read/activate only an exact APIC record with its immutable descriptor ticket.
 * Return0 is reserved to genuinely ordinary addresses. Malformed known Node
 * objects poison/retain and never reach ordinary matrix/slab free paths. */
static int lsf_node_vector_record_locked(const void *address, struct irq_matrix *matrix,
    struct lsf_node_capacity **owner, struct lsf_node_vector_slot **slot)
{
    struct lsf_node_capacity *actual;
    struct lsf_prepaid_view *record, *desc;
    unsigned int index, found;
    int selected;

    selected = lsf_node_irq_aux_index_locked(address, LSF_NODE_IRQ_APIC, owner, &index, &record);
    if (selected != 1)
        return selected;
    *slot = &(*owner)->vector_slots[index];
    if (record->deferred != LSF_PREPAID_PUBLISHED ||
        (*slot)->matrix != matrix || (*slot)->cpu != 0 || !(*slot)->vector ||
        ((*slot)->phase != LSF_NODE_VECTOR_BOUND && (*slot)->phase != LSF_NODE_VECTOR_ACTIVE) ||
        !lsf_node_irq_aux_ticket_locked(&(*slot)->apic, record, LSF_NODE_IRQ_APIC) ||
        lsf_node_irq_aux_index_locked((*owner)->irq_descs[index], LSF_NODE_IRQ_DESC,
            &actual, &found, &desc) != 1 || actual != *owner || found != index ||
        !lsf_node_irq_aux_ticket_locked(&(*slot)->desc, desc, LSF_NODE_IRQ_DESC) ||
        desc->deferred != LSF_PREPAID_PUBLISHED)
        return lsf_node_irq_aux_poison_locked();
    return 1;
}

int lsf_node_vector_read(const void *apic, struct irq_matrix *matrix,
    struct lsf_node_vector_slot *out)
{
    struct lsf_node_capacity *owner;
    struct lsf_node_vector_slot *slot;
    unsigned long flags;
    int result;

    if (!out)
        return -EINVAL;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_node_vector_record_locked(apic, matrix, &owner, &slot);
    if (result == 1)
        *out = *slot;
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_vector_activate(const void *apic, struct irq_matrix *matrix)
{
    struct lsf_node_capacity *owner;
    struct lsf_node_vector_slot *slot;
    struct lsf_node_parent *node;
    unsigned long flags;
    int result;

    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_node_vector_record_locked(apic, matrix, &owner, &slot);
    if (result == 1) {
        node = lsf_node_capacity_parent_locked(owner);
        if (!lsf_node_capacity_open_locked(node) || slot->phase != LSF_NODE_VECTOR_BOUND)
            result = -EOPNOTSUPP;
        else
            slot->phase = LSF_NODE_VECTOR_ACTIVE;
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_vector_retain(struct irq_matrix *matrix, unsigned int cpu,
    unsigned int vector, bool managed)
{
    struct lsf_node_parent *node;
    struct lsf_node_capacity *owner;
    struct lsf_node_vector_slot *slot, *validated;
    unsigned long flags, base;
    unsigned int index;
    int result = 0;

    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.pages)
        goto out;
    base = (unsigned long)page_address(factory.pages);
    node = (void *)(base + LSF_FACTORY_INFRA_OFFSET);
    node = lsf_node_capacity_parent_locked(&node->capacity);
    if (!node) {
        /* An invalid original Node registrar cannot authorize allocator free.
         * No owner payload is read after this failed complete-parent check. */
        result = lsf_node_irq_unknown_parent_locked(NULL);
        goto out;
    }
    for (index = 0; index < LSF_NODE_CAPACITY_VECTORS; ++index) {
        slot = &node->capacity.vector_slots[index];
        if (slot->phase < LSF_NODE_VECTOR_HELD || slot->matrix != matrix ||
            slot->cpu != cpu || slot->vector != vector)
            continue;
        result = -EIO;
        if (managed || slot->phase != LSF_NODE_VECTOR_ACTIVE ||
            lsf_node_vector_record_locked(node->capacity.irq_apic[index], matrix,
                &owner, &validated) != 1 || owner != &node->capacity || validated != slot) {
            lsf_node_irq_aux_poison_locked();
            goto out;
        }
        slot->phase = LSF_NODE_VECTOR_BOUND;
        result = 1; /* Keep actual alloc_map bit; no reuse by another attempt. */
        goto out;
    }
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_irq_aux_uncertain(const void *address, enum lsf_node_capacity_role role)
{
    struct lsf_node_capacity *owner;
    struct lsf_prepaid_view *record;
    unsigned int index;
    unsigned long flags;
    int selected;

    if (role != LSF_NODE_IRQ_PARENT_DATA && role != LSF_NODE_IRQ_APIC)
        return -EINVAL;
    spin_lock_irqsave(&pool_lock, flags);
    selected = lsf_node_irq_aux_index_locked(address, role, &owner, &index, &record);
    if (selected)
        selected = lsf_node_irq_aux_poison_locked();
    spin_unlock_irqrestore(&pool_lock, flags);
    return selected;
}

int lsf_node_irq_aux_retire(const void *address, enum lsf_node_capacity_role role)
{
    struct lsf_node_capacity *owner;
    struct lsf_node_vector_slot *slot;
    struct lsf_prepaid_view *record;
    unsigned int index;
    unsigned long flags;
    int selected;

    if (role != LSF_NODE_IRQ_PARENT_DATA && role != LSF_NODE_IRQ_APIC)
        return -EINVAL;
    spin_lock_irqsave(&pool_lock, flags);
    selected = lsf_node_irq_aux_index_locked(address, role, &owner, &index, &record);
    if (selected == 1 &&
        (record->deferred != LSF_PREPAID_PUBLISHED ||
         (role == LSF_NODE_IRQ_PARENT_DATA && !(owner->irq_parent_claimed & BIT(index))) ||
         (role == LSF_NODE_IRQ_APIC && !(owner->irq_apic_claimed & BIT(index)))))
        selected = lsf_node_irq_aux_poison_locked();
    if (selected == 1 && role == LSF_NODE_IRQ_APIC) {
        slot = &owner->vector_slots[index];
        if (slot->phase != LSF_NODE_VECTOR_BOUND ||
            !lsf_node_irq_aux_ticket_locked(&slot->apic, record, LSF_NODE_IRQ_APIC))
            selected = lsf_node_irq_aux_poison_locked();
        else
            slot->phase = LSF_NODE_VECTOR_RETAINED;
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    if (selected == 1)
        return lsf_node_capacity_native_free(address, role);
    return selected;
}
