/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in actual kernel/irq/irqdesc.c after its native functions. The
 * descriptor storage is prepaid before its first write. No function here
 * issues NodeFunding or bypasses native sysfs/proc/domain/vector ownership.
 */
#include <net/lsf_node_capacity_private.h>

int lsf_node_irq_layout(struct lsf_node_capacity *owner)
{
    struct lsf_node_capacity_extent *out;

    if (lsf_node_capacity_checkpoint(owner) || IS_ENABLED(CONFIG_CPUMASK_OFFSTACK) ||
        IS_ENABLED(CONFIG_DEBUG_KOBJECT_RELEASE) ||
        sizeof(struct irq_desc) > PAGE_SIZE || __alignof__(struct irq_desc) > PAGE_SIZE)
        return -EOPNOTSUPP;
    out = owner->extent;
    out[LSF_NODE_IRQ_DESC] = (struct lsf_node_capacity_extent){
        sizeof(struct irq_desc), __alignof__(struct irq_desc)};
    owner->irq_kobject_offset = offsetof(struct irq_desc, kobj);
    owner->irq_kobject_bytes = sizeof(struct kobject);
    return 0;
}

int lsf_node_irq_prepare(struct lsf_node_capacity *owner)
{
    unsigned int index;

    if (lsf_node_capacity_checkpoint(owner))
        return -EOPNOTSUPP;
    for (index = 0; index < LSF_NODE_CAPACITY_VECTORS; ++index) {
        owner->irq_descs[index] = lsf_node_capacity_take(owner, LSF_NODE_IRQ_DESC,
            sizeof(struct irq_desc), __alignof__(struct irq_desc));
        if (!owner->irq_descs[index])
            return -ENOMEM;
    }
    /* These are actual native allocations and original tickets, not live
     * IRQs or published descriptors. The eventual native constructor must
     * consume these views and real per-CPU cells only after whole admission.
     */
    return lsf_node_capacity_checkpoint(owner);
}

int lsf_node_irq_sparse_entry(const struct ma_state *mas, const void *entry)
{
    lockdep_assert_held(&sparse_irq_lock);
    return mas && mas->tree == &sparse_irqs && mas->index == mas->last &&
        mas->index <= UINT_MAX && irq_to_desc(mas->index) == entry;
}

int lsf_node_irq_desc_delete(unsigned int irq, struct irq_desc *desc)
{
    MA_STATE(mas, &sparse_irqs, irq, irq);
    struct lsf_node_capacity *owner;
    void *removed;
    int selected, error, unbound;

    lockdep_assert_held(&sparse_irq_lock);
    selected = lsf_node_capacity_native_owned(desc, LSF_NODE_IRQ_DESC, &owner);
    if (!selected) {
        delete_irq_desc(irq);
        return 0; /* Complete original ordinary route, same native lock. */
    }
    if (selected < 0)
        return selected;
    if (irq_desc_get_irq(desc) != irq)
        return -EIO;
    error = lsf_node_capacity_mas_bind_cleanup(&mas, desc);
    if (error)
        return error;
    /* Native erase can allocate even while removing an entry. The loan is
     * the exact still-published descriptor, not general admission after close.
     * mas_erase returns the entry even on allocation error, so its return alone
     * MUST NOT authorize descriptor retirement or the following native RCU.
     */
    removed = mas_erase(&mas);
    error = mas_is_err(&mas) ? xa_err(mas.node) : 0;
    if (!error && (removed != desc || irq_to_desc(irq) != NULL))
        error = -EIO;
    unbound = lsf_node_capacity_mas_unbind(owner, &mas);
    return error ? error : unbound;
}

int lsf_node_irq_desc_queue(struct irq_desc *desc)
{
    /* Called at the original call_rcu, AFTER real sparse-tree removal. The
     * same continuation lasts through RCU and actual kobject last-put. Its
     * original physical allocation stays held at irq_kobj_release.
     */
    return lsf_node_capacity_queue(desc, LSF_NODE_IRQ_DESC);
}

/* Native init_desc body with only its explicit allocator context changed.
 * The immutable layout gate rejects out-of-line mask allocation. Actual native
 * locks, defaults, resend, kobject and RCU initialization remain unchanged. */
static int lsf_node_init_desc(struct lsf_node_capacity *node_owner, struct irq_desc *desc, int irq, int node,
		     unsigned int flags,
		     const struct cpumask *affinity,
		     struct module *owner)
{
	desc->kstat_irqs = lsf_node_capacity_stat_take(node_owner);
	if (!desc->kstat_irqs)
		return -ENOMEM;

	if (alloc_masks(desc, node)) {
		free_percpu(desc->kstat_irqs);
		return -ENOMEM;
	}

	raw_spin_lock_init(&desc->lock);
	lockdep_set_class(&desc->lock, &irq_desc_lock_class);
	mutex_init(&desc->request_mutex);
	init_waitqueue_head(&desc->wait_for_threads);
	desc_set_defaults(irq, desc, node, affinity, owner);
	irqd_set(&desc->irq_data, flags);
	irq_resend_init(desc);
#ifdef CONFIG_SPARSE_IRQ
	kobject_init(&desc->kobj, &irq_kobj_type);
	init_rcu_head(&desc->rcu);
#endif

	return 0;
}

struct irq_desc *lsf_node_irq_desc_build(struct lsf_node_capacity *node_owner,
    int irq, int node, unsigned int flags, const struct cpumask *affinity,
    struct module *module_owner)
{
    struct irq_desc *desc;
    int error;

