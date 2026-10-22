/* SPDX-License-Identifier: GPL-2.0-only */
/* Uninstalled source, included after the actual device event factory helpers.
 * The receive tail must NOT keep an extra skb reference: original sock_rfree
 * and rmem/dump semantics still run at their unchanged final-free point. */
static_assert(LSF_DEVICE_RECIPIENT_WORK == LSF_DEVICE_RECIPIENT_KIND_WORK);
static_assert(LSF_DEVICE_RECIPIENT_SIGQUEUE == LSF_DEVICE_RECIPIENT_KIND_SIGQUEUE);

struct lsf_device_recipient_work {
    const struct task_struct *actor;
    const struct sock *recipient;
};

/* The ordinary sigqueue layout is unchanged. Only this private allocation
 * prepays the complete original object and its actual deferred-return head. */
struct lsf_device_recipient_signal {
    struct sigqueue signal;
    struct rcu_head retire;
    struct lsf_device_registration_source birth;
};
static_assert(offsetof(struct lsf_device_recipient_signal, signal) == 0);

static int lsf_factory_device_recipient_same_source(
    struct lsf_device_registration_source a, struct lsf_device_registration_source b)
{
    return a.address == b.address && a.kind == b.kind && a.slot == b.slot &&
        a.generation == b.generation && a.pci_slot == b.pci_slot &&
        a.pci_generation == b.pci_generation;
}

/* Caller holds pool_lock. Classify bank range and exact typed birth BEFORE
 * reading work storage. A private wrong-kind/returned/interior address cannot
 * become an ordinary allocator/free or authorize a different original PCI. */
static int lsf_factory_device_recipient_lookup_locked(const void *address,
    unsigned int kind, unsigned int phase, struct lsf_device_registration_source *copy)
{
    struct lsf_prepaid_view *record;
    struct lsf_prepaid_ticket ticket;
    unsigned long base, value = (unsigned long)address;
    unsigned int i;
    if (!factory.pages)
        return 0;
    base = (unsigned long)page_address(factory.pages);
    if (value < base || value - base >= LSF_BACKING_BYTES)
        return 0;
    if (!copy || !factory.device || factory.pool.poisoned ||
        (kind != LSF_DEVICE_RECIPIENT_WORK && kind != LSF_DEVICE_RECIPIENT_SIGQUEUE) ||
        (phase != LSF_PREPAID_PUBLISHED &&
         (phase != LSF_PREPAID_QUEUED || kind != LSF_DEVICE_RECIPIENT_SIGQUEUE)) ||
        (kind == LSF_DEVICE_RECIPIENT_SIGQUEUE && IS_ENABLED(CONFIG_PREEMPT_RT)))
        goto poison;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->offset != value - base)
            continue;
        ticket = (struct lsf_prepaid_ticket){i, record->generation};
        if (record != lsf_device_record(&factory.pool, factory.device->key, ticket, kind) ||
            record->deferred != phase ||
            (kind == LSF_DEVICE_RECIPIENT_WORK && record->bytes < sizeof(struct lsf_device_recipient_work)) ||
            (kind == LSF_DEVICE_RECIPIENT_SIGQUEUE && record->bytes < sizeof(struct lsf_device_recipient_signal)))
            goto poison;
        *copy = (struct lsf_device_registration_source){
            .address = address, .kind = kind, .slot = i,
            .generation = record->generation, .pci_slot = record->cache_bucket,
            .pci_generation = record->cache_anchor,
        };
        if (!lsf_factory_device_registration_parent_locked(*copy))
            goto poison;
        return 1;
    }
poison:
    lsf_factory_device_firmware_poison();
    return -1;
}

/* Caller holds pool_lock. The exact synchronous work actor is compared only;
 * no pointer borrow survives its actual callback/receive tail. A signal queue
 * entry is a separate physical descendant and does not use this task fence. */
