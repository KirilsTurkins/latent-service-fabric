/* SPDX-License-Identifier: GPL-2.0-only */
/* Same factory TU. Original typed domain/PCI births lend one synchronous
 * allocator/registration scope. Nothing here issues NodeFunding or inherits
 * authority from a thread, kobject address, ordinary parent or artifact alone.
 */
#include <net/lsf_stream_q35_msi_private.h>
#include <linux/sched/task.h>

/* The original definition belongs to the same captured factory TU. */
static struct lsf_prepaid_view *lsf_q35_record_locked(const void *address,
    unsigned int role, struct device **actual, struct lsf_prepaid_ticket *ticket);

static int lsf_node_irq_birth_equal(const struct lsf_node_native_ticket *left,
    const struct lsf_node_native_ticket *right)
{
    return left->slot == right->slot && left->role == right->role &&
        left->generation == right->generation && left->bytes == right->bytes &&
        left->alignment == right->alignment;
}

static struct lsf_node_parent *lsf_node_irq_parent_locked(void)
{
    struct lsf_node_parent *node;
    unsigned long base;

    lockdep_assert_held(&pool_lock);
    if (!factory.pages)
        return NULL;
    base = (unsigned long)page_address(factory.pages);
    node = (void *)(base + LSF_FACTORY_INFRA_OFFSET);
    return lsf_node_capacity_parent_locked(&node->capacity);
}

/* This TU exists only in the immutable Node-capacity image. Once its one
 * Node open completed, invalid registrar bytes cannot turn a selected caller
 * into an ordinary allocator caller. Before open, unrelated OS routes remain
 * ordinary; a known bank address/native reservation still fails closed. */
static int lsf_node_irq_unknown_parent_locked(const void *address)
{
    unsigned long base, at = (unsigned long)address;
    unsigned int slot;
    int known = factory.opened;

    lockdep_assert_held(&pool_lock);
    if (factory.pages) {
        base = (unsigned long)page_address(factory.pages);
        if (address && at >= base && at - base < LSF_BACKING_BYTES)
            known = 1;
    }
    if (factory.pool.records[1].kind == LSF_NODE_PARENT_KIND)
        known = 1;
    for (slot = 2; !known && slot < LSF_ALLOCATION_SLOTS; ++slot) {
        const struct lsf_prepaid_view *record = &factory.pool.records[slot];
        if (record->phase != LSF_PREPAID_EMPTY &&
            record->kind > LSF_NODE_CAPACITY_NATIVE_BASE &&
            record->kind < LSF_NODE_CAPACITY_NATIVE_BASE + LSF_NODE_CAPACITY_ROLES)
            known = 1;
    }
    if (!known)
        return 0;
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
    return -EIO;
}

static int lsf_node_irq_call_current_locked(struct lsf_node_parent *node)
{
    struct lsf_node_capacity *owner;
    struct lsf_prepaid_view *domain, *pci;
    struct lsf_prepaid_ticket ticket;
    struct device *device;

    lockdep_assert_held(&pool_lock);
    if (!lsf_node_capacity_open_locked(node) || !lsf_node_device_actor_current())
        return 0;
    owner = &node->capacity;
    if (!owner->irq_call || owner->irq_task != current || !owner->irq_generation ||
        !factory.device->constructor_active || factory.device->constructor_task != current)
        return 0;
    domain = lsf_q35_record_locked(owner->irq_domain, LSF_Q35_MSI_DOMAIN, &device, &ticket);
    if (!domain || domain->deferred != LSF_PREPAID_PUBLISHED ||
        ticket.slot != owner->irq_domain_birth.slot ||
        ticket.generation != owner->irq_domain_birth.generation ||
        domain->kind != owner->irq_domain_birth.role ||
        domain->bytes != owner->irq_domain_birth.bytes ||
        domain->owner != node->owner.slot || domain->owner_generation != node->owner.generation ||
        domain->cache_bucket != owner->irq_pci_birth.slot ||
        domain->cache_anchor != owner->irq_pci_birth.generation)
        return 0;
    pci = lsf_device_record(&factory.pool, node->owner,
        (struct lsf_prepaid_ticket){owner->irq_pci_birth.slot, owner->irq_pci_birth.generation},
        LSF_DEVICE_PCI);
    return pci && pci->deferred == LSF_PREPAID_PUBLISHED &&
        pci->bytes == owner->irq_pci_birth.bytes && owner->irq_pci_birth.role == LSF_DEVICE_PCI;
}

