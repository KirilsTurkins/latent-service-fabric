/* SPDX-License-Identifier: GPL-2.0-only */
#include <linux/radix-tree.h>
/* Include after factory-node-irq-loan.c. All metadata is in the original
 * prepaid Node parent; packed payload views use the existing real page owner.
 * No domain/root pointer is dereferenced by late queue/RCU classification. */
static_assert(ARRAY_SIZE(((struct lsf_node_capacity *)0)->radix_origin) ==
    LSF_ALLOCATION_SLOTS);

static int lsf_node_radix_poison_locked(void)
{
    lockdep_assert_held(&pool_lock);
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
    return -EIO;
}

static int lsf_node_radix_record_locked(const void *address,
    struct lsf_node_capacity **owner, struct lsf_prepaid_view **record,
    struct lsf_node_radix_origin **origin)
{
    struct lsf_prepaid_view *candidate;
    struct lsf_node_radix_origin *saved;
    unsigned int slot, role;
    int selected;

    lockdep_assert_held(&pool_lock);
    for (slot = 2; slot < LSF_ALLOCATION_SLOTS; ++slot) {
        candidate = &factory.pool.records[slot];
        if (candidate->offset != (unsigned long)address ||
            (candidate->kind != LSF_NODE_CAPACITY_KIND_BASE + LSF_NODE_RADIX_PRIVATE &&
             candidate->kind != LSF_NODE_CAPACITY_KIND_BASE + LSF_NODE_RADIX_SHARED))
            continue;
        role = candidate->kind - LSF_NODE_CAPACITY_KIND_BASE;
        selected = lsf_node_capacity_record_locked(address, role, owner, record);
        if (selected != 1)
            return selected;
        saved = &(*owner)->radix_origin[slot];
        if (saved->view_generation != candidate->generation || saved->role != role ||
            !saved->root_identity || !saved->domain.generation || !saved->pci.generation)
            return lsf_node_radix_poison_locked();
        *origin = saved;
        return 1;
    }
    /* Do not swallow the existing original-bank MSI/IDR dispatchers. Only
     * native Node extents and our logical radix views are this classifier's
     * unknown-range responsibility; other original roles continue unchanged. */
    for (slot = 2; slot < LSF_ALLOCATION_SLOTS; ++slot) {
        candidate = &factory.pool.records[slot];
        if (candidate->phase == LSF_PREPAID_EMPTY ||
            candidate->offset == LSF_NODE_CAPACITY_UNBOUND ||
            (unsigned long)address < candidate->offset ||
            (unsigned long)address - candidate->offset >= candidate->bytes)
            continue;
        if ((candidate->kind > LSF_NODE_CAPACITY_NATIVE_BASE &&
             candidate->kind < LSF_NODE_CAPACITY_NATIVE_BASE + LSF_NODE_CAPACITY_ROLES) ||
            candidate->kind == LSF_NODE_CAPACITY_KIND_BASE + LSF_NODE_RADIX_PRIVATE ||
            candidate->kind == LSF_NODE_CAPACITY_KIND_BASE + LSF_NODE_RADIX_SHARED)
            return lsf_node_radix_poison_locked();
    }
    return 0;
}

/* Only a source-classified actual x86 vector root may keep its logical nodes
 * through device-child close. Private-root nodes are NEVER exempted. Original
 * domain/PCI metadata can be tombstoned by then, but its slot/generation and
 * same-Node ancestry cannot be reset, reused or reparented. No payload read. */
static int lsf_node_radix_shared_record_locked(struct lsf_node_capacity *owner,
    struct lsf_prepaid_view *record)
{
    struct lsf_node_capacity *actual;
    struct lsf_prepaid_view *found, *domain, *pci;
    struct lsf_node_radix_origin *origin;
    struct lsf_node_parent *node;

    lockdep_assert_held(&pool_lock);
    if (record->kind != LSF_NODE_CAPACITY_KIND_BASE + LSF_NODE_RADIX_SHARED ||
        lsf_node_radix_record_locked((void *)(unsigned long)record->offset,
            &actual, &found, &origin) != 1 || actual != owner || found != record ||
        origin->role != LSF_NODE_RADIX_SHARED ||
        origin->domain.slot < 2 || origin->domain.slot >= LSF_ALLOCATION_SLOTS ||
        origin->pci.slot < 2 || origin->pci.slot >= LSF_ALLOCATION_SLOTS ||
        origin->pci.role != LSF_DEVICE_PCI || origin->domain.alignment != 64 ||
        origin->pci.alignment != 64)
        return 0;
    node = lsf_node_capacity_parent_locked(owner);
    if (!node)
        return 0;
    domain = &factory.pool.records[origin->domain.slot];
    pci = &factory.pool.records[origin->pci.slot];
    return (domain->phase == LSF_PREPAID_LIVE || domain->phase == LSF_PREPAID_RETURNED) &&
        (pci->phase == LSF_PREPAID_LIVE || pci->phase == LSF_PREPAID_RETURNED) &&
        domain->generation == origin->domain.generation && domain->kind == origin->domain.role &&
        domain->bytes == origin->domain.bytes && domain->owner == node->owner.slot &&
        domain->owner_generation == node->owner.generation &&
        domain->cache_bucket == origin->pci.slot && domain->cache_anchor == origin->pci.generation &&
        pci->generation == origin->pci.generation && pci->kind == origin->pci.role &&
        pci->bytes == origin->pci.bytes && pci->owner == node->owner.slot &&
        pci->owner_generation == node->owner.generation &&
        pci->cache_bucket == owner->device_root.slot &&
        pci->cache_anchor == owner->device_root.generation;
}