static int lsf_factory_device_recipient_current_locked(
    struct lsf_device_registration_source source, const struct sock *recipient)
{
    struct lsf_device_registration_source actual;
    const struct lsf_device_recipient_work *work;
    struct lsf_factory_device_firmware *owned;
    if (source.kind != LSF_DEVICE_RECIPIENT_WORK ||
        lsf_factory_device_recipient_lookup_locked(source.address,
            LSF_DEVICE_RECIPIENT_WORK, LSF_PREPAID_PUBLISHED, &actual) != 1 ||
        source.slot != actual.slot || source.generation != actual.generation ||
        source.pci_slot != actual.pci_slot || source.pci_generation != actual.pci_generation ||
        !(owned = lsf_factory_device_registration_parent_locked(actual)) ||
        !owned->core_initialized || owned->queued || owned->putting || owned->returned ||
        in_interrupt())
        return 0;
    work = actual.address;
    return work->actor == current && work->recipient &&
        (!recipient || work->recipient == recipient);
}

/* The real caller still holds this actual original SKB while entering. All
 * continuation metadata is admitted before callbacks/queue publication or the
 * receiver's original skb_free_datagram. On failure, no successful work owner
 * is invented; the caller must preserve/quarantine the original operation. */
int lsf_factory_device_recipient_begin(const void *skb, const struct sock *recipient,
    struct lsf_device_registration_source *copy)
{
    struct lsf_device_registration_source source;
    struct lsf_device_recipient_work *work;
    struct lsf_prepaid_ticket parent, ticket;
    lsf_u64 offset;
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_factory_device_uevent_lookup_locked(skb, LSF_DEVICE_UEVENT_SKB, &source);
    if (result != 1)
        goto out;
    if (!copy || !recipient || in_interrupt() ||
        !lsf_factory_device_uevent_current_locked(source))
        goto poison;
    parent = (struct lsf_prepaid_ticket){source.pci_slot, source.pci_generation};
    if (!lsf_device_allocate(&factory.pool, factory.device->key, sizeof(*work),
            LSF_DEVICE_RECIPIENT_WORK, parent, &ticket, &offset))
        goto poison;
    work = (void *)((char *)page_address(factory.pages) + offset);
    *work = (struct lsf_device_recipient_work){.actor = current, .recipient = recipient};
    if (!lsf_device_recipient_publish(&factory.pool, factory.device->key,
            ticket, LSF_DEVICE_RECIPIENT_WORK, parent))
        goto poison;
    *copy = (struct lsf_device_registration_source){
        .address = work, .kind = LSF_DEVICE_RECIPIENT_WORK,
        .slot = ticket.slot, .generation = ticket.generation,
        .pci_slot = parent.slot, .pci_generation = parent.generation,
    };
    goto out;
poison:
    lsf_factory_device_firmware_poison();
    result = -1;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_device_recipient_current(struct lsf_device_registration_source source,
    const struct sock *recipient)
{
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_factory_device_recipient_current_locked(source, recipient);
    if (!result)
        lsf_factory_device_firmware_poison();
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_device_recipient_finish(struct lsf_device_registration_source source)
{
    struct lsf_prepaid_ticket ticket = {source.slot, source.generation};
    unsigned long flags;
    int result = -1;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_factory_device_recipient_current_locked(source, NULL) ||
        !lsf_device_queue(&factory.pool, factory.device->key, ticket, LSF_DEVICE_RECIPIENT_WORK) ||
        !lsf_device_finish(&factory.pool, factory.device->key, ticket, LSF_DEVICE_RECIPIENT_WORK))
        goto poison;
    result = 1;
    goto out;
poison:
    lsf_factory_device_firmware_poison();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    /* This call must be at the real tail, outside original recipient/sighand
     * locks as well as pool_lock. Source wiring must not move it earlier. */
    if (result == 1)
        lsf_factory_device_firmware_schedule();
    return result;
}

/* Called only by the explicit private __sigqueue_alloc chain. The actual
 * source function retains its original RLIMIT/ucounts/flags initialization. */
struct sigqueue *lsf_factory_device_recipient_signal_allocate(
    struct lsf_device_registration_source source)
{
    struct lsf_prepaid_ticket parent = {source.pci_slot, source.pci_generation}, ticket;
    struct lsf_device_recipient_signal *owned;
    struct sigqueue *result = NULL;
    unsigned long flags;
    lsf_u64 offset;
    spin_lock_irqsave(&pool_lock, flags);
    if (IS_ENABLED(CONFIG_PREEMPT_RT) ||
        !lsf_factory_device_recipient_current_locked(source, NULL))
        goto poison;
    if (!lsf_device_allocate(&factory.pool, factory.device->key, sizeof(*owned),
            LSF_DEVICE_RECIPIENT_SIGQUEUE, parent, &ticket, &offset))
        goto out;
    owned = (void *)((char *)page_address(factory.pages) + offset);
    memset(owned, 0, sizeof(*owned));
    result = &owned->signal;
    owned->birth = (struct lsf_device_registration_source){
        .address = result, .kind = LSF_DEVICE_RECIPIENT_SIGQUEUE,
        .slot = ticket.slot, .generation = ticket.generation,
        .pci_slot = parent.slot, .pci_generation = parent.generation,
    };
    if (!lsf_device_recipient_publish(&factory.pool, factory.device->key,
            ticket, LSF_DEVICE_RECIPIENT_SIGQUEUE, parent)) {
        result = NULL;
        goto poison;
    }
    goto out;
poison:
    lsf_factory_device_firmware_poison();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Before any q->flags/ucounts read in the real final-return function. */
int lsf_factory_device_recipient_signal_birth(const struct sigqueue *address,
    struct lsf_device_registration_source *source)
{
    const struct lsf_device_recipient_signal *owned;
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_factory_device_recipient_lookup_locked(address,
        LSF_DEVICE_RECIPIENT_SIGQUEUE, LSF_PREPAID_PUBLISHED, source);
    if (result == 1) {
        owned = source->address;
        if (!lsf_factory_device_recipient_same_source(*source, owned->birth)) {
            lsf_factory_device_firmware_poison();
            result = -1;
        }
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* The actual callback runs after the non-RT producer's original IRQ/preempt
 * disabled extent. Classify before any private dereference; no head/object
 * access follows its sole final return. Shared RCU capacity remains unqualified. */
static void lsf_factory_device_recipient_signal_callback(struct rcu_head *head)
{
    const struct lsf_device_recipient_signal *owned;
    struct lsf_device_registration_source source;
    struct lsf_prepaid_ticket ticket;
    unsigned long flags, value = (unsigned long)head;
    const void *address;
    int result = -1;
    spin_lock_irqsave(&pool_lock, flags);
    if (value < offsetof(struct lsf_device_recipient_signal, retire))
        goto poison;
    address = (const void *)(value - offsetof(struct lsf_device_recipient_signal, retire));
    if (lsf_factory_device_recipient_lookup_locked(address,
            LSF_DEVICE_RECIPIENT_SIGQUEUE, LSF_PREPAID_QUEUED, &source) != 1)
        goto poison;
    owned = source.address;
    if (!lsf_factory_device_recipient_same_source(source, owned->birth))
        goto poison;
    ticket = (struct lsf_prepaid_ticket){source.slot, source.generation};
    if (!lsf_device_finish(&factory.pool, factory.device->key, ticket, LSF_DEVICE_RECIPIENT_SIGQUEUE))
        goto poison;
    result = 1;
    goto out;
poison:
    lsf_factory_device_firmware_poison();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    if (result == 1)
        lsf_factory_device_firmware_schedule();
}

/* __sigqueue_free has already performed its unchanged PREALLOC/ucount handling.
 * Keep the actual object/PCI charged through RCU, never queue final cleanup
 * directly from this original sighand extent. No new physical queue is added. */
int lsf_factory_device_recipient_signal_return(const struct sigqueue *address)
{
    struct lsf_device_registration_source source;
    struct lsf_prepaid_ticket ticket;
    unsigned long flags;
    struct lsf_device_recipient_signal *owned = NULL;
    int result;
    rcu_read_lock();
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_factory_device_recipient_lookup_locked(address,
        LSF_DEVICE_RECIPIENT_SIGQUEUE, LSF_PREPAID_PUBLISHED, &source);
    if (result == 1) {
        ticket = (struct lsf_prepaid_ticket){source.slot, source.generation};
        owned = (void *)((char *)page_address(factory.pages) + factory.pool.records[source.slot].offset);
        if (!lsf_factory_device_recipient_same_source(source, owned->birth) ||
            !lsf_device_queue(&factory.pool, factory.device->key, ticket, LSF_DEVICE_RECIPIENT_SIGQUEUE)) {
            lsf_factory_device_firmware_poison();
            result = -1;
        }
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    if (result == 1)
        call_rcu(&owned->retire, lsf_factory_device_recipient_signal_callback);
    rcu_read_unlock();
    return result;
}
