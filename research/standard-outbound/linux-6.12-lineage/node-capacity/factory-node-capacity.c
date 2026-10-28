/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in the separately compiled Node image after its parent definition.
 * The original bank plus real per-role native allocator outputs share the
 * SAME original one-MiB admission. Existing fixed records, owner slot and
 * generation are the only registrar. No additional general bank is created.
 * This allocator context is not a NodeFunding or NodeRetired producer.
 */
#include <net/lsf_node_capacity_private.h>
#include <linux/overflow.h>
#include <linux/maple_tree.h>
#ifndef LSF_STREAM_NODE_CAPACITY_IMAGE
#error "Node native capacity requires its distinct compiled image"
#endif
static_assert(LSF_NODE_PARENT_KIND == LSF_NODE_CAPACITY_PARENT_KIND);

static int lsf_node_capacity_record_locked(const void *address,
    enum lsf_node_capacity_role role, struct lsf_node_capacity **owner,
    struct lsf_prepaid_view **found);
static int lsf_node_irq_call_current_locked(struct lsf_node_parent *node);
static int lsf_node_radix_shared_record_locked(struct lsf_node_capacity *owner,
    struct lsf_prepaid_view *record);

static struct lsf_node_parent *lsf_node_capacity_parent_locked(
    const struct lsf_node_capacity *capacity)
{
    struct lsf_node_parent *node;
    struct lsf_prepaid_view *parent;
    struct lsf_prepaid_context *context;
    unsigned long base, extent = ALIGN(sizeof(*node), 64);

    lockdep_assert_held(&pool_lock);
    if (!factory.pages || !factory.opened || !factory.pool.initialized)
        return NULL;
    base = (unsigned long)page_address(factory.pages);
    node = (void *)(base + LSF_FACTORY_INFRA_OFFSET);
    /* An arbitrary pointer is only compared here; no caller payload is read. */
    if (capacity != &node->capacity)
        return NULL;
    parent = &factory.pool.records[1];
    context = &factory.pool.contexts[LSF_DEVICE_OWNER_SLOT];
    if (parent->phase != LSF_PREPAID_LIVE ||
        parent->kind != LSF_NODE_PARENT_KIND || !parent->generation ||
        parent->owner != LSF_DEVICE_OWNER_SLOT ||
        parent->owner_generation != context->generation || !context->generation ||
        parent->offset != LSF_FACTORY_INFRA_OFFSET || parent->bytes != extent ||
        parent->cache_bucket || parent->cache_anchor)
        return NULL;
    /* The complete parent extent and original context precede these reads. */
    if (node->owner.slot != LSF_DEVICE_OWNER_SLOT ||
        node->owner.generation != context->generation ||
        node->record.slot != 1u || node->record.generation != parent->generation)
        return NULL;
    return node;
}

static int lsf_node_capacity_device_child_locked(struct lsf_node_parent *node)
{
    const struct lsf_node_native_ticket *ticket;
    struct lsf_prepaid_view *record;
    struct lsf_factory_device_state *state;
    unsigned long base, extent = ALIGN(sizeof(*state), 64);

    lockdep_assert_held(&pool_lock);
    if (!node)
        return 0;
    ticket = &node->capacity.device_root;
    if (!ticket->slot)
        return !ticket->generation && !factory.device;
    if (ticket->slot < 2 || ticket->slot >= LSF_ALLOCATION_SLOTS ||
        ticket->role != LSF_DEVICE_ROOT || !ticket->generation ||
        ticket->bytes != extent || ticket->alignment != 64)
        return 0;
    record = &factory.pool.records[ticket->slot];
    if ((record->phase != LSF_PREPAID_LIVE && record->phase != LSF_PREPAID_RETURNED) ||
        record->generation != ticket->generation ||
        record->kind != LSF_DEVICE_ROOT || record->owner != node->owner.slot ||
        record->owner_generation != node->owner.generation ||
        record->cache_bucket != node->record.slot ||
        record->cache_anchor != node->record.generation ||
        record->bytes != extent || record->offset % 64 ||
        record->offset < LSF_FACTORY_INFRA_OFFSET + ALIGN(sizeof(*node), 64) ||
        record->offset - LSF_FACTORY_INFRA_OFFSET > LSF_FACTORY_INFRA_BYTES ||
        extent > LSF_FACTORY_INFRA_BYTES - (record->offset - LSF_FACTORY_INFRA_OFFSET))
        return 0;
    if (!factory.device)
        return record->deferred == LSF_PREPAID_PRIVATE || record->phase == LSF_PREPAID_RETURNED;
    base = (unsigned long)page_address(factory.pages);
    state = (void *)(base + record->offset);
    if (factory.device != state ||
        (record->deferred != LSF_PREPAID_PUBLISHED &&
         record->deferred != LSF_PREPAID_QUEUED && record->phase != LSF_PREPAID_RETURNED))
        return 0;
    /* Only the exact original bank view is dereferenced. This is a new child,
     * never an existing DeviceRoot adopted as the Node or a second context.
     */
    return state->key.slot == node->owner.slot &&
        state->key.generation == node->owner.generation &&
        state->root.slot == ticket->slot && state->root.generation == ticket->generation;
}

static int lsf_node_capacity_open_locked(struct lsf_node_parent *node)
{
    struct lsf_prepaid_context *context;

    if (!node || !lsf_node_capacity_device_child_locked(node) ||
        factory.pool.poisoned || factory.pool.stopped ||
        READ_ONCE(factory.uncertain))
        return 0;
    context = &factory.pool.contexts[node->owner.slot];
    return !context->poisoned && !context->closed && !node->capacity.device_closed &&
        (!factory.device ||
         (factory.pool.records[node->capacity.device_root.slot].phase == LSF_PREPAID_LIVE &&
          factory.pool.records[node->capacity.device_root.slot].deferred == LSF_PREPAID_PUBLISHED)) &&
        node->state == LSF_NODE_ATTACHED_UNQUALIFIED && node->expires_ns &&
        ktime_get_ns() < node->expires_ns;
}

/* Selected-image front gate for existing DeviceRoot allocation helpers. The
 * ordinary image is byte-exact. A Node child retains the original Node expiry
 * and close fence; package/device metadata cannot create a fresh grant.
 */
static int lsf_node_device_admission_current(struct lsf_prepaid *pool,
    struct lsf_prepaid_key key)
{
    struct lsf_node_parent *node;
    unsigned long base;

    lockdep_assert_held(&pool_lock);
    if (pool != &factory.pool)
        return 0;
    if (pool->records[1].kind != LSF_NODE_PARENT_KIND)
        return 1;
    if (!factory.pages)
        return 0;
    base = (unsigned long)page_address(factory.pages);
    node = (void *)(base + LSF_FACTORY_INFRA_OFFSET);
    node = lsf_node_capacity_parent_locked(&node->capacity);
    return node && key.slot == node->owner.slot &&
        key.generation == node->owner.generation && lsf_node_capacity_open_locked(node);
}

static int lsf_node_device_actor_current(void)
{
    struct lsf_node_parent *node;
    unsigned long base;

    /* All original core_actor callers hold pool_lock. No extra actor get,
     * global alias ownership or retrospective adoption is introduced here.
     */
    lockdep_assert_held(&pool_lock);
    if (!factory.pages || !factory.opened)
        return 0;
    base = (unsigned long)page_address(factory.pages);
    node = (void *)(base + LSF_FACTORY_INFRA_OFFSET);
    node = lsf_node_capacity_parent_locked(&node->capacity);
    return lsf_node_capacity_open_locked(node) && current->nsproxy &&
        node->mm == current->mm && node->tgid == task_tgid(current) &&
        node->cred == current_cred() && node->net == current->nsproxy->net_ns;
}

static int lsf_node_device_child_close(struct lsf_prepaid *pool,
    struct lsf_prepaid_key key)
{
    struct lsf_node_parent *node;
    unsigned long base;

    lockdep_assert_held(&pool_lock);
    if (pool != &factory.pool)
        return -1;
    if (pool->records[1].kind != LSF_NODE_PARENT_KIND)
        return 0;
    if (!factory.pages)
        return -1;
    base = (unsigned long)page_address(factory.pages);
    node = (void *)(base + LSF_FACTORY_INFRA_OFFSET);
    node = lsf_node_capacity_parent_locked(&node->capacity);
    if (!node || !node->capacity.device_root.slot ||
        !lsf_node_capacity_device_child_locked(node) ||
        key.slot != node->owner.slot || key.generation != node->owner.generation)
        return -1;
    node->capacity.device_closed = 1;
    return 1; /* Seal this child, NOT the original Node context. */
}

