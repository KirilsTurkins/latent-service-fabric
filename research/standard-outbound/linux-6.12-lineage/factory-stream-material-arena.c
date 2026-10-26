/* SPDX-License-Identifier: GPL-2.0-only */
/* Fixed private typed constructors use the original already-paid Node arena.
 * No future-count prediction, second table, new allocation or caller cost
 * admission exists here. Each caller supplies its actual allocating-TU type;
 * missing allocating/freeing source ports still forbid consumer selection. */
static int lsf_stream_constructor_current_locked(struct lsf_stream_rx_state *state)
{
    lockdep_assert_held(&pool_lock);
    return state && state == lsf_stream_rx_current_locked() && !state->closing &&
        !state->stopped && !factory.pool.stopped && !factory.pool.poisoned &&
        !READ_ONCE(factory.uncertain) && factory.device->constructor_active &&
        factory.device->constructor_task == current && current->mm == factory.mm &&
        current_cred() == factory.cred && task_tgid(current) == factory.tgid &&
        current->nsproxy && current->nsproxy->net_ns == factory.net;
}

static int lsf_stream_constructor_allocate_locked(struct lsf_stream_rx_state *state,
    unsigned int kind, struct lsf_prepaid_ticket parent, unsigned long bytes,
    unsigned long alignment, struct lsf_prepaid_ticket *ticket, u64 *offset)
{
    struct lsf_prepaid_view *birth;
    lockdep_assert_held(&pool_lock);
    if (!lsf_stream_constructor_current_locked(state) || !ticket || !offset ||
        !parent.slot || parent.slot >= LSF_ALLOCATION_SLOTS ||
        !bytes || bytes > ULONG_MAX - 63u || !alignment || alignment > 64u ||
        (alignment & (alignment - 1u)) || !lsf_device_kind(kind) || kind == LSF_DEVICE_ROOT)
        return -EPERM;
    birth = lsf_device_record(&factory.pool, state->owner, parent,
        factory.pool.records[parent.slot].kind);
    if (!birth || (birth->deferred != LSF_PREPAID_PRIVATE &&
                   birth->deferred != LSF_PREPAID_PUBLISHED)) return -EPERM;
    /* Allocator charges exact extent/start padding/record generation BEFORE
     * the caller initializes or publishes any address. Original caps apply. */
    if (!lsf_device_allocate_stream_aligned(&factory.pool, state->owner, bytes,
            kind, parent, ticket, 64u, offset))
        return -ENOBUFS;
    return 1;
}

/* Called from the real private pci_enter AFTER its original constructor fence,
 * while factory_lock is held, BEFORE the first PCI or RX/DMA view is used.
 * These two functions read compiled type geometry only; neither allocates. */
static int lsf_stream_rx_constructor_reserve(void)
{
    struct lsf_stream_ring_geometry geometry = {};
    unsigned long flags;
    int result = -EPERM;
    lockdep_assert_held(&factory_lock);
    if (lsf_prepaid_stream_net_geometry(&geometry) ||
        lsf_prepaid_stream_ring_geometry(&geometry)) return -EOPNOTSUPP;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.device || !factory.device->constructor_active ||
        factory.device->constructor_task != current || factory.device->pci_attempted ||
        current->mm != factory.mm || current_cred() != factory.cred ||
        task_tgid(current) != factory.tgid || !current->nsproxy ||
        current->nsproxy->net_ns != factory.net) goto out;
    result = lsf_stream_rx_preallocate_locked(geometry);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
