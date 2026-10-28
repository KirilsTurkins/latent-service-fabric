/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in the actual x86 vector TU. The existing platform vector_matrix
 * remains a native provider prerequisite, never retroactively adopted. Eight
 * real native alloc_map bits are owned by the original Node BEFORE IRQ birth.
 */
#include <net/lsf_node_capacity_private.h>

int lsf_node_vector_layout(struct lsf_node_capacity_extent *out)
{
    if (!out || sizeof(struct apic_chip_data) > PAGE_SIZE ||
        __alignof__(struct apic_chip_data) > PAGE_SIZE)
        return -EOPNOTSUPP;
    out[LSF_NODE_IRQ_APIC] = (struct lsf_node_capacity_extent){
        sizeof(struct apic_chip_data), __alignof__(struct apic_chip_data)};
    return 0;
}

int lsf_node_vector_prepare(struct lsf_node_capacity *owner)
{
    unsigned long flags;
    unsigned int index, cpu;
    int vector, error = -EOPNOTSUPP;

    /* Original pcpu_prepare holds cpus_read_lock across this entire call.
     * Do not recursively acquire it behind a waiting hotplug writer. */
    raw_spin_lock_irqsave(&vector_lock, flags);
    if (!vector_matrix || !x86_vector_domain || x86_vector_domain->parent ||
        apic_is_disabled || num_possible_cpus() != 1 || !cpu_possible(0) ||
        nr_cpu_ids != 1 || num_online_cpus() != 1 || !cpu_online(0) ||
        !lsf_node_matrix_room(vector_matrix, LSF_NODE_CAPACITY_VECTORS))
        goto out;
    for (index = 0; index < LSF_NODE_CAPACITY_VECTORS; ++index) {
        error = lsf_node_vector_begin(owner, index, vector_matrix);
        if (error)
            goto out;
        cpu = nr_cpu_ids;
        /* Native allocation sets the real bit and capacity counters. A mere
         * irq_matrix_reserve/global_reserved snapshot cannot provide this. */
        vector = irq_matrix_alloc(vector_matrix, cpumask_of(0), false, &cpu);
        error = lsf_node_vector_commit(owner, index, vector_matrix, vector, cpu);
        if (error)
            goto out; /* Partial bits remain held by the SAME original Node. */
        if (!lsf_node_matrix_held(vector_matrix, cpu, vector)) {
            error = -EIO;
            goto out;
        }
    }
    error = lsf_node_irq_aux_ready(owner);
out:
    raw_spin_unlock_irqrestore(&vector_lock, flags);
    return error;
}

static struct apic_chip_data *lsf_node_alloc_apic(struct irq_data *data, int node,
    const struct irq_alloc_info *info)
{
    struct lsf_node_capacity *owner, *current_owner;
    struct irq_domain *source;
    struct apic_chip_data *apicd;
    unsigned int index;
    int selected;

    selected = lsf_node_irq_aux_index(data, LSF_NODE_IRQ_PARENT_DATA, &owner, &index);
    if (!selected)
        return alloc_apic_chip_data(node); /* Complete original ordinary body. */
    if (selected < 0 || !info || (info->flags & X86_IRQ_ALLOC_LEGACY) ||
        lsf_node_irq_current_owner(&current_owner) != 1 || current_owner != owner)
        return NULL;
    /* The actual parent-data allocation was authenticated before these reads. */
    source = lsf_node_irq_current_domain(owner);
    if (!source || source->parent != x86_vector_domain || data->domain != x86_vector_domain ||
        x86_vector_domain->parent || data->parent_data || data->chip_data ||
        irqd_affinity_is_managed(data))
        return NULL;
    apicd = lsf_node_irq_aux_take(owner, LSF_NODE_IRQ_APIC, data);
    if (apicd)
        INIT_HLIST_NODE(&apicd->clist); /* Exact native constructor default. */
    return apicd;
}

static int lsf_node_retire_apic(struct apic_chip_data *apicd)
{
    struct lsf_node_capacity *owner;
    unsigned int index;
    int selected = lsf_node_irq_aux_index(apicd, LSF_NODE_IRQ_APIC, &owner, &index);

    if (selected != 1)
        return selected;
    if (apicd->vector || apicd->prev_vector || apicd->move_in_progress ||
        !hlist_unhashed(&apicd->clist))
        return lsf_node_irq_aux_uncertain(apicd, LSF_NODE_IRQ_APIC);
    return lsf_node_irq_aux_retire(apicd, LSF_NODE_IRQ_APIC);
}