static int lsf_node_shared_record_locked(struct lsf_node_parent *node,
    struct lsf_prepaid_view *record)
{
    struct lsf_node_capacity *actual;
    struct lsf_prepaid_view *found;
    enum lsf_node_capacity_role role;
    unsigned int index;
    int matched = 0;

    if (record->offset == LSF_NODE_CAPACITY_UNBOUND)
        return 0;
    if (record->kind > LSF_NODE_CAPACITY_NATIVE_BASE &&
        record->kind <= LSF_NODE_CAPACITY_NATIVE_BASE + LSF_NODE_MAPLE_PAGE) {
        role = record->kind - LSF_NODE_CAPACITY_NATIVE_BASE;
        if (role == LSF_NODE_PCPU_STAT)
            return 0;
    } else if (record->kind == LSF_NODE_CAPACITY_NATIVE_BASE + LSF_NODE_SMALL_PAGE) {
        role = LSF_NODE_SMALL_PAGE;
    } else if (record->kind == LSF_NODE_CAPACITY_KIND_BASE + LSF_NODE_IRQ_DESC) {
        if (record->deferred != LSF_PREPAID_PRIVATE)
            return 0;
        role = LSF_NODE_IRQ_DESC;
        for (index = 0; index < LSF_NODE_CAPACITY_VECTORS; ++index)
            if (node->capacity.irq_descs[index] == (void *)(unsigned long)record->offset &&
                !(node->capacity.irq_claimed & BIT(index)) &&
                !(node->capacity.irq_returned & BIT(index)))
                matched++;
        if (matched != 1)
            return 0;
    } else if (record->kind == LSF_NODE_CAPACITY_KIND_BASE + LSF_NODE_IRQ_PARENT_DATA ||
        record->kind == LSF_NODE_CAPACITY_KIND_BASE + LSF_NODE_IRQ_APIC) {
        if (record->deferred != LSF_PREPAID_PRIVATE)
            return 0;
        role = record->kind - LSF_NODE_CAPACITY_KIND_BASE;
        for (index = 0; index < LSF_NODE_CAPACITY_VECTORS; ++index) {
            const void *address = role == LSF_NODE_IRQ_PARENT_DATA ?
                node->capacity.irq_parent_data[index] : node->capacity.irq_apic[index];
            unsigned int claimed = role == LSF_NODE_IRQ_PARENT_DATA ?
                node->capacity.irq_parent_claimed : node->capacity.irq_apic_claimed;
            unsigned int returned = role == LSF_NODE_IRQ_PARENT_DATA ?
                node->capacity.irq_parent_returned : node->capacity.irq_apic_returned;
            if (address == (void *)(unsigned long)record->offset &&
                !(claimed & BIT(index)) && !(returned & BIT(index)))
                matched++;
        }
        if (matched != 1)
            return 0;
    } else if (record->kind == LSF_NODE_CAPACITY_KIND_BASE + LSF_NODE_IRQ_ACTION) {
        if (record->deferred != LSF_PREPAID_PRIVATE)
            return 0;
        role = LSF_NODE_IRQ_ACTION;
        for (index = 0; index < LSF_NODE_CAPACITY_VECTORS; ++index)
            if (node->capacity.irq_actions[index] == (void *)(unsigned long)record->offset &&
                !(node->capacity.irq_action_claimed & BIT(index)) &&
                !(node->capacity.irq_action_returned & BIT(index)))
                matched++;
        if (matched != 1)
            return 0;
    } else if (record->kind == LSF_NODE_CAPACITY_KIND_BASE + LSF_NODE_RADIX_SHARED) {
        role = LSF_NODE_RADIX_SHARED;
        if (!lsf_node_radix_shared_record_locked(&node->capacity, record))
            return 0;
    } else if (record->kind == LSF_NODE_CAPACITY_KIND_BASE + LSF_NODE_MAPLE_NODE) {
        role = LSF_NODE_MAPLE_NODE;
    } else if (record->kind == LSF_NODE_CAPACITY_KIND_BASE + LSF_NODE_PCPU_STAT) {
        if (record->deferred != LSF_PREPAID_PRIVATE)
            return 0;
        role = LSF_NODE_PCPU_STAT;
        for (index = 0; index < LSF_NODE_CAPACITY_VECTORS; ++index)
            if (node->capacity.pcpu_stat_backing[index] == (void *)(unsigned long)record->offset &&
                !(node->capacity.pcpu_claimed & BIT(index)) &&
                !(node->capacity.pcpu_returned & BIT(index)))
                matched++;
        if (matched != 1)
            return 0;
    } else {
        return 0; /* Future/unknown roles cannot silently become Node-shared. */
    }
    return lsf_node_capacity_record_locked((void *)(unsigned long)record->offset,
        role, &actual, &found) == 1 && actual == &node->capacity && found == record;
}

static int lsf_node_device_child_quiescent(struct lsf_prepaid *pool,
    struct lsf_prepaid_key key, struct lsf_prepaid_ticket ticket, unsigned int queued)
{
    struct lsf_node_parent *node;
    struct lsf_prepaid_context *context;
    struct lsf_prepaid_view *record;
    unsigned long base;
    unsigned int index, live = 0, continuations = 0;

    lockdep_assert_held(&pool_lock);
    if (pool != &factory.pool || !factory.pages || queued > 1)
        return 0;
    base = (unsigned long)page_address(factory.pages);
    node = (void *)(base + LSF_FACTORY_INFRA_OFFSET);
    node = lsf_node_capacity_parent_locked(&node->capacity);
    if (!node || !lsf_node_capacity_device_child_locked(node) ||
        key.slot != node->owner.slot || key.generation != node->owner.generation ||
        ticket.slot != node->capacity.device_root.slot ||
        ticket.generation != node->capacity.device_root.generation)
        return 0;
    context = &pool->contexts[key.slot];
    if ((!context->closed && !node->capacity.device_closed) || context->poisoned ||
        node->capacity.active_mas || node->capacity.mas_task || node->capacity.mas_generation ||
        node->capacity.irq_call || node->capacity.irq_task || node->capacity.irq_generation ||
        node->capacity.irq_sysfs_desc.generation || node->capacity.small_allocating)
        return 0;
    for (index = 1; index < LSF_ALLOCATION_SLOTS; ++index) {
        record = &pool->records[index];
        if (record->owner != key.slot || record->owner_generation != key.generation ||
            record->phase != LSF_PREPAID_LIVE)
            continue;
        if (index != node->record.slot && index != ticket.slot &&
            !lsf_node_shared_record_locked(node, record))
            return 0;
        if (record->deferred == LSF_PREPAID_QUEUED)
            continuations++;
        live++;
    }
    /* Node-shared VM/percpu/Maple carriers and their callbacks retain their
     * ORIGINAL Node owner. Device-specific descendants must all be returned.
     * Child retirement neither refunds nor reparents that retained capacity.
     */
    return live == context->live && live >= 2 && continuations == context->continuations &&
        (pool->records[ticket.slot].deferred == LSF_PREPAID_QUEUED) == queued;
}

