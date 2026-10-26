/* SPDX-License-Identifier: GPL-2.0-only */
/* Include AFTER the original typed NETDEV-record helper. This is actual bank
 * allocation before constructor publication, never adoption of a pointer. */
#include <net/lsf_stream_netdev_cpu_private.h>
static_assert(NR_CPUS == 64);
static_assert(__alignof__(struct lsf_stream_netdev_cpu_storage) <= 64);
static_assert(sizeof(struct lsf_stream_netdev_cpu_storage) <= LSF_FACTORY_INFRA_BYTES);

int lsf_factory_stream_netdev_cpu_allocate(struct net_device *dev)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *parent;
    struct lsf_prepaid_ticket parent_ticket, ticket;
    struct lsf_stream_netdev_cpu_storage *storage;
    unsigned long flags;
    u64 offset;
    unsigned int cpu, field;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_stream_rx_address_locked(dev)) goto out;
    result = -EOPNOTSUPP;
    state = lsf_stream_rx_current_locked();
    parent = lsf_stream_netdev_record_locked(state, dev, &parent_ticket);
    if (!parent || parent->deferred != LSF_PREPAID_PRIVATE ||
        !lsf_stream_constructor_current_locked(state) || READ_ONCE(dev->lsf_cpu_storage) ||
        dev->pcpu_refcnt || dev->core_stats) goto out;
    result = lsf_stream_constructor_allocate_locked(state, LSF_DEVICE_NETDEV_CPU,
        parent_ticket, sizeof(*storage), __alignof__(*storage), &ticket, &offset);
    if (result != 1) goto out;
    storage = (void *)((char *)page_address(factory.pages) + offset);
    memset(storage, 0, sizeof(*storage));
    storage->device = dev; storage->cpus = NR_CPUS;
    atomic_set(&storage->fault, 0);
    for (cpu = 0; cpu < NR_CPUS; ++cpu) {
        atomic_set(&storage->references[cpu], 0);
        for (field = 0; field < 4; ++field) atomic_long_set(&storage->stats[cpu][field], 0);
    }
    if (!lsf_device_publish(&factory.pool, state->owner, ticket, LSF_DEVICE_NETDEV_CPU)) {
        factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1);
        result = -EIO; goto out;
    }
    WRITE_ONCE(dev->lsf_cpu_storage, storage); /* BEFORE original initial __dev_hold. */
out:
    if (result < 0 && factory.pool.poisoned) WRITE_ONCE(factory.uncertain, 1);
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_netdev_cpu_retire(struct net_device *dev)
{
    struct lsf_stream_rx_state *state;
    struct lsf_stream_netdev_cpu_storage *storage;
    struct lsf_prepaid_view *parent, *record;
    struct lsf_prepaid_ticket parent_ticket, ticket;
    unsigned long flags, base, at;
    unsigned int i;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_stream_rx_address_locked(dev)) goto out;
    result = -1;
    state = lsf_stream_rx_current_locked();
    parent = lsf_stream_netdev_record_locked(state, dev, &parent_ticket);
    if (!parent) goto poison;
    storage = READ_ONCE(dev->lsf_cpu_storage);
    if (!storage) { result = 0; goto out; }
    if (!lsf_stream_rx_address_locked(storage)) goto poison;
    base = (unsigned long)page_address(factory.pages); at = (unsigned long)storage;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->offset != at - base) continue;
        ticket = (struct lsf_prepaid_ticket){i, record->generation};
        if (!lsf_device_record(&factory.pool, state->owner, ticket, LSF_DEVICE_NETDEV_CPU) ||
            record->bytes != ((sizeof(*storage) + 63u) & ~63ull) ||
            record->deferred != LSF_PREPAID_PUBLISHED ||
            record->cache_bucket != parent_ticket.slot || record->cache_anchor != parent_ticket.generation)
            goto poison;
        /* Only after authoritative original birth checks may payload be read.
         * Do NOT zero or require zero signed per-CPU debt. The unchanged Linux
         * wait-allrefs==1 and actual original free points are last-use proof. */
        if (storage->device != dev || storage->cpus != NR_CPUS || atomic_read(&storage->fault))
            goto poison;
        WRITE_ONCE(dev->lsf_cpu_storage, NULL); /* Last real alias BEFORE return. */
        if (!lsf_device_queue(&factory.pool, state->owner, ticket, LSF_DEVICE_NETDEV_CPU) ||
            !lsf_device_finish(&factory.pool, state->owner, ticket, LSF_DEVICE_NETDEV_CPU))
            goto poison;
        result = 1; goto out;
    }
poison:
    factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