static int lsf_node_vector_slot(struct irq_data *data, struct lsf_node_vector_slot *slot)
{
    int selected;
    lockdep_assert_held(&vector_lock);
    selected = lsf_node_vector_read(apic_chip_data(data), vector_matrix, slot);
    if (selected == 1 && (!lsf_node_matrix_held(vector_matrix, slot->cpu, slot->vector) ||
        irqd_affinity_is_managed(data)))
        return lsf_node_irq_aux_uncertain(apic_chip_data(data), LSF_NODE_IRQ_APIC);
    return selected;
}

static int lsf_node_vector_soft_reserve(struct irq_data *data)
{
    struct lsf_node_vector_slot slot;
    struct apic_chip_data *apicd = apic_chip_data(data);
    int selected = lsf_node_vector_slot(data, &slot);
    if (selected == 1 && (slot.phase != LSF_NODE_VECTOR_BOUND || apicd->has_reserved))
        return lsf_node_irq_aux_uncertain(apicd, LSF_NODE_IRQ_APIC);
    /* Selected has_reserved is backed by its exact preheld native bit, not
     * another global_reserved count. Original can_reserve/shutdown code runs. */
    return selected;
}

static int lsf_node_vector_remove_soft(struct irq_data *data)
{
    struct lsf_node_vector_slot slot;
    int selected = lsf_node_vector_slot(data, &slot);
    if (selected == 1 && slot.phase != LSF_NODE_VECTOR_BOUND)
        return lsf_node_irq_aux_uncertain(apic_chip_data(data), LSF_NODE_IRQ_APIC);
    return selected;
}

static int lsf_node_vector_alloc(struct irq_data *data, const struct cpumask *mask,
    bool reserved, unsigned int *cpu)
{
    struct lsf_node_vector_slot slot;
    struct apic_chip_data *apicd = apic_chip_data(data);
    int selected = lsf_node_vector_slot(data, &slot);

    if (!selected)
        return irq_matrix_alloc(vector_matrix, mask, reserved, cpu);
    if (selected < 0)
        return selected;
    if (!mask || cpumask_empty(mask) || !cpumask_test_cpu(0, mask))
        return -EOPNOTSUPP;
    if (slot.phase != LSF_NODE_VECTOR_BOUND || apicd->vector || apicd->prev_vector ||
        apicd->move_in_progress || !hlist_unhashed(&apicd->clist))
        return lsf_node_irq_aux_uncertain(apicd, LSF_NODE_IRQ_APIC);
    selected = lsf_node_vector_activate(apicd, vector_matrix);
    if (selected != 1)
        return selected < 0 ? selected : -EIO;
    *cpu = slot.cpu;
    return slot.vector; /* SAME already allocated bit; no renewed selection. */
}

static void lsf_node_vector_matrix_free(unsigned int cpu, unsigned int vector, bool managed)
{
    int selected;
    lockdep_assert_held(&vector_lock);
    /* Native callers have already removed this vector's actual device alias.
     * A negative classification is retained, never ordinary allocator fallback.
     */
    selected = lsf_node_vector_retain(vector_matrix, cpu, vector, managed);
    if (!selected)
        irq_matrix_free(vector_matrix, cpu, vector, managed);
}


static int lsf_node_reserve_vector(struct irq_data *data)
{
    struct apic_chip_data *apicd = apic_chip_data(data);
    int selected = lsf_node_vector_soft_reserve(data);
    if (selected < 0)
        return selected;
    if (!selected) {
        reserve_irq_vector_locked(data);
        return 0;
    }
    /* Original native body except its unbacked global soft-counter increment.
     * The same held alloc_map bit backs this descriptor's reservation. */
    apicd->can_reserve = true;
    apicd->has_reserved = true;
    irqd_set_can_reserve(data);
    trace_vector_reserve(data->irq, 0);
    vector_assign_managed_shutdown(data);
    return 0;
}

static void lsf_node_remove_vector_reservation(struct irq_data *data)
{
    int selected = lsf_node_vector_remove_soft(data);
    if (!selected)
        irq_matrix_remove_reserved(vector_matrix);
    /* Selected descriptors never added a global soft reservation. Their
     * actual bit remains with the Node, including on incomplete cleanup. */
}