static int lsf_node_capacity_device_prepare(struct lsf_node_capacity *owner)
{
    struct lsf_node_parent *node;
    struct lsf_factory_device_state *state;
    struct lsf_prepaid_context *context;
    struct lsf_prepaid_view *record;
    struct lsf_prepaid_ticket ticket;
    unsigned long flags, extent = ALIGN(sizeof(*state), 64);
    unsigned int slot;
    int result = -EOPNOTSUPP;

    lockdep_assert_held(&factory_lock);
    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_capacity_parent_locked(owner);
    if (!lsf_node_capacity_open_locked(node) || factory.device || owner->device_root.slot ||
        __alignof__(*state) > 64 || extent > LSF_FACTORY_INFRA_BYTES ||
        !factory.pool.next_generation || factory.pool.next_generation == (u64)-1)
        goto out;
    context = &factory.pool.contexts[node->owner.slot];
    if (context->cursor != ALIGN(sizeof(*node), 64) ||
        extent > LSF_FACTORY_INFRA_BYTES - context->cursor)
        goto out;
    for (slot = 2; slot < LSF_ALLOCATION_SLOTS; ++slot)
        if (factory.pool.records[slot].phase == LSF_PREPAID_EMPTY)
            break;
    if (slot == LSF_ALLOCATION_SLOTS)
        goto out;
    record = &factory.pool.records[slot];
    *record = (struct lsf_prepaid_view){
        .generation = factory.pool.next_generation++,
        .owner_generation = node->owner.generation,
        .offset = LSF_FACTORY_INFRA_OFFSET + context->cursor, .bytes = extent,
        .owner = node->owner.slot, .phase = LSF_PREPAID_LIVE, .kind = LSF_DEVICE_ROOT,
        .deferred = LSF_PREPAID_PRIVATE,
        .cache_bucket = node->record.slot, .cache_anchor = node->record.generation,
    };
    context->cursor += extent;
    context->live++;
    ticket = (struct lsf_prepaid_ticket){slot, record->generation};
    owner->device_root = (struct lsf_node_native_ticket){slot, LSF_DEVICE_ROOT,
        record->generation, extent, 64};
    /* Original view and parent precede memset, reference slots and publication.
     * No context_create, bank acquisition or existing DeviceRoot is reused.
     */
    state = (void *)((char *)page_address(factory.pages) + record->offset);
    memset(state, 0, sizeof(*state));
    state->key = node->owner;
    state->root = ticket;
    if (!lsf_node_capacity_open_locked(node) ||
        !lsf_device_publish(&factory.pool, node->owner, ticket, LSF_DEVICE_ROOT))
        goto out;
    factory.device = state;
    result = 0;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_capacity_checkpoint(struct lsf_node_capacity *owner)
{
    struct lsf_node_parent *node;
    unsigned long flags;
    int result;

    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_capacity_parent_locked(owner);
    result = lsf_node_capacity_open_locked(node) ? 0 : -EOPNOTSUPP;
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* A cleanup loan is a borrowed obligation of one actual published descriptor,
 * not a second admission mode or a saved caller assertion. All provenance is
 * rechecked under the original registrar lock. The real sparse-IRQ caller
 * binds this only after proving its exact current tree entry under that tree's
 * native mutex. No stack alias is retained after that native call returns.
 */
static int lsf_node_capacity_cleanup_live_locked(struct lsf_node_parent *node)
{
    struct lsf_node_capacity *owner;
    struct lsf_node_capacity *actual;
    struct lsf_prepaid_context *context;
    struct lsf_prepaid_view *record, *found;
    const struct lsf_node_native_ticket *origin;

    lockdep_assert_held(&pool_lock);
    if (!node || factory.pool.poisoned || READ_ONCE(factory.uncertain))
        return 0;
    owner = &node->capacity;
    origin = &owner->cleanup_origin;
    if (!owner->pcpu_prepared || !owner->active_mas || owner->mas_task != current ||
        !owner->mas_generation || origin->role != LSF_NODE_IRQ_DESC ||
        origin->slot < 2 || origin->slot >= LSF_ALLOCATION_SLOTS || !origin->generation ||
        origin->alignment != 64)
        return 0;
    context = &factory.pool.contexts[node->owner.slot];
    record = &factory.pool.records[origin->slot];
    return !context->poisoned && record->offset != LSF_NODE_CAPACITY_UNBOUND &&
        lsf_node_capacity_record_locked((void *)(unsigned long)record->offset,
            LSF_NODE_IRQ_DESC, &actual, &found) == 1 && actual == owner && found == record &&
        record->generation == origin->generation &&
        record->deferred == LSF_PREPAID_PUBLISHED &&
        record->bytes == origin->bytes;
}

static int lsf_node_capacity_maple_allowed_locked(struct lsf_node_parent *node)
{
    return lsf_node_capacity_open_locked(node) || lsf_node_capacity_cleanup_live_locked(node);
}

int lsf_node_capacity_maple_checkpoint(struct lsf_node_capacity *owner)
{
    struct lsf_node_parent *node;
    unsigned long flags;
    int result;

    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_capacity_parent_locked(owner);
    result = lsf_node_capacity_maple_allowed_locked(node) ? 0 : -EOPNOTSUPP;
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_capacity_begin(struct lsf_node_capacity *owner)
{
    struct lsf_node_parent *node;
    unsigned long flags;
    unsigned int role;
    int error = -EOPNOTSUPP;

    /* The real allocating-TU caller holds pcpu_alloc_mutex and the native
     * possible-CPU read lock. This factory serialization spans the entire
     * transaction; no second actor can rewrite its geometry or renew expiry.
     */
    lockdep_assert_held(&factory_lock);
    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_capacity_parent_locked(owner);
    if (!lsf_node_capacity_open_locked(node) || owner->started)
        goto unlock;
    owner->started = 1;
    owner->extent[LSF_NODE_SMALL_PAGE] = (struct lsf_node_capacity_extent){PAGE_SIZE, PAGE_SIZE};
    spin_unlock_irqrestore(&pool_lock, flags);
    error = lsf_node_capacity_device_prepare(owner);
    if (!error)
        error = lsf_node_pcpu_layout(owner);
    if (!error)
        error = lsf_node_vm_layout(owner->extent);
    if (!error)
        error = lsf_node_maple_layout(owner->extent);
    if (!error)
        error = lsf_node_irq_layout(owner);
    if (!error)
        error = lsf_node_irqdomain_layout(owner->extent);
    if (!error)
        error = lsf_node_radix_layout(owner->extent);
    if (!error)
        error = lsf_node_vector_layout(owner->extent);
    if (!error)
        error = lsf_node_irq_action_layout(owner->extent);
    if (!error)
        error = lsf_node_irq_proc_layout(owner->extent);
    if (!error)
        error = lsf_node_irq_proc_name_layout(owner->extent);
    if (error)
        return error; /* Irreversible attempt; original custody stays retained. */
    for (role = 1; role < LSF_NODE_CAPACITY_ROLES; ++role) {
        const struct lsf_node_capacity_extent *extent = &owner->extent[role];
        if (!extent->bytes && role == LSF_NODE_PCPU_EXTENSIONS)
            continue;
        if (!extent->bytes || !is_power_of_2(extent->alignment) ||
            extent->alignment > PAGE_SIZE || extent->bytes > LSF_BOOTSTRAP_CEILING)
            return -EOPNOTSUPP;
    }
    return lsf_node_capacity_checkpoint(owner);
unlock:
    spin_unlock_irqrestore(&pool_lock, flags);
    return error;
}

static unsigned long lsf_node_native_bootstrap_bytes(void);

int lsf_node_capacity_reserve(struct lsf_node_capacity *owner,
    enum lsf_node_capacity_role role, struct lsf_node_native_ticket *ticket)
{
    struct lsf_node_parent *node;
    struct lsf_prepaid_context *context;
    struct lsf_prepaid_view *record, *prior;
    unsigned long flags, cost, used, floor, bytes, alignment;
    unsigned int slot, scan;
    int result = -EOPNOTSUPP;

    if (!ticket || !in_task() || in_atomic() || irqs_disabled())
        return result;
    floor = lsf_node_native_bootstrap_bytes();
    if (floor > LSF_BOOTSTRAP_CEILING)
        return result;
    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_capacity_parent_locked(owner);
    if ((!lsf_node_capacity_open_locked(node) &&
            !(role == LSF_NODE_MAPLE_PAGE && lsf_node_capacity_cleanup_live_locked(node))) || role <= 0 ||
        role >= LSF_NODE_CAPACITY_ROLES || lsf_node_small_role(role) || role == LSF_NODE_PCPU_STAT ||
        role == LSF_NODE_MAPLE_NODE ||
        !owner->started || !factory.pool.next_generation ||
        factory.pool.next_generation == (u64)-1)
        goto out;
    bytes = owner->extent[role].bytes;
    alignment = owner->extent[role].alignment;
    if (!bytes || bytes > LSF_BOOTSTRAP_CEILING ||
        !is_power_of_2(alignment) || alignment > PAGE_SIZE)
        goto out;
    cost = PAGE_SIZE << get_order(bytes);
    /* Existing bank/metadata floor and actual native physical reservations
     * share ONE ceiling. Returned or failed reservations stay charged; no
     * independent counter, slot reuse or unproved physical refund exists.
     */
    used = floor;
    for (scan = 2; scan < LSF_ALLOCATION_SLOTS; ++scan) {
        prior = &factory.pool.records[scan];
        if (prior->phase == LSF_PREPAID_EMPTY ||
            prior->kind <= LSF_NODE_CAPACITY_NATIVE_BASE ||
            prior->kind >= LSF_NODE_CAPACITY_NATIVE_BASE + LSF_NODE_CAPACITY_ROLES)
            continue;
        if (prior->owner != node->owner.slot ||
            prior->owner_generation != node->owner.generation ||
            prior->cache_bucket != node->record.slot ||
            prior->cache_anchor != node->record.generation ||
            prior->bytes > LSF_BOOTSTRAP_CEILING - used)
            goto out;
        used += prior->bytes;
    }
    if (cost > LSF_BOOTSTRAP_CEILING - used)
        goto out;
    for (slot = 2; slot < LSF_ALLOCATION_SLOTS; ++slot)
        if (factory.pool.records[slot].phase == LSF_PREPAID_EMPTY)
            break;
    if (slot == LSF_ALLOCATION_SLOTS)
        goto out;
    record = &factory.pool.records[slot];
    *record = (struct lsf_prepaid_view){
        .generation = factory.pool.next_generation++,
        .owner_generation = node->owner.generation,
        .offset = LSF_NODE_CAPACITY_UNBOUND,
        .bytes = cost,
        .owner = node->owner.slot,
        .phase = LSF_PREPAID_LIVE,
        .kind = LSF_NODE_CAPACITY_NATIVE_BASE + role,
        .deferred = LSF_PREPAID_PRIVATE,
        .cache_bucket = node->record.slot,
        .cache_anchor = node->record.generation,
    };
    context = &factory.pool.contexts[node->owner.slot];
    context->live++;
    *ticket = (struct lsf_node_native_ticket){slot, role, record->generation,
        cost, alignment};
    result = 0;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_capacity_commit(struct lsf_node_capacity *owner,
    const struct lsf_node_native_ticket *ticket, const void *address)
{
    struct lsf_node_parent *node;
    struct lsf_prepaid_view *record;
    struct lsf_prepaid_context *context;
    unsigned long flags;
    int result = -EIO;

    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_capacity_parent_locked(owner);
    if (!node || !ticket || ticket->slot < 2 || ticket->slot >= LSF_ALLOCATION_SLOTS ||
        ticket->role <= 0 || ticket->role >= LSF_NODE_CAPACITY_ROLES ||
        ticket->role == LSF_NODE_PCPU_STAT || ticket->role == LSF_NODE_MAPLE_NODE)
        goto poison;
    record = &factory.pool.records[ticket->slot];
    if (record->generation != ticket->generation || record->phase != LSF_PREPAID_LIVE ||
        record->kind != LSF_NODE_CAPACITY_NATIVE_BASE + ticket->role ||
        record->offset != LSF_NODE_CAPACITY_UNBOUND || record->bytes != ticket->bytes ||
        record->owner != node->owner.slot ||
        record->owner_generation != node->owner.generation ||
        record->cache_bucket != node->record.slot ||
        record->cache_anchor != node->record.generation)
        goto poison;
    context = &factory.pool.contexts[node->owner.slot];
    /* Capture the actual result before checking stop/expiry. A failed
     * currentness check cannot lose an allocated page or certify no birth.
     */
    if (address) {
        record->offset = (unsigned long)address;
        if (!is_power_of_2(owner->extent[ticket->role].alignment) ||
            owner->extent[ticket->role].alignment > PAGE_SIZE ||
            (unsigned long)address % PAGE_SIZE ||
            (unsigned long)address % owner->extent[ticket->role].alignment)
            goto poison;
    } else {
        record->phase = LSF_PREPAID_RETURNED;
        if (!context->live)
            goto poison;
        context->live--;
    }
    result = (lsf_node_capacity_open_locked(node) ||
        (ticket->role == LSF_NODE_MAPLE_PAGE && lsf_node_capacity_cleanup_live_locked(node)))
        ? 0 : -EOPNOTSUPP;
    goto out;
poison:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void *lsf_node_capacity_take(struct lsf_node_capacity *owner,
    enum lsf_node_capacity_role role, unsigned long bytes,
    unsigned long alignment)
{
    struct lsf_node_native_ticket ticket;
    struct page *page;
    unsigned long flags;
    void *address;

    if (lsf_node_small_role(role))
        return lsf_node_capacity_small_take(owner, role, bytes, alignment);
    /* Page-table allocating TUs must call their real native constructors
     * between reserve/commit, rather than treating a raw page as a ptdesc.
     */
    if (role >= LSF_NODE_P4D_PAGE && role <= LSF_NODE_PTE_PAGE)
        return NULL;
    if (lsf_node_capacity_reserve(owner, role, &ticket))
        return NULL;
    if (bytes != owner->extent[role].bytes || alignment != ticket.alignment) {
        lsf_node_capacity_commit(owner, &ticket, NULL);
        return NULL;
    }
    /* Whole exclusive allocator output, prepaid before its zeroing. No
     * shared-slab size guess, alternative arena or bank fallback is used.
     */
    page = alloc_pages(GFP_KERNEL | __GFP_ZERO | __GFP_NORETRY,
        get_order(ticket.bytes));
    address = page ? page_address(page) : NULL;
    if (page && !address) {
        /* Impossible on the selected native x86-64 GFP_KERNEL mapping, but
         * never turn an actual page into a claimed no-birth NULL result.
         */
        spin_lock_irqsave(&pool_lock, flags);
        factory.pool.poisoned = 1;
        WRITE_ONCE(factory.uncertain, 1);
        spin_unlock_irqrestore(&pool_lock, flags);
        /* Keep the charged unbound reservation; no foreign address is
         * invented and no physical refund or completed preparation is issued.
         */
        return NULL;
    }
    if (lsf_node_capacity_commit(owner, &ticket, address))
        return NULL;
    return address;
}

/* Native free callbacks can run after the caller, close or stop. They never
 * require a current task/stack binding and never dereference a saved ma_state.
 * Inside-bank unknown/duplicate/foreign records suppress the ordinary allocator
 * free and poison/retain the ORIGINAL bank. Outside-bank callers stay ordinary.
 */
static int lsf_node_capacity_record_locked(const void *address,
    enum lsf_node_capacity_role role, struct lsf_node_capacity **owner,
    struct lsf_prepaid_view **found)
{
    struct lsf_node_parent *node;
    struct lsf_prepaid_view *record, *parent;
    unsigned long base, at = (unsigned long)address, bytes, alignment;
    unsigned int slot, kind;
    bool covered;

    lockdep_assert_held(&pool_lock);
    if (!factory.pages || !address)
        return 0;
    base = (unsigned long)page_address(factory.pages);
    covered = at >= base && at - base < LSF_BACKING_BYTES;
    /* Native extents are authenticated by the exact original record, not by
     * assuming that an arbitrary external address belongs to the Node.
     * Also recognize interiors and returned extents to suppress wrong-type or
     * duplicate allocator frees rather than falling through to a slab free.
     */
    for (slot = 2; slot < LSF_ALLOCATION_SLOTS; ++slot) {
        record = &factory.pool.records[slot];
        if (record->phase != LSF_PREPAID_EMPTY &&
            record->kind > LSF_NODE_CAPACITY_NATIVE_BASE &&
            record->kind < LSF_NODE_CAPACITY_NATIVE_BASE + LSF_NODE_CAPACITY_ROLES &&
            record->offset != LSF_NODE_CAPACITY_UNBOUND &&
            at >= record->offset && at - record->offset < record->bytes)
            covered = true;
    }
    if (!covered)
        return 0;
    node = (void *)(base + LSF_FACTORY_INFRA_OFFSET);
    node = lsf_node_capacity_parent_locked(&node->capacity);
    if (!node || role <= 0 || role >= LSF_NODE_CAPACITY_ROLES ||
        !node->capacity.started || !node->capacity.extent[role].bytes ||
        !is_power_of_2(node->capacity.extent[role].alignment) ||
        node->capacity.extent[role].alignment > PAGE_SIZE)
        goto poison;
    alignment = node->capacity.extent[role].alignment;
    if (role == LSF_NODE_PCPU_STAT || role == LSF_NODE_MAPLE_NODE || lsf_node_small_role(role)) {
        bytes = ALIGN(node->capacity.extent[role].bytes, 64);
        if (lsf_node_small_role(role))
            alignment = 64;
        kind = LSF_NODE_CAPACITY_KIND_BASE + role;
    } else {
        if (node->capacity.extent[role].bytes > LSF_BOOTSTRAP_CEILING)
            goto poison;
        bytes = PAGE_SIZE << get_order(node->capacity.extent[role].bytes);
        alignment = PAGE_SIZE;
        kind = LSF_NODE_CAPACITY_NATIVE_BASE + role;
    }
    for (slot = 2; slot < LSF_ALLOCATION_SLOTS; ++slot) {
        record = &factory.pool.records[slot];
        if (record->offset != at || record->kind != kind)
            continue;
        if (record->phase != LSF_PREPAID_LIVE || !record->generation ||
            record->owner != node->owner.slot ||
            record->owner_generation != node->owner.generation ||
            record->bytes != bytes || at % alignment ||
            (record->deferred != LSF_PREPAID_PRIVATE &&
             record->deferred != LSF_PREPAID_PUBLISHED &&
             record->deferred != LSF_PREPAID_QUEUED))
            goto poison;
        if (role == LSF_NODE_PCPU_STAT || role == LSF_NODE_MAPLE_NODE || lsf_node_small_role(role)) {
            if (record->cache_bucket < 2 || record->cache_bucket >= LSF_ALLOCATION_SLOTS)
                goto poison;
            parent = &factory.pool.records[record->cache_bucket];
            if (parent->phase != LSF_PREPAID_LIVE ||
                parent->generation != record->cache_anchor ||
                parent->kind != LSF_NODE_CAPACITY_NATIVE_BASE +
                    (role == LSF_NODE_PCPU_STAT ? LSF_NODE_PCPU_DATA :
                     role == LSF_NODE_MAPLE_NODE ? LSF_NODE_MAPLE_PAGE : LSF_NODE_SMALL_PAGE) ||
                parent->owner != record->owner ||
                parent->owner_generation != record->owner_generation ||
                parent->cache_bucket != node->record.slot ||
                parent->cache_anchor != node->record.generation ||
                record->offset < parent->offset || record->bytes > parent->bytes ||
                record->offset - parent->offset > parent->bytes - record->bytes)
                goto poison;
        } else if (record->cache_bucket != node->record.slot ||
            record->cache_anchor != node->record.generation) {
            goto poison;
        }
        *owner = &node->capacity;
        *found = record;
        return 1;
    }
poison:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
    return -EIO;
}

int lsf_node_capacity_native_owned(const void *address,
    enum lsf_node_capacity_role role, struct lsf_node_capacity **owner)
{
    struct lsf_prepaid_view *record;
    unsigned long flags;
    int result;

    if (!owner)
        return -EINVAL;
    *owner = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_node_capacity_record_locked(address, role, owner, &record);
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_capacity_publish(const void *address,
    enum lsf_node_capacity_role role)
{
    struct lsf_node_capacity *owner;
    struct lsf_prepaid_view *record;
    struct lsf_node_parent *node;
    unsigned long flags;
    int result;

    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_node_capacity_record_locked(address, role, &owner, &record);
    if (result == 1) {
        node = lsf_node_capacity_parent_locked(owner);
        if ((!lsf_node_capacity_open_locked(node) &&
                !(role == LSF_NODE_MAPLE_NODE && lsf_node_capacity_cleanup_live_locked(node))) ||
            record->deferred != LSF_PREPAID_PRIVATE)
            result = -EIO;
        else
            record->deferred = LSF_PREPAID_PUBLISHED;
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_capacity_queue(const void *address,
    enum lsf_node_capacity_role role)
{
    struct lsf_node_capacity *owner;
    struct lsf_prepaid_view *record;
    struct lsf_prepaid_context *context;
    unsigned long flags;
    int result;

    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_node_capacity_record_locked(address, role, &owner, &record);
    if (result == 1) {
        context = &factory.pool.contexts[LSF_DEVICE_OWNER_SLOT];
        if (record->deferred != LSF_PREPAID_PUBLISHED ||
            context->continuations == LSF_ALLOCATION_SLOTS)
            result = -EIO;
        else {
            record->deferred = LSF_PREPAID_QUEUED;
            context->continuations++;
        }
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_capacity_native_free(const void *address,
    enum lsf_node_capacity_role role)
{
    struct lsf_node_capacity *owner;
    struct lsf_prepaid_context *context;
    struct lsf_prepaid_view *record;
    unsigned long flags;
    int result;

    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_node_capacity_record_locked(address, role, &owner, &record);
    if (result == 1) {
        context = &factory.pool.contexts[LSF_DEVICE_OWNER_SLOT];
        if (role == LSF_NODE_SMALL_PAGE || factory.pool.poisoned || context->poisoned || !context->live ||
            (record->deferred == LSF_PREPAID_QUEUED && !context->continuations)) {
            factory.pool.poisoned = 1;
            WRITE_ONCE(factory.uncertain, 1);
            result = -EIO;
        } else {
            if (record->deferred == LSF_PREPAID_QUEUED)
                context->continuations--;
            record->phase = LSF_PREPAID_RETURNED;
            context->live--;
            /* Cursor, generation, backing, actor refs and original escrow
             * stay retained. This is never a physical refund or address reuse.
             */
        }
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_capacity_stat_view(struct lsf_node_capacity *owner,
    unsigned int index, void *backing, void __percpu *pointer)
{
    struct lsf_node_capacity *actual;
    struct lsf_node_parent *node;
    struct lsf_prepaid_view *parent, *record;
    struct lsf_prepaid_context *context;
    unsigned long flags, at = (unsigned long)backing;
    unsigned int slot, parent_slot, i;
    int result = -EOPNOTSUPP;

    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_capacity_parent_locked(owner);
    if (!lsf_node_capacity_open_locked(node) || index >= LSF_NODE_CAPACITY_VECTORS ||
        !pointer || !backing || at < index * 64ul || owner->pcpu_prepared ||
        owner->pcpu_stats[index] || owner->pcpu_stat_backing[index] ||
        !factory.pool.next_generation || factory.pool.next_generation == (u64)-1)
        goto out;
    result = lsf_node_capacity_record_locked((void *)(at - index * 64ul),
        LSF_NODE_PCPU_DATA, &actual, &parent);
    if (result != 1 || actual != owner)
        goto out;
    result = -EIO;
    if (parent->bytes != PAGE_SIZE || (index + 1) * 64ul > parent->bytes)
        goto out;
    for (i = 0; i < LSF_NODE_CAPACITY_VECTORS; ++i)
        if (owner->pcpu_stats[i] == pointer || owner->pcpu_stat_backing[i] == backing)
            goto out;
    context = &factory.pool.contexts[node->owner.slot];
    parent_slot = parent - factory.pool.records;
    for (slot = 2; slot < LSF_ALLOCATION_SLOTS; ++slot) {
        record = &factory.pool.records[slot];
        if (record->phase != LSF_PREPAID_EMPTY)
            continue;
        /* Logical child view of already owned physical data; use the SAME
         * original array and generation, not a second slot/byte ledger.
         */
        *record = (struct lsf_prepaid_view){
            .generation = factory.pool.next_generation++,
            .owner_generation = node->owner.generation,
            .offset = at,
            .bytes = 64,
            .owner = node->owner.slot,
            .phase = LSF_PREPAID_LIVE,
            .kind = LSF_NODE_CAPACITY_KIND_BASE + LSF_NODE_PCPU_STAT,
            .deferred = LSF_PREPAID_PRIVATE,
            .cache_bucket = parent_slot,
            .cache_anchor = parent->generation,
        };
        context->live++;
        owner->pcpu_stat_backing[index] = backing;
        owner->pcpu_stats[index] = pointer;
        result = 0;
        break;
    }
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void __percpu *lsf_node_capacity_stat_take(struct lsf_node_capacity *owner)
{
    struct lsf_node_parent *node;
    struct lsf_node_capacity *actual;
    struct lsf_prepaid_view *record;
    unsigned long flags;
    unsigned int index;
    void __percpu *pointer = NULL;

    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_capacity_parent_locked(owner);
    if (!lsf_node_irq_call_current_locked(node) || !owner->pcpu_prepared)
        goto out;
    for (index = 0; index < LSF_NODE_CAPACITY_VECTORS; ++index) {
        if (owner->pcpu_claimed & BIT(index))
            continue;
        if (!owner->pcpu_stats[index] || lsf_node_capacity_record_locked(
                owner->pcpu_stat_backing[index], LSF_NODE_PCPU_STAT,
                &actual, &record) != 1 || actual != owner)
            goto out;
        owner->pcpu_claimed |= BIT(index);
        record->deferred = LSF_PREPAID_PUBLISHED;
        pointer = owner->pcpu_stats[index];
        break;
    }
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return pointer;
}

int lsf_node_capacity_stat_lookup(void __percpu *pointer,
    struct lsf_node_capacity **owner, unsigned int *index)
{
    struct lsf_node_parent *node;
    struct lsf_node_capacity *actual;
    struct lsf_prepaid_view *record;
    unsigned long flags, base;
    unsigned int i;
    int result = 0;

    if (!owner || !index)
        return -EINVAL;
    *owner = NULL;
    *index = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.pages || !pointer)
        goto out;
    base = (unsigned long)page_address(factory.pages);
    node = (void *)(base + LSF_FACTORY_INFRA_OFFSET);
    node = lsf_node_capacity_parent_locked(&node->capacity);
    if (!node)
        goto out;
    for (i = 0; i < LSF_NODE_CAPACITY_VECTORS; ++i) {
        if (node->capacity.pcpu_stats[i] != pointer)
            continue;
        result = -EIO;
        if (!node->capacity.pcpu_prepared ||
            !(node->capacity.pcpu_claimed & BIT(i)) ||
            (node->capacity.pcpu_returned & BIT(i)))
            goto poison;
        result = lsf_node_capacity_record_locked(node->capacity.pcpu_stat_backing[i],
            LSF_NODE_PCPU_STAT, &actual, &record);
        if (result != 1 || actual != &node->capacity)
            goto poison;
        *owner = actual;
        *index = i;
        goto out;
    }
    /* A non-exact pointer in this actual canonical per-CPU unit must not
     * reach ordinary pcpu_chunk_addr_search/free_area. This includes private
     * and unpopulated offsets, not only the eight exact published cell starts.
     * Native __addr_to_pcpu_ptr is affine modulo unsigned long; subtraction
     * therefore also handles a canonical interval crossing integer wrap.
     */
    if (node->capacity.pcpu_stats[0]) {
        if (!node->capacity.unit_pages || node->capacity.unit_pages > ULONG_MAX / PAGE_SIZE)
            goto poison;
        if ((unsigned long)pointer - (unsigned long)node->capacity.pcpu_stats[0] <
            node->capacity.unit_pages * PAGE_SIZE)
            goto poison;
    }
    goto out;
poison:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
    result = -EIO;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_capacity_stat_return(struct lsf_node_capacity *owner,
    unsigned int index)
{
    struct lsf_node_parent *node;
    struct lsf_node_capacity *actual;
    struct lsf_prepaid_view *record;
    struct lsf_prepaid_context *context;
    unsigned long flags;
    int result = -EIO;

    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_capacity_parent_locked(owner);
    if (!node || index >= LSF_NODE_CAPACITY_VECTORS || !owner->pcpu_prepared ||
        !(owner->pcpu_claimed & BIT(index)) || (owner->pcpu_returned & BIT(index)))
        goto poison;
    result = lsf_node_capacity_record_locked(owner->pcpu_stat_backing[index],
        LSF_NODE_PCPU_STAT, &actual, &record);
    context = &factory.pool.contexts[node->owner.slot];
    if (result != 1 || actual != owner || record->deferred != LSF_PREPAID_PUBLISHED ||
        factory.pool.poisoned || context->poisoned || !context->live ||
        context->continuations >= LSF_ALLOCATION_SLOTS)
        goto poison;
    /* Closure/expiry cannot prevent legitimate native destruction. Neither
     * this bitmap nor the record permits a new allocation at this address.
     */
    owner->pcpu_returned |= BIT(index);
    record->deferred = LSF_PREPAID_QUEUED;
    context->continuations++;
    result = 1;
    goto out;
poison:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
    result = -EIO;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_capacity_stat_allocated(struct lsf_node_capacity *owner,
    unsigned int index, int offset)
{
    struct lsf_node_parent *node;
    struct lsf_node_capacity *actual;
    struct lsf_prepaid_view *record;
    unsigned long flags;
    int result = -EIO;

    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_capacity_parent_locked(owner);
    if (!node || index >= LSF_NODE_CAPACITY_VECTORS ||
        (owner->pcpu_allocated & BIT(index)) ||
        lsf_node_capacity_record_locked(owner->pcpu_stat_backing[index],
            LSF_NODE_PCPU_STAT, &actual, &record) != 1 || actual != owner ||
        record->deferred != LSF_PREPAID_PRIVATE)
        goto poison;
    if (offset < 0) {
        result = -ENOMEM;
        goto out;
    }
    if (offset != index * 64)
        goto poison; /* Actual unexpected native area stays quarantined. */
    owner->pcpu_allocated |= BIT(index); /* Capture real result before expiry. */
    result = lsf_node_capacity_open_locked(node) ? 0 : -EOPNOTSUPP;
    goto out;
poison:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_capacity_stat_private_return(struct lsf_node_capacity *owner,
    unsigned int index, int *allocated)
{
    struct lsf_node_parent *node;
    struct lsf_node_capacity *actual;
    struct lsf_prepaid_view *record, *chunk_record;
    struct lsf_prepaid_context *context;
    unsigned long flags;
    int result = -EIO;

    if (!allocated)
        return -EINVAL;
    *allocated = 0;
    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_capacity_parent_locked(owner);
    if (!node || index >= LSF_NODE_CAPACITY_VECTORS)
        goto poison;
    context = &factory.pool.contexts[node->owner.slot];
    if (!context->closed || factory.pool.poisoned || context->poisoned ||
        READ_ONCE(factory.uncertain))
        goto out;
    if (!owner->pcpu_stat_backing[index] || (owner->pcpu_claimed & BIT(index)) ||
        (owner->pcpu_returned & BIT(index))) {
        result = 0;
        goto out;
    }
    if (lsf_node_capacity_record_locked(owner->pcpu_stat_backing[index],
            LSF_NODE_PCPU_STAT, &actual, &record) != 1 || actual != owner ||
        record->deferred != LSF_PREPAID_PRIVATE ||
        !context->live || context->continuations >= LSF_ALLOCATION_SLOTS)
        goto poison;
    if ((owner->pcpu_allocated & BIT(index)) &&
        (lsf_node_capacity_record_locked(owner->pcpu_chunk, LSF_NODE_PCPU_CHUNK,
            &actual, &chunk_record) != 1 || actual != owner))
        goto poison;
    owner->pcpu_returned |= BIT(index);
    record->deferred = LSF_PREPAID_QUEUED;
    context->continuations++;
    *allocated = !!(owner->pcpu_allocated & BIT(index));
    result = 1;
    goto out;
poison:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_capacity_stat_finish_return(struct lsf_node_capacity *owner,
    unsigned int index, int freed)
{
    struct lsf_node_parent *node;
    struct lsf_node_capacity *actual;
    struct lsf_prepaid_view *record;
    unsigned long flags;
    void *address = NULL;

    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_capacity_parent_locked(owner);
    if (!node || index >= LSF_NODE_CAPACITY_VECTORS ||
        freed != ((owner->pcpu_allocated & BIT(index)) ? 64 : 0) ||
        !(owner->pcpu_returned & BIT(index)) ||
        lsf_node_capacity_record_locked(owner->pcpu_stat_backing[index],
            LSF_NODE_PCPU_STAT, &actual, &record) != 1 || actual != owner ||
        record->deferred != LSF_PREPAID_QUEUED)
        goto poison;
    address = owner->pcpu_stat_backing[index];
    spin_unlock_irqrestore(&pool_lock, flags);
    /* The physical allocation remains held. Logical return occurs only after
     * the real native free-area routine removed its allocation-map alias.
     */
    return lsf_node_capacity_native_free(address, LSF_NODE_PCPU_STAT);
poison:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
    spin_unlock_irqrestore(&pool_lock, flags);
    return -EIO;
}

int lsf_node_capacity_pcpu_commit(struct lsf_node_capacity *owner)
{
    struct lsf_node_parent *node;
    struct lsf_node_capacity *actual;
    struct lsf_prepaid_view *record;
    unsigned long flags;
    unsigned int index;
    int result = -EIO;

    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_capacity_parent_locked(owner);
    if (!lsf_node_capacity_open_locked(node) || !owner->started || owner->pcpu_prepared ||
        owner->pcpu_claimed || owner->pcpu_returned || owner->irq_claimed ||
        owner->pcpu_allocated != (1u << LSF_NODE_CAPACITY_VECTORS) - 1u ||
        lsf_node_capacity_record_locked(owner->pcpu_chunk, LSF_NODE_PCPU_CHUNK,
            &actual, &record) != 1 || actual != owner)
        goto out;
    for (index = 0; index < LSF_NODE_CAPACITY_VECTORS; ++index)
        if (!owner->pcpu_stats[index] ||
            lsf_node_capacity_record_locked(owner->pcpu_stat_backing[index],
                LSF_NODE_PCPU_STAT, &actual, &record) != 1 || actual != owner ||
            record->deferred != LSF_PREPAID_PRIVATE)
            goto out;
    for (index = 0; index < LSF_NODE_CAPACITY_VECTORS; ++index)
        if (!owner->irq_descs[index] ||
            lsf_node_capacity_record_locked(owner->irq_descs[index], LSF_NODE_IRQ_DESC,
                &actual, &record) != 1 || actual != owner ||
            record->deferred != LSF_PREPAID_PRIVATE)
            goto out;
    owner->pcpu_prepared = 1;
    result = 0; /* Native pcpu capacity only, never a whole NodeFunding word. */
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_pgtable_pre_free(struct mm_struct *mm, const void *address,
    enum lsf_node_capacity_role role)
{
    struct lsf_node_capacity *owner;
    struct lsf_prepaid_view *record;
    struct lsf_prepaid_context *context;
    unsigned long flags;
    int selected;

    if (role < LSF_NODE_P4D_PAGE || role > LSF_NODE_PTE_PAGE)
        return -EINVAL;
    spin_lock_irqsave(&pool_lock, flags);
    selected = lsf_node_capacity_record_locked(address, role, &owner, &record);
    if (selected == 1) {
        context = &factory.pool.contexts[LSF_DEVICE_OWNER_SLOT];
        if (mm != &init_mm || factory.pool.poisoned || context->poisoned ||
            record->deferred != LSF_PREPAID_PUBLISHED ||
            context->continuations == LSF_ALLOCATION_SLOTS) {
            factory.pool.poisoned = 1;
            WRITE_ONCE(factory.uncertain, 1);
            selected = -EIO;
        } else {
            /* Claim BEFORE the actual native destructor. A duplicate cannot
             * run that destructor twice or release the physical backing.
             */
            record->deferred = LSF_PREPAID_QUEUED;
            context->continuations++;
        }
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return selected;
}

/* Called at the real native backing-free point, AFTER any actual ptdesc
 * destructor. Native page-table flags, lock and global accounting cleanup
 * therefore remain native; only the physical page stays with the original
 * Node. No new owner and no page-table-cache refund are manufactured here.
 */
int lsf_node_pgtable_backing_hold(const void *address)
{
    struct lsf_prepaid_view *record;
    unsigned long at = (unsigned long)address, base, flags;
    unsigned int slot, role = 0;
    bool covered = false;

    spin_lock_irqsave(&pool_lock, flags);
    if (factory.pages) {
        base = (unsigned long)page_address(factory.pages);
        covered = at >= base && at - base < LSF_BACKING_BYTES;
        for (slot = 2; slot < LSF_ALLOCATION_SLOTS; ++slot) {
            record = &factory.pool.records[slot];
            if (record->phase == LSF_PREPAID_EMPTY ||
                record->kind <= LSF_NODE_CAPACITY_NATIVE_BASE ||
                record->kind >= LSF_NODE_CAPACITY_NATIVE_BASE + LSF_NODE_CAPACITY_ROLES ||
                record->offset == LSF_NODE_CAPACITY_UNBOUND ||
                at < record->offset || at - record->offset >= record->bytes)
                continue;
            covered = true;
            if (at == record->offset &&
                record->kind >= LSF_NODE_CAPACITY_NATIVE_BASE + LSF_NODE_P4D_PAGE &&
                record->kind <= LSF_NODE_CAPACITY_NATIVE_BASE + LSF_NODE_PTE_PAGE)
                role = record->kind - LSF_NODE_CAPACITY_NATIVE_BASE;
        }
    }
    if (covered && !role) {
        factory.pool.poisoned = 1;
        WRITE_ONCE(factory.uncertain, 1);
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    if (role)
        return lsf_node_capacity_native_free(address, role);
    return covered ? -EIO : 0;
}

int lsf_node_capacity_mas_bind(struct lsf_node_capacity *owner, struct ma_state *mas)
{
    struct lsf_node_parent *node;
    unsigned long flags;
    int result = -EOPNOTSUPP;

    if (!mas || !lsf_node_irq_sparse_identity(mas->tree))
        return result;
    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_capacity_parent_locked(owner);
    if (!lsf_node_capacity_open_locked(node) || !owner->pcpu_prepared ||
        owner->active_mas || owner->mas_task || owner->mas_generation ||
        (owner->sparse_tree && owner->sparse_tree != mas->tree) ||
        !factory.pool.next_generation || factory.pool.next_generation == (u64)-1)
        goto out;
    owner->sparse_tree = mas->tree;
    owner->cleanup_origin = (struct lsf_node_native_ticket){0};
    owner->mas_generation = factory.pool.next_generation++;
    owner->mas_task = current;
    owner->active_mas = mas;
    result = 0;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_capacity_mas_owner(struct ma_state *mas, struct lsf_node_capacity **owner)
{
    struct lsf_node_parent *node;
    unsigned long base, flags;
    int result = 0;

    if (!owner)
        return -EINVAL;
    *owner = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.pages)
        goto out;
    base = (unsigned long)page_address(factory.pages);
    node = (void *)(base + LSF_FACTORY_INFRA_OFFSET);
    node = lsf_node_capacity_parent_locked(&node->capacity);
    if (!node || !node->capacity.active_mas || node->capacity.mas_task != current)
        goto out;
    /* A copied ma_state in the same active sparse-tree operation must never
     * fall through to ordinary SLUB. Native preallocation is attached to the
     * one original state; an unexpected second allocation state is refused.
     * A genuinely different tree remains an ordinary native caller.
     */
    if (!mas || mas->tree != node->capacity.sparse_tree)
        goto out;
    /* Only the live call-local alias can be read. RCU/free paths never call
     * this function and cannot gain authority from a reused stack address.
     */
    result = -EIO;
    if (!lsf_node_capacity_maple_allowed_locked(node) || !node->capacity.mas_generation ||
        node->capacity.active_mas != mas)
        goto out;
    *owner = &node->capacity;
    result = 1;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_capacity_mas_bind_cleanup(struct ma_state *mas, const void *entry)
{
    struct lsf_node_capacity *owner;
    struct lsf_node_parent *node;
    struct lsf_prepaid_view *record;
    struct lsf_prepaid_context *context;
    unsigned long flags;
    int result = -EOPNOTSUPP;

    /* The real tree lock/lifetime precedes this comparison; no IRQ descriptor
     * payload is dereferenced to manufacture provenance from its contents.
     */
    if (!mas || !entry || !lsf_node_irq_sparse_entry(mas, entry))
        return result;
    spin_lock_irqsave(&pool_lock, flags);
    if (lsf_node_capacity_record_locked(entry, LSF_NODE_IRQ_DESC, &owner, &record) != 1)
        goto out;
    node = lsf_node_capacity_parent_locked(owner);
    context = &factory.pool.contexts[LSF_DEVICE_OWNER_SLOT];
    if (!node || factory.pool.poisoned || context->poisoned ||
        READ_ONCE(factory.uncertain) || !owner->pcpu_prepared ||
        record->deferred != LSF_PREPAID_PUBLISHED ||
        owner->active_mas || owner->mas_task || owner->mas_generation ||
        owner->cleanup_origin.generation ||
        (owner->sparse_tree && owner->sparse_tree != mas->tree) ||
        !factory.pool.next_generation || factory.pool.next_generation == (u64)-1)
        goto out;
    owner->sparse_tree = mas->tree;
    owner->mas_generation = factory.pool.next_generation++;
    owner->mas_task = current;
    owner->active_mas = mas;
    owner->cleanup_origin = (struct lsf_node_native_ticket){
        record - factory.pool.records, LSF_NODE_IRQ_DESC, record->generation,
        record->bytes, 64};
    result = 0;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_node_capacity_mas_unbind(struct lsf_node_capacity *owner, struct ma_state *mas)
{
    struct lsf_node_parent *node;
    unsigned long flags;
    int result = -EIO;

    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_capacity_parent_locked(owner);
    if (!node || owner->active_mas != mas)
        goto poison;
    if (owner->mas_task == current && owner->mas_generation)
        result = 0;
    /* Clear the saved stack/task aliases before the registering call can
     * return, including an expired/stopped or otherwise failed transaction.
     */
    owner->active_mas = NULL;
    owner->mas_task = NULL;
    owner->mas_generation = 0;
    owner->cleanup_origin = (struct lsf_node_native_ticket){0};
    if (!result)
        goto out;
poison:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void *lsf_node_capacity_maple_take(struct lsf_node_capacity *owner)
{
    struct lsf_node_parent *node;
    struct lsf_node_capacity *actual;
    struct lsf_prepaid_context *context;
    struct lsf_prepaid_view *parent, *record;
    unsigned long flags, bytes, stride, alignment, offset;
    unsigned int slot, parent_slot;
    void *page, *address = NULL;

    if (lsf_node_capacity_maple_checkpoint(owner))
        return NULL;
    bytes = owner->extent[LSF_NODE_MAPLE_NODE].bytes;
    alignment = owner->extent[LSF_NODE_MAPLE_NODE].alignment;
    stride = ALIGN(bytes, 64);
    if (!bytes || !is_power_of_2(alignment) || alignment > PAGE_SIZE ||
        !stride || stride > PAGE_SIZE || stride % alignment || PAGE_SIZE % stride)
        return NULL;
    /* The sparse IRQ mutex serializes this explicit allocator context. Each
     * fresh physical page is paid before its allocator; each logical node
     * uses another ORIGINAL record before its first native field write.
     */
    if (!owner->maple_page || owner->maple_used == PAGE_SIZE / stride) {
        page = lsf_node_capacity_take(owner, LSF_NODE_MAPLE_PAGE, PAGE_SIZE, PAGE_SIZE);
        if (!page)
            return NULL;
        owner->maple_page = page;
        owner->maple_used = 0;
    }
    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_capacity_parent_locked(owner);
    if (!lsf_node_capacity_maple_allowed_locked(node) || owner->mas_task != current ||
        !owner->active_mas || !owner->mas_generation ||
        owner->maple_used >= PAGE_SIZE / stride ||
        !factory.pool.next_generation || factory.pool.next_generation == (u64)-1 ||
        lsf_node_capacity_record_locked(owner->maple_page, LSF_NODE_MAPLE_PAGE,
            &actual, &parent) != 1 || actual != owner)
        goto out;
    context = &factory.pool.contexts[node->owner.slot];
    parent_slot = parent - factory.pool.records;
    offset = owner->maple_used * stride;
    for (slot = 2; slot < LSF_ALLOCATION_SLOTS; ++slot) {
        record = &factory.pool.records[slot];
        if (record->phase != LSF_PREPAID_EMPTY)
            continue;
        address = (char *)owner->maple_page + offset;
        *record = (struct lsf_prepaid_view){
            .generation = factory.pool.next_generation++,
            .owner_generation = node->owner.generation,
            .offset = (unsigned long)address,
            .bytes = stride,
            .owner = node->owner.slot,
            .phase = LSF_PREPAID_LIVE,
            .kind = LSF_NODE_CAPACITY_KIND_BASE + LSF_NODE_MAPLE_NODE,
            .deferred = LSF_PREPAID_PRIVATE,
            .cache_bucket = parent_slot,
            .cache_anchor = parent->generation,
        };
        context->live++;
        owner->maple_used++;
        break;
    }
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    /* Mark the admitted node before preallocation can publish its pointer
     * into a ma_state. A later native store uses only these prepaid nodes.
     */
    if (address && lsf_node_capacity_publish(address, LSF_NODE_MAPLE_NODE) != 1)
        return NULL;
    return address;
}

struct irq_desc *lsf_node_capacity_desc_take(struct lsf_node_capacity *owner)
{
    struct lsf_node_parent *node;
    struct lsf_node_capacity *actual;
    struct lsf_prepaid_view *record;
    struct irq_desc *desc = NULL;
    unsigned long flags;
    unsigned int index;

    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_capacity_parent_locked(owner);
    if (!lsf_node_irq_call_current_locked(node) || !owner->pcpu_prepared)
        goto out;
    for (index = 0; index < LSF_NODE_CAPACITY_VECTORS; ++index) {
        if (owner->irq_claimed & (1u << index))
            continue;
        if (lsf_node_capacity_record_locked(owner->irq_descs[index], LSF_NODE_IRQ_DESC,
                &actual, &record) != 1 || actual != owner ||
            record->deferred != LSF_PREPAID_PRIVATE)
            goto out;
        record->deferred = LSF_PREPAID_PUBLISHED;
        owner->irq_claimed |= 1u << index;
        owner->irq_desc_pci[index] = owner->irq_pci_birth;
        owner->irq_desc_domain[index] = owner->irq_domain_birth;
        desc = owner->irq_descs[index];
        break;
    }
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return desc;
}

int lsf_node_capacity_desc_close_private(struct lsf_node_capacity *owner,
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
    if (!owner->irq_descs[index] || (owner->irq_claimed & BIT(index)) ||
        (owner->irq_returned & BIT(index))) {
        result = 0;
        goto out;
    }
    if (lsf_node_capacity_record_locked(owner->irq_descs[index], LSF_NODE_IRQ_DESC,
            &actual, &record) != 1 || actual != owner ||
        record->deferred != LSF_PREPAID_PRIVATE)
        goto poison;
    /* Never-claimed storage has no native init_desc/kobject/RCU aliases.
     * Only its private logical record returns; the actual page stays charged.
     */
    owner->irq_returned |= BIT(index);
    address = owner->irq_descs[index];
    spin_unlock_irqrestore(&pool_lock, flags);
    return lsf_node_capacity_native_free(address, LSF_NODE_IRQ_DESC);
poison:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

#include "factory-node-irq-loan.c"
#include "factory-node-radix.c"

#include "factory-node-parent-vector.c"

int lsf_node_irq_aux_close_private(struct lsf_node_capacity *owner, unsigned int index)
{
    struct lsf_node_parent *node;
    struct lsf_node_capacity *actual;
    struct lsf_prepaid_view *record;
    struct lsf_prepaid_context *context;
    struct lsf_node_vector_slot *slot;
    enum lsf_node_capacity_role role;
    unsigned int claimed, *returned;
    unsigned long flags;
    void *address;
    int result = -EIO;

    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_capacity_parent_locked(owner);
    if (!node || index >= LSF_NODE_CAPACITY_VECTORS)
        goto poison;
    context = &factory.pool.contexts[node->owner.slot];
    if (!context->closed || factory.pool.poisoned || context->poisoned ||
        READ_ONCE(factory.uncertain))
        goto out;
    for (role = LSF_NODE_IRQ_PARENT_DATA; role <= LSF_NODE_IRQ_APIC; ++role) {
        address = role == LSF_NODE_IRQ_PARENT_DATA ?
            owner->irq_parent_data[index] : owner->irq_apic[index];
        claimed = role == LSF_NODE_IRQ_PARENT_DATA ?
            owner->irq_parent_claimed : owner->irq_apic_claimed;
        returned = role == LSF_NODE_IRQ_PARENT_DATA ?
            &owner->irq_parent_returned : &owner->irq_apic_returned;
        if (!address || (claimed & BIT(index)) || (*returned & BIT(index)))
            continue;
        if (lsf_node_capacity_record_locked(address, role, &actual, &record) != 1 ||
            actual != owner || record->deferred != LSF_PREPAID_PRIVATE || !context->live)
            goto poison;
        if (role == LSF_NODE_IRQ_APIC) {
            slot = &owner->vector_slots[index];
            /* An unknown partial native allocation keeps its original view.
             * No attempt is made to infer or release an unconfirmed bit. */
            if (slot->phase != LSF_NODE_VECTOR_HELD)
                continue;
            if (!lsf_node_irq_aux_ticket_locked(&slot->apic, record, role) ||
                slot->desc.generation || !slot->matrix || slot->cpu || !slot->vector)
                goto poison;
        }
        *returned |= BIT(index);
        record->phase = LSF_PREPAID_RETURNED;
        context->live--;
        /* Only a never-initialized private logical view returns. Its page,
         * matrix bit and immutable source identity remain ORIGINAL Node-owned.
         * No slot, cursor, native bit or physical charge is refunded/reused. */
    }
    result = 0;
    goto out;
poison:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

#include "factory-node-irq-action-pool.c"
#include "factory-node-irq-proc-pool.c"
#include "factory-node-small-objects.c"