    desc = lsf_node_capacity_desc_take(node_owner);
    if (!desc)
        return NULL;
    error = lsf_node_init_desc(node_owner, desc, irq, node, flags, affinity, module_owner);
    if (error) {
        /* Native init failed before kobject_init. Its native failure path has
         * already returned any claimed stat cell; no uninitialized last-put. */
        lsf_node_capacity_native_free(desc, LSF_NODE_IRQ_DESC);
        return NULL;
    }
    if (lsf_node_capacity_checkpoint(node_owner)) {
        /* Real native kobject destruction calls irq_kobj_release only after
         * initialization, preserving its masks/stat cleanup and exact owner. */
        kobject_put(&desc->kobj);
        return NULL;
    }
    return desc;
}

struct irq_desc *lsf_node_irq_desc_allocate(int irq, int node, unsigned int flags,
    const struct cpumask *affinity, struct module *module_owner)
{
    struct lsf_node_capacity *owner;
    int selected = lsf_node_irq_current_owner(&owner);

    if (!selected)
        return alloc_desc(irq, node, flags, affinity, module_owner);
    if (selected < 0)
        return NULL;
    return lsf_node_irq_desc_build(owner, irq, node, flags, affinity, module_owner);
}

int lsf_node_irq_desc_insert(unsigned int irq, struct irq_desc *desc)
{
    struct lsf_node_capacity *owner;
    int selected = lsf_node_capacity_native_owned(desc, LSF_NODE_IRQ_DESC, &owner);

    if (!selected) {
        irq_insert_desc(irq, desc);
        return 0;
    }
    if (selected < 0)
        return selected;
    return lsf_node_irq_desc_store(owner, irq, desc);
}

int lsf_node_irq_desc_store(struct lsf_node_capacity *owner, unsigned int irq,
    struct irq_desc *desc)
{
    MA_STATE(mas, &sparse_irqs, irq, irq);
    struct lsf_node_capacity *actual;
    unsigned int index;
    int error;

    lockdep_assert_held(&sparse_irq_lock);
    if (lsf_node_capacity_native_owned(desc, LSF_NODE_IRQ_DESC, &actual) != 1 ||
        actual != owner)
        return -EIO;
    /* Original record precedes these descriptor fields. A repeated, foreign,
     * uninitialized or already externally registered descriptor is not adopted.
     */
    if (irq_desc_get_irq(desc) != irq || !desc->kobj.state_initialized ||
        desc->kobj.state_in_sysfs || irq_to_desc(irq) ||
        lsf_node_capacity_stat_lookup(desc->kstat_irqs, &actual, &index) != 1 ||
        actual != owner)
        return -EIO;
    error = lsf_node_mas_store(owner, &mas, desc);
    if (error) {
        /* Binding cleanup may fail AFTER the native store. Never last-put an
         * entry still visible in the actual tree. Unknown partial publication
         * stays with its original owner; no success/funding is returned.
         */
        if (irq_to_desc(irq) != desc)
            kobject_put(&desc->kobj);
        return error;
    }
    if (irq_to_desc(irq) != desc)
        return -EIO;
    /* This is ONLY the error-returning native sparse insertion boundary.
     * The complete provider must preserve its following real sysfs/proc paths
     * with their original prebirth Node provenance. No caller/issuer for that
     * incomplete provider path exists in this source prototype.
     */
    return 0;
}

int lsf_node_irq_kobject_type_known(const struct kobject *object)
{
    int owned = lsf_node_irq_kobject_owned(object);

    if (owned <= 0)
        return owned;
    if (object->ktype != &irq_kobj_type || !object->state_initialized)
        return lsf_node_irq_kobject_retain(object);
    return 1;
}

int lsf_node_irq_kobject_ready(const struct kobject *object)
{
    int owned = lsf_node_irq_kobject_type_known(object);

    if (owned <= 0)
        return owned;
    if (lsf_node_irq_kobject_current(object) != 1 || object->parent != irq_kobj_base ||
        (object->parent && object->parent->ktype && object->parent->ktype->child_ns_type))
        return -EOPNOTSUPP;
    /* Native irq_kobj_type uses its original sysfs ops/groups/release and no
     * ownership/namespace callback. Only this exact type is recognized here.
     */
    return 1;
}

int lsf_node_irq_kobject_add(struct irq_desc *desc, int irq)
{
    char text[12], *name;
    int owned, length, error;

    static_assert(sizeof(int) == 4);
    owned = lsf_node_irq_sysfs_enter(desc);
    if (!owned)
        return kobject_add(&desc->kobj, irq_kobj_base, "%d", irq);
    if (owned < 0)
        return owned;
    error = -EOPNOTSUPP;
    if (lsf_node_irq_kobject_type_known(&desc->kobj) != 1 || desc->kobj.name)
        goto out;
    /* Exact original signed-int conversion. -2147483648 plus NUL fits12;
     * there is no unsigned conversion, name inference or allocator multiplier.
     */
    length = snprintf(text, sizeof(text), "%d", irq);
    if (length <= 0 || length >= (int)sizeof(text))
        goto out;
    error = lsf_node_irq_name_copy(desc, text, &name);
    if (error)
        goto out;
    desc->kobj.name = name;
    /* Pinned kobject_set_name_vargs returns immediately for name && !fmt.
     * Native kobject_add still supplies its real parent, namespace and group
     * publication. The selected type's ready guard is checked independently.
     */
    error = kobject_add(&desc->kobj, irq_kobj_base, NULL);
out:
    /* Keep the actual native result so irq_sysfs_add records IRQS_SYSFS iff
     * publication really happened. A scope mismatch poisons the original
     * owner and the enclosing domain leave fails; it cannot certify success.
     */
    (void)lsf_node_irq_sysfs_leave(desc);
    return error;
}
