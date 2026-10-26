/* SPDX-License-Identifier: GPL-2.0-only */
/* After actual stream operations/RX state, before the original FD release.
 * No selected consumer is supplied. Constructor-only release/mint/collector
 * remain original. Unknown normal teardown retains SAME paid graph. */

/* Successful original recycle is a per-slot inductive history fence: every
 * reuse requires ALL original records returned before generation reset. The
 * latest born identity cannot be replaced or forged by a userspace request.
 * The original never-wrap pool generation and lease rules remain in force.
 * This does NOT establish device/Root final-free or current physical bytes. */
static int lsf_stream_contexts_retired_locked(void)
{
    unsigned int i, word;
    lockdep_assert_held(&factory_lock);
    lockdep_assert_held(&pool_lock);
    if (!factory.pool.stopped || factory.inflight || factory.reply_pending ||
        factory.pool.poisoned || READ_ONCE(factory.uncertain))
        return 0;
    for (i = 0; i < LSF_FACTORY_CONTEXTS; ++i) {
        struct lsf_factory_context *context = &factory.contexts[i];
        struct lsf_prepaid_context *owner = &factory.pool.contexts[i];
        if (owner->generation || owner->cursor || owner->live || owner->continuations ||
            owner->poisoned || owner->closed != 1 || context->socket)
            return 0;
        for (word = 0; word < 8; ++word)
            if (owner->scope.identity[word]) return 0;
        if (!context->key.generation) {
            if (context->key.slot || context->lease || context->net ||
                context->stream.sequence || context->stream.expiry || context->stream.retired)
                return 0;
        } else if (context->key.slot != i || !context->lease ||
            context->lease > factory.last_lease || context->net != factory.net ||
            context->key.generation >= factory.pool.next_generation ||
            context->stream.retired != 1)
            return 0;
    }
    /* Original owner table has64 slots. Only the four application slots and
     * actual LSF_DEVICE_OWNER_SLOT may ever carry state in this profile. */
    for (i = LSF_FACTORY_CONTEXTS; i < LSF_OWNER_SLOTS; ++i) {
        struct lsf_prepaid_context *owner = &factory.pool.contexts[i];
        if (i == LSF_DEVICE_OWNER_SLOT) continue;
        if (owner->generation || owner->cursor || owner->live || owner->continuations ||
            owner->closed || owner->poisoned) return 0;
        for (word = 0; word < 8; ++word)
            if (owner->scope.identity[word]) return 0;
    }
    return 1;
}

/* Called after actual admission close, BEFORE existing paid cleanup-worker
 * destruction. Holds SAME Root bank plus real PCI and vdev references across
 * every unlocked driver/IRQ callback. No put/physical drop under either lock.
 * No retry on partially completed reset; unknown permanently retains graph. */
static int lsf_factory_stream_stop(void)
{
    struct lsf_stream_rx_state *state;
    struct pci_dev *pci;
    struct virtio_device *vdev;
    unsigned long flags;
    unsigned int held = 0;
    int result = -EOPNOTSUPP;
    if (!lsf_factory_selected_consumer()) return 0;
    mutex_lock(&factory_lock);
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    if (!state || state->closing || state->stopped || state->device_borrows ||
        !lsf_stream_contexts_retired_locked() || !state->pci || !state->virtio ||
        !state->material || state->material_returned ||
        !lsf_stream_material_seal_unused_locked(state->material) ||
        !lsf_stream_rx_device_get_locked(state, &held))
        goto refuse;
    state->closing = 1; /* No further RX loans/queue construction admitted. */
    pci = (struct pci_dev *)state->pci;
    vdev = (struct virtio_device *)state->virtio;
    spin_unlock_irqrestore(&pool_lock, flags);
    mutex_unlock(&factory_lock);
    if (held == 3) {
        device_lock(&vdev->dev);
        result = lsf_prepaid_stream_net_quiesce(vdev);
        device_unlock(&vdev->dev);
    } else result = -ENODEV;
    if (!result) {
        mutex_lock(&factory_lock);
        spin_lock_irqsave(&pool_lock, flags);
        if (lsf_stream_rx_current_locked() != state || state->device_borrows != 1 ||
            !lsf_stream_contexts_retired_locked()) result = -EIO;
        else state->hardware_stopped = 1;
        spin_unlock_irqrestore(&pool_lock, flags);
        mutex_unlock(&factory_lock);
    }
    if (!result) {
        /* Original PCI removal owns driver detach, real NAPI/RCU, IRQ release,
         * transport/BAR and kobject tails. The retained references below may
         * delay final physical destructors; bank borrow covers ALL of them. */
        pci_stop_and_remove_bus_device_locked(pci);
    }
    /* Both original device references are put while the bank borrow remains
     * counted. Their original release callbacks may use their OWN locks. */
    if (!lsf_stream_rx_device_put(state, pci, vdev, held, !result)) result = -EIO;
    mutex_lock(&factory_lock);
    spin_lock_irqsave(&pool_lock, flags);
    if (result || lsf_stream_rx_current_locked() != state || state->device_borrows ||
        !lsf_stream_contexts_retired_locked())
        goto refuse;
    /* Original removal has returned; retained packet/callback views can still
     * outlive it. The separate normal Root collector must verify every one. */
    spin_unlock_irqrestore(&pool_lock, flags);
    mutex_unlock(&factory_lock);
    return 0;
refuse:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
    spin_unlock_irqrestore(&pool_lock, flags);
    mutex_unlock(&factory_lock);
    return result ? result : -EIO;
}