void *lsf_node_radix_take(struct lsf_node_capacity *owner,
    struct radix_tree_root *root, unsigned long bytes, unsigned long alignment)
{
    struct lsf_node_parent *node;
    struct lsf_node_capacity *actual;
    struct lsf_prepaid_view *record;
    struct lsf_node_radix_origin *origin;
    unsigned long flags;
    void *address;
    int role = lsf_node_radix_root_role(owner, root);

    /* Native irqdomain TU derives the class from the actual authenticated
     * child and real x86 vector parent. The caller supplies no class flag. */
    if (role != LSF_NODE_RADIX_PRIVATE && role != LSF_NODE_RADIX_SHARED)
        return NULL;
    address = lsf_node_capacity_take(owner, role, bytes, alignment);
    if (!address)
        return NULL;
    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_capacity_parent_locked(owner);
    if (!lsf_node_irq_call_current_locked(node) ||
        lsf_node_capacity_record_locked(address, role, &actual, &record) != 1 ||
        actual != owner || record->deferred != LSF_PREPAID_PRIVATE)
        goto poison;
    origin = &owner->radix_origin[record - factory.pool.records];
    if (origin->view_generation || origin->root_identity)
        goto poison;
    *origin = (struct lsf_node_radix_origin){
        .root_identity = (unsigned long)root,
        .view_generation = record->generation,
        .domain = owner->irq_domain_birth,
        .pci = owner->irq_pci_birth,
        .role = role,
    };
    spin_unlock_irqrestore(&pool_lock, flags);
    return address;
poison:
    lsf_node_radix_poison_locked();
    spin_unlock_irqrestore(&pool_lock, flags);
    /* The actual backing/view and original ticket remain retained. */
    return NULL;
}

int lsf_node_radix_owned(const void *address,
    struct lsf_node_capacity **owner, unsigned int *role)
{
    struct lsf_prepaid_view *record;
    struct lsf_node_radix_origin *origin;
    unsigned long flags;
    int result;

    if (!owner || !role)
        return -EINVAL;
    *owner = NULL;
    *role = 0;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_node_radix_record_locked(address, owner, &record, &origin);
    if (result == 1)
        *role = origin->role;
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_radix_root_owned(struct radix_tree_root *root,
    struct lsf_node_capacity **copy)
{
    struct lsf_node_parent *node;
    struct lsf_node_radix_origin *origin;
    struct lsf_prepaid_view *record;
    unsigned int slot;
    unsigned long flags;
    int role = 0;

    if (!root || !copy)
        return -EINVAL;
    *copy = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_irq_parent_locked();
    if (!node) {
        role = lsf_node_irq_unknown_parent_locked(root);
        goto out;
    }
    for (slot = 2; slot < LSF_ALLOCATION_SLOTS; ++slot) {
        origin = &node->capacity.radix_origin[slot];
        if (origin->root_identity != (unsigned long)root)
            continue;
        record = &factory.pool.records[slot];
        if (!origin->view_generation || record->generation != origin->view_generation ||
            record->owner != node->owner.slot ||
            record->owner_generation != node->owner.generation ||
            (record->phase != LSF_PREPAID_LIVE && record->phase != LSF_PREPAID_RETURNED) ||
            (origin->role != LSF_NODE_RADIX_PRIVATE && origin->role != LSF_NODE_RADIX_SHARED) ||
            record->kind != LSF_NODE_CAPACITY_KIND_BASE + origin->role ||
            !origin->domain.generation || !origin->pci.generation ||
            (role && role != origin->role)) {
            role = lsf_node_radix_poison_locked();
            goto out;
        }
        role = origin->role;
    }
    if (role)
        *copy = &node->capacity;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return role;
}

int lsf_node_radix_node_matches(const void *address,
    struct lsf_node_capacity *owner, struct radix_tree_root *root,
    unsigned int role)
{
    struct lsf_node_capacity *actual;
    struct lsf_prepaid_view *record;
    struct lsf_node_radix_origin *origin;
    unsigned long flags;
    int result;

    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_node_radix_record_locked(address, &actual, &record, &origin);
    if (result == 1 && (actual != owner || origin->role != role ||
        origin->root_identity != (unsigned long)root ||
        record->deferred != LSF_PREPAID_PUBLISHED))
        result = lsf_node_radix_poison_locked();
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_radix_uncertain(const void *address)
{
    struct lsf_node_capacity *owner;
    struct lsf_prepaid_view *record;
    struct lsf_node_radix_origin *origin;
    unsigned long flags;
    int result;

    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_node_radix_record_locked(address, &owner, &record, &origin);
    if (result)
        result = lsf_node_radix_poison_locked();
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_radix_queue(const void *address)
{
    struct lsf_node_capacity *owner;
    unsigned int role;
    int result = lsf_node_radix_owned(address, &owner, &role);

    if (result != 1)
        return result;
    result = lsf_node_capacity_queue(address, role);
    if (result != 1)
        lsf_node_radix_uncertain(address);
    return result;
}

/* Called before callback payload access. No root/domain/array is read. */
int lsf_node_radix_rcu_ready(const void *address)
{
    struct lsf_node_capacity *owner;
    struct lsf_prepaid_view *record;
    struct lsf_node_radix_origin *origin;
    unsigned long flags;
    int result;

    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_node_radix_record_locked(address, &owner, &record, &origin);
    if (result == 1 && record->deferred != LSF_PREPAID_QUEUED)
        result = lsf_node_radix_poison_locked();
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_radix_finish(const void *address)
{
    struct lsf_node_capacity *owner;
    unsigned int role;
    int result = lsf_node_radix_rcu_ready(address);

    if (result != 1)
        return result;
    result = lsf_node_radix_owned(address, &owner, &role);
    return result == 1 ? lsf_node_capacity_native_free(address, role) : result;
    /* No physical free, cursor reuse, ticket refund or NodeRetired claim. */
}