int lsf_node_irq_call_enter(struct irq_domain *domain, struct lsf_node_irq_call *call)
{
    struct lsf_node_parent *node;
    struct lsf_node_capacity *owner;
    struct lsf_prepaid_view *record, *pci;
    struct lsf_prepaid_ticket ticket;
    struct device *device;
    unsigned long base, at = (unsigned long)domain, flags;
    int result = -EOPNOTSUPP;

    if (!call)
        return -EINVAL;
    *call = (struct lsf_node_irq_call){0};
    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_irq_parent_locked();
    if (!node) {
        result = lsf_node_irq_unknown_parent_locked(domain);
        /* A malformed known Node never becomes an ordinary allocator caller. */
        goto out;
    }
    owner = &node->capacity;
    if (owner->irq_call && owner->irq_task == current)
        goto out; /* No nested domain can silently borrow another scope. */
    base = (unsigned long)page_address(factory.pages);
    if (at < base || at - base >= LSF_BACKING_BYTES) {
        result = 0;
        goto out;
    }
    record = lsf_q35_record_locked(domain, LSF_Q35_MSI_DOMAIN, &device, &ticket);
    if (!record || record->deferred != LSF_PREPAID_PUBLISHED ||
        !owner->pcpu_prepared || owner->irq_call || owner->irq_task ||
        owner->irq_generation || owner->irq_sysfs_desc.generation ||
        !lsf_node_capacity_open_locked(node) || !lsf_node_device_actor_current() ||
        !factory.device->constructor_active || factory.device->constructor_task != current ||
        record->owner != node->owner.slot || record->owner_generation != node->owner.generation ||
        !factory.pool.next_generation || factory.pool.next_generation == (u64)-1)
        goto out;
    pci = lsf_device_record(&factory.pool, node->owner,
        (struct lsf_prepaid_ticket){record->cache_bucket, record->cache_anchor}, LSF_DEVICE_PCI);
    if (!pci || pci->deferred != LSF_PREPAID_PUBLISHED)
        goto out;
    owner->irq_domain_birth = (struct lsf_node_native_ticket){ticket.slot,
        record->kind, ticket.generation, record->bytes, 64};
    owner->irq_pci_birth = (struct lsf_node_native_ticket){record->cache_bucket,
        LSF_DEVICE_PCI, record->cache_anchor, pci->bytes, 64};
    owner->irq_domain = domain;
    owner->irq_generation = factory.pool.next_generation++;
    call->generation = owner->irq_generation;
    /* The real reference slot is already inside the paid Node parent. A
     * task address cannot be recycled into this loan after a fatal exit.
     */
    get_task_struct(current);
    owner->irq_task = current;
    owner->irq_call = call;
    result = 1;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_irq_call_leave(struct lsf_node_irq_call *call)
{
    struct lsf_node_parent *node;
    struct lsf_node_capacity *owner;
    struct task_struct *task = NULL;
    unsigned long flags;
    int result = -EIO;

    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_irq_parent_locked();
    if (!node || !call)
        goto poison;
    owner = &node->capacity;
    if (owner->irq_call != call)
        goto poison;
    if (owner->irq_task == current && owner->irq_generation &&
        call->generation == owner->irq_generation && !owner->irq_sysfs_desc.generation &&
        !factory.pool.poisoned && !READ_ONCE(factory.uncertain)) {
        task = owner->irq_task;
        owner->irq_task = NULL;
        result = 0;
    }
    /* Always remove the matching caller's stack/domain aliases before return.
     * On unknown cleanup the paid real task reference stays quarantined; it
     * cannot authorize another enter or let a task-address ABA reuse the loan.
     */
    owner->irq_call = NULL;
    owner->irq_domain = NULL;
    owner->irq_generation = 0;
    owner->irq_domain_birth = (struct lsf_node_native_ticket){0};
    owner->irq_pci_birth = (struct lsf_node_native_ticket){0};
    owner->irq_sysfs_desc = (struct lsf_node_native_ticket){0};
    call->generation = 0;
    if (result)
        goto poison;
    spin_unlock_irqrestore(&pool_lock, flags);
    put_task_struct(task);
    return 0;
poison:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_irq_current_owner(struct lsf_node_capacity **copy)
{
    struct lsf_node_parent *node;
    unsigned long flags;
    int result = 0;

    if (!copy)
        return -EINVAL;
    *copy = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_irq_parent_locked();
    if (!node) {
        result = lsf_node_irq_unknown_parent_locked(NULL);
        goto out;
    }
    if (node && node->capacity.irq_call && node->capacity.irq_task == current) {
        result = -EOPNOTSUPP;
        if (lsf_node_irq_call_current_locked(node)) {
            *copy = &node->capacity;
            result = 1;
        }
    }
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

struct irq_domain *lsf_node_irq_current_domain(struct lsf_node_capacity *owner)
{
    struct lsf_node_parent *node;
    struct irq_domain *domain = NULL;
    unsigned long flags;

    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_capacity_parent_locked(owner);
    if (lsf_node_irq_call_current_locked(node))
        domain = (struct irq_domain *)owner->irq_domain;
    spin_unlock_irqrestore(&pool_lock, flags);
    return domain;
}

static int lsf_node_irq_device_owner_locked(struct irq_desc *desc,
    struct lsf_node_capacity **copy)
{
    struct lsf_node_parent *node;
    struct lsf_node_capacity *owner;
    struct lsf_prepaid_view *record, *pci, *domain;
    struct lsf_prepaid_ticket ticket;
    struct device *device;
    const struct lsf_node_native_ticket *saved;
    unsigned long base;
    unsigned int index;
    int result;

    lockdep_assert_held(&pool_lock);
    if (!copy)
        return -EINVAL;
    *copy = NULL;
    result = lsf_node_capacity_record_locked(desc, LSF_NODE_IRQ_DESC, &owner, &record);
    if (result != 1)
        goto out;
    result = -EOPNOTSUPP;
    node = lsf_node_capacity_parent_locked(owner);
    if (!lsf_node_capacity_open_locked(node) || !lsf_node_device_actor_current() ||
        !factory.device->constructor_active || factory.device->constructor_task != current ||
        record->deferred != LSF_PREPAID_PUBLISHED)
        goto out;
    for (index = 0; index < LSF_NODE_CAPACITY_VECTORS; ++index)
        if (owner->irq_descs[index] == desc)
            break;
    if (index == LSF_NODE_CAPACITY_VECTORS || !(owner->irq_claimed & BIT(index)))
        goto out;
    saved = &owner->irq_desc_pci[index];
    pci = lsf_device_record(&factory.pool, node->owner,
        (struct lsf_prepaid_ticket){saved->slot, saved->generation}, LSF_DEVICE_PCI);
    if (!pci || saved->role != LSF_DEVICE_PCI || pci->bytes != saved->bytes ||
        pci->deferred != LSF_PREPAID_PUBLISHED)
        goto out;
    saved = &owner->irq_desc_domain[index];
    if (saved->slot < 2 || saved->slot >= LSF_ALLOCATION_SLOTS)
        goto out;
    domain = &factory.pool.records[saved->slot];
    if (domain->phase != LSF_PREPAID_LIVE || domain->deferred != LSF_PREPAID_PUBLISHED ||
        domain->generation != saved->generation ||
        domain->kind != saved->role || domain->bytes != saved->bytes ||
        domain->cache_bucket != owner->irq_desc_pci[index].slot ||
        domain->cache_anchor != owner->irq_desc_pci[index].generation)
        goto out;
    base = (unsigned long)page_address(factory.pages);
    if (lsf_q35_record_locked((void *)(base + domain->offset), LSF_Q35_MSI_DOMAIN,
            &device, &ticket) != domain || ticket.slot != saved->slot ||
        ticket.generation != saved->generation)
        goto out;
    *copy = owner;
    result = 1;
out:
    return result;
}

int lsf_node_irq_device_owner(struct irq_desc *desc, struct lsf_node_capacity **copy)
{
    unsigned long flags;
    int result;

    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_node_irq_device_owner_locked(desc, copy);
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_irq_pci_owner(struct device *device, struct lsf_node_capacity **copy)
{
    struct lsf_node_parent *node;
    struct lsf_prepaid_ticket ticket;
    struct lsf_prepaid_view *pci;
    const void *address;
    unsigned long flags;
    int result;

    if (!copy)
        return -EINVAL;
    *copy = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_factory_device_core_parent(device, offsetof(struct pci_dev, dev),
        &ticket, &address);
    if (result != 1)
        goto out;
    result = -EOPNOTSUPP;
    node = lsf_node_irq_parent_locked();
    if (!lsf_node_capacity_open_locked(node) || !lsf_node_device_actor_current() ||
        !factory.device->constructor_active || factory.device->constructor_task != current)
        goto out;
    pci = lsf_device_record(&factory.pool, node->owner, ticket, LSF_DEVICE_PCI);
    if (!pci || pci->deferred != LSF_PREPAID_PUBLISHED ||
        pci->cache_bucket != node->capacity.device_root.slot ||
        pci->cache_anchor != node->capacity.device_root.generation)
        goto out;
    *copy = &node->capacity;
    result = 1;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Cleanup identity only. It lends no current actor, allocation, publication or
 * reopening authority. Original closed/queued PCI ownership survives native
 * free_irq and transport teardown until the actual child terminal fence. */
int lsf_node_irq_pci_original(struct device *device, struct lsf_node_capacity **copy)
{
    struct lsf_node_parent *node;
    struct lsf_prepaid_ticket ticket;
    struct lsf_prepaid_view *pci;
    const void *address;
    unsigned long flags;
    int result;

    if (!copy)
        return -EINVAL;
    *copy = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_factory_device_core_parent(device, offsetof(struct pci_dev, dev),
        &ticket, &address);
    if (result != 1)
        goto out;
    result = -EIO;
    node = lsf_node_irq_parent_locked();
    if (!node || !lsf_node_capacity_device_child_locked(node))
        goto out;
    pci = lsf_device_record(&factory.pool, node->owner, ticket, LSF_DEVICE_PCI);
    if (!pci || (pci->deferred != LSF_PREPAID_PUBLISHED &&
            pci->deferred != LSF_PREPAID_QUEUED) ||
        pci->cache_bucket != node->capacity.device_root.slot ||
        pci->cache_anchor != node->capacity.device_root.generation)
        goto out;
    *copy = &node->capacity;
    result = 1;
out:
    if (result < 0)
        lsf_factory_device_firmware_poison();
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_irq_sysfs_enter(struct irq_desc *desc)
{
    struct lsf_node_parent *node;
    struct lsf_node_capacity *owner;
    struct lsf_prepaid_view *record;
    unsigned long flags;
    unsigned int index;
    int result;

    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_node_capacity_record_locked(desc, LSF_NODE_IRQ_DESC, &owner, &record);
    if (result != 1)
        goto out;
    result = -EOPNOTSUPP;
    node = lsf_node_capacity_parent_locked(owner);
    if (!lsf_node_irq_call_current_locked(node) || owner->irq_sysfs_desc.generation ||
        record->deferred != LSF_PREPAID_PUBLISHED)
        goto out;
    for (index = 0; index < LSF_NODE_CAPACITY_VECTORS; ++index)
        if (owner->irq_descs[index] == desc)
            break;
    if (index == LSF_NODE_CAPACITY_VECTORS ||
        !lsf_node_irq_birth_equal(&owner->irq_desc_pci[index], &owner->irq_pci_birth) ||
        !lsf_node_irq_birth_equal(&owner->irq_desc_domain[index], &owner->irq_domain_birth))
        goto out;
    owner->irq_sysfs_desc = (struct lsf_node_native_ticket){record - factory.pool.records,
        LSF_NODE_IRQ_DESC, record->generation, record->bytes, 64};
    result = 1;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_irq_sysfs_leave(struct irq_desc *desc)
{
    struct lsf_node_parent *node;
    struct lsf_node_capacity *owner;
    struct lsf_prepaid_view *record;
    unsigned long flags;
    int result = -EIO;

    spin_lock_irqsave(&pool_lock, flags);
    if (lsf_node_capacity_record_locked(desc, LSF_NODE_IRQ_DESC, &owner, &record) != 1)
        goto poison;
    node = lsf_node_capacity_parent_locked(owner);
    if (node && owner->irq_call && owner->irq_task == current && owner->irq_generation &&
        owner->irq_sysfs_desc.slot == record - factory.pool.records &&
        owner->irq_sysfs_desc.generation == record->generation)
        result = 0;
    owner->irq_sysfs_desc = (struct lsf_node_native_ticket){0};
    if (result)
        goto poison;
    spin_unlock_irqrestore(&pool_lock, flags);
    return 0;
poison:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Classify only the selected real external descriptor allocations. The bank
 * still contains ordinary typed PCI/kernfs children handled by the old path.
 * Padding/interior/wrong-type pointers in a native extent never fall back.
 */
static int lsf_node_irq_kobject_record_locked(const void *object,
    struct lsf_node_capacity **owner, struct lsf_prepaid_view **record,
    unsigned int *desc_index)
{
    struct lsf_node_parent *node;
    struct lsf_prepaid_view *physical;
    unsigned long at = (unsigned long)object, offset;
    unsigned int slot, index;
    int covered = 0;

    lockdep_assert_held(&pool_lock);
    if (!factory.pages || !object)
        return 0;
    for (slot = 2; slot < LSF_ALLOCATION_SLOTS; ++slot) {
        physical = &factory.pool.records[slot];
        if (physical->phase != LSF_PREPAID_EMPTY &&
            physical->kind > LSF_NODE_CAPACITY_NATIVE_BASE &&
            physical->kind < LSF_NODE_CAPACITY_NATIVE_BASE + LSF_NODE_CAPACITY_ROLES &&
            physical->offset != LSF_NODE_CAPACITY_UNBOUND &&
            at >= physical->offset && at - physical->offset < physical->bytes)
            covered = 1;
    }
    if (!covered)
        return 0;
    node = lsf_node_irq_parent_locked();
    if (!node)
        return -EIO;
    offset = node->capacity.irq_kobject_offset;
    if (!offset || !node->capacity.irq_kobject_bytes || at < offset ||
        offset >= node->capacity.extent[LSF_NODE_IRQ_DESC].bytes ||
        node->capacity.irq_kobject_bytes > node->capacity.extent[LSF_NODE_IRQ_DESC].bytes - offset ||
        lsf_node_capacity_record_locked((void *)(at - offset), LSF_NODE_IRQ_DESC,
            owner, record) != 1 || *owner != &node->capacity ||
        ((*record)->deferred != LSF_PREPAID_PUBLISHED &&
         (*record)->deferred != LSF_PREPAID_QUEUED))
        return -EIO;
    for (index = 0; index < LSF_NODE_CAPACITY_VECTORS; ++index)
        if (node->capacity.irq_descs[index] == (void *)(at - offset))
            break;
    if (index == LSF_NODE_CAPACITY_VECTORS)
        return -EIO;
    *desc_index = index;
    return 1;
}

static int lsf_node_irq_kobject_source_locked(const void *object,
    struct lsf_device_registration_source *copy)
{
    struct lsf_node_capacity *owner;
    struct lsf_node_parent *node;
    struct lsf_prepaid_view *record, *pci;
    struct lsf_node_native_ticket *parent;
    unsigned long base;
    unsigned int index;
    int result = lsf_node_irq_kobject_record_locked(object, &owner, &record, &index);

    if (result != 1)
        return result;
    node = lsf_node_capacity_parent_locked(owner);
    if (!copy || !lsf_node_irq_call_current_locked(node) ||
        owner->irq_sysfs_desc.slot != record - factory.pool.records ||
        owner->irq_sysfs_desc.generation != record->generation)
        return -EOPNOTSUPP;
    parent = &owner->irq_desc_pci[index];
    if (parent->role != LSF_DEVICE_PCI ||
        !lsf_node_irq_birth_equal(parent, &owner->irq_pci_birth) ||
        !lsf_node_irq_birth_equal(&owner->irq_desc_domain[index], &owner->irq_domain_birth))
        return -EIO;
    pci = lsf_device_record(&factory.pool, node->owner,
        (struct lsf_prepaid_ticket){parent->slot, parent->generation}, LSF_DEVICE_PCI);
    if (!pci || pci->deferred != LSF_PREPAID_PUBLISHED || pci->bytes != parent->bytes)
        return -EIO;
    base = (unsigned long)page_address(factory.pages);
    *copy = (struct lsf_device_registration_source){
        .address = (void *)(base + pci->offset), .kind = LSF_DEVICE_PCI,
        .slot = parent->slot, .generation = parent->generation,
        .pci_slot = parent->slot, .pci_generation = parent->generation,
    };
    return 1;
}

int lsf_node_irq_kobject_owned(const struct kobject *object)
{
    struct lsf_node_capacity *owner;
    struct lsf_prepaid_view *record;
    unsigned long flags;
    unsigned int index;
    int result;

    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_node_irq_kobject_record_locked(object, &owner, &record, &index);
    if (result < 0) {
        factory.pool.poisoned = 1;
        WRITE_ONCE(factory.uncertain, 1);
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_irq_kobject_retain(const struct kobject *object)
{
    struct lsf_node_capacity *owner;
    struct lsf_prepaid_view *record;
    unsigned long flags;
    unsigned int index;
    int result;

    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_node_irq_kobject_record_locked(object, &owner, &record, &index);
    if (result) {
        factory.pool.poisoned = 1;
        WRITE_ONCE(factory.uncertain, 1);
        result = -EIO;
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_irq_kobject_current(const struct kobject *object)
{
    struct lsf_device_registration_source source;
    unsigned long flags;
    int result;

    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_node_irq_kobject_source_locked(object, &source);
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_irq_name_copy(struct irq_desc *desc, const char *text, char **copy)
{
    struct lsf_node_capacity *owner;
    struct lsf_prepaid_view *record, *member;
    struct lsf_device_registration_source source;
    struct lsf_prepaid_ticket ticket;
    unsigned long flags, base, at;
    const void *object;
    unsigned int index = LSF_NODE_CAPACITY_VECTORS, slot;
    int result;

    if (!copy)
        return -EINVAL;
    *copy = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_node_capacity_record_locked(desc, LSF_NODE_IRQ_DESC, &owner, &record);
    if (result == 1) {
        object = (void *)((unsigned long)desc + owner->irq_kobject_offset);
        result = lsf_node_irq_kobject_source_locked(object, &source);
        for (index = 0; index < LSF_NODE_CAPACITY_VECTORS; ++index)
            if (owner->irq_descs[index] == desc)
                break;
        if (index == LSF_NODE_CAPACITY_VECTORS || owner->irq_names[index].generation)
            result = -EOPNOTSUPP;
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    if (result != 1)
        return -EOPNOTSUPP;
    *copy = lsf_factory_device_sysfs_name(source, text);
    if (!*copy)
        return -ENOMEM;
    spin_lock_irqsave(&pool_lock, flags);
    base = (unsigned long)page_address(factory.pages);
    at = (unsigned long)*copy;
    result = -EIO;
    if (at < base || at - base >= LSF_BACKING_BYTES)
        goto retain;
    for (slot = 2; slot < LSF_ALLOCATION_SLOTS; ++slot) {
        member = &factory.pool.records[slot];
        if (member->kind != LSF_DEVICE_KERNFS_NAME || member->offset != at - base)
            continue;
        ticket = (struct lsf_prepaid_ticket){slot, member->generation};
        if (lsf_device_record(&factory.pool,
                (struct lsf_prepaid_key){record->owner, record->owner_generation},
                ticket, LSF_DEVICE_KERNFS_NAME) != member ||
            member->cache_bucket != source.pci_slot || member->cache_anchor != source.pci_generation ||
            owner->irq_names[index].generation)
            goto retain;
        /* Capture the actual allocation identity before a later currentness
         * refusal. A different same-PCI name is never accepted at final put.
         */
        owner->irq_names[index] = (struct lsf_node_native_ticket){slot,
            LSF_DEVICE_KERNFS_NAME, member->generation, member->bytes, 64};
        if (!lsf_node_irq_call_current_locked(lsf_node_capacity_parent_locked(owner))) {
            *copy = NULL;
            if (!lsf_device_queue(&factory.pool,
                    (struct lsf_prepaid_key){record->owner, record->owner_generation},
                    ticket, LSF_DEVICE_KERNFS_NAME) ||
                !lsf_device_finish(&factory.pool,
                    (struct lsf_prepaid_key){record->owner, record->owner_generation},
                    ticket, LSF_DEVICE_KERNFS_NAME))
                goto retain;
            result = -EOPNOTSUPP;
        } else {
            result = 0;
        }
        spin_unlock_irqrestore(&pool_lock, flags);
        return result;
    }
retain:
    *copy = NULL;
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_irq_name_capture(const struct kobject *object, const char *name,
    struct lsf_node_irq_name *copy)
{
    struct lsf_node_capacity *owner;
    struct lsf_prepaid_view *desc, *pci, *member;
    struct lsf_node_native_ticket *parent;
    struct lsf_prepaid_ticket ticket;
    unsigned long base, at = (unsigned long)name, flags;
    unsigned int index, slot;
    int result;

    if (!copy)
        return -EINVAL;
    *copy = (struct lsf_node_irq_name){0};
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_node_irq_kobject_record_locked(object, &owner, &desc, &index);
    if (result != 1 || !name)
        goto out;
    result = -EIO;
    parent = &owner->irq_desc_pci[index];
    pci = lsf_device_record(&factory.pool,
        (struct lsf_prepaid_key){desc->owner, desc->owner_generation},
        (struct lsf_prepaid_ticket){parent->slot, parent->generation}, LSF_DEVICE_PCI);
    base = (unsigned long)page_address(factory.pages);
    if (parent->role != LSF_DEVICE_PCI || !pci || pci->bytes != parent->bytes ||
        (pci->deferred != LSF_PREPAID_PUBLISHED && pci->deferred != LSF_PREPAID_QUEUED) ||
        at < base || at - base >= LSF_BACKING_BYTES)
        goto out;
    for (slot = 2; slot < LSF_ALLOCATION_SLOTS; ++slot) {
        member = &factory.pool.records[slot];
        if (member->kind != LSF_DEVICE_KERNFS_NAME || member->offset != at - base)
            continue;
        ticket = (struct lsf_prepaid_ticket){slot, member->generation};
        if (slot != owner->irq_names[index].slot ||
            member->generation != owner->irq_names[index].generation ||
            owner->irq_names[index].role != LSF_DEVICE_KERNFS_NAME ||
            member->bytes != owner->irq_names[index].bytes ||
            lsf_device_record(&factory.pool,
                (struct lsf_prepaid_key){desc->owner, desc->owner_generation},
                ticket, LSF_DEVICE_KERNFS_NAME) != member ||
            member->cache_bucket != parent->slot || member->cache_anchor != parent->generation ||
            !lsf_device_queue(&factory.pool,
                (struct lsf_prepaid_key){desc->owner, desc->owner_generation},
                ticket, LSF_DEVICE_KERNFS_NAME))
            goto out;
        *copy = (struct lsf_node_irq_name){parent->slot, slot,
            parent->generation, member->generation};
        result = 1;
        break;
    }
out:
    if (result < 0) {
        factory.pool.poisoned = 1;
        WRITE_ONCE(factory.uncertain, 1);
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_irq_name_finish(struct lsf_node_irq_name copy, const char *name)
{
    struct lsf_node_parent *node;
    struct lsf_prepaid_view *pci, *member;
    unsigned long flags, base;
    int result = -EIO;

    if (!name && !copy.name_slot)
        return 0;
    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_irq_parent_locked();
    if (!node || copy.name_slot < 2 || copy.name_slot >= LSF_ALLOCATION_SLOTS)
        goto poison;
    pci = lsf_device_record(&factory.pool, node->owner,
        (struct lsf_prepaid_ticket){copy.pci_slot, copy.pci_generation}, LSF_DEVICE_PCI);
    member = lsf_device_record(&factory.pool, node->owner,
        (struct lsf_prepaid_ticket){copy.name_slot, copy.name_generation}, LSF_DEVICE_KERNFS_NAME);
    base = (unsigned long)page_address(factory.pages);
    if (!pci || !member || member->deferred != LSF_PREPAID_QUEUED ||
        member->cache_bucket != copy.pci_slot || member->cache_anchor != copy.pci_generation ||
        (unsigned long)name < base || member->offset != (unsigned long)name - base ||
        !lsf_device_finish(&factory.pool, node->owner,
            (struct lsf_prepaid_ticket){copy.name_slot, copy.name_generation}, LSF_DEVICE_KERNFS_NAME))
        goto poison;
    result = 0;
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
poison:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
