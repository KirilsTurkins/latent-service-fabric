/* SPDX-License-Identifier: GPL-2.0-only */
/* WIP uninstalled selected-profile no-tap admission fence. Included in the
 * built-in factory TU after its static pool_lock/factory and before open.
 * The actual multicast LISTEN_ALL_NSID path can deliver to any receiver net;
 * every tap therefore participates. This is admission metadata, not storage
 * ownership, a caller-supplied authority or a claim that all nets receive.
 * Its static footprint remains part of the unqualified NodeFixed image. */
static struct {
    u64 taps;
    unsigned int private_alive, poisoned;
} lsf_device_uevent_taps;

/* Same short pool spin extent on both sides. No callback, allocator, RTNL,
 * per-net mutex, module operation, wait or RCU barrier occurs while held. */
int lsf_factory_device_tap_admit(struct netlink_tap *tap)
{
    unsigned long flags;
    int error = -EBUSY;
    spin_lock_irqsave(&pool_lock, flags);
    if (!tap || lsf_device_uevent_taps.poisoned)
        goto out;
    if (tap->lsf_device_uevent_admitted) {
        /* An unknown or still-RCU-retiring birth cannot forge absence. */
        lsf_device_uevent_taps.poisoned = 1;
        WRITE_ONCE(factory.uncertain, 1);
        goto out;
    }
    if (lsf_device_uevent_taps.private_alive || lsf_device_uevent_taps.taps == U64_MAX)
        goto out;
    tap->lsf_device_uevent_admitted = 1;
    ++lsf_device_uevent_taps.taps;
    error = 0;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return error;
}

/* Called ONLY after original successful list_del_rcu and synchronize_net.
 * The real ndo_stop caller still owns its netdev_priv tap until return. An
 * unsuccessful unlink never calls this, and the internal marker remains live
 * throughout the actual RCU wait and any intervening re-add attempt. */
void lsf_factory_device_tap_retired(struct netlink_tap *tap)
{
    unsigned long flags;
    spin_lock_irqsave(&pool_lock, flags);
    if (!tap || tap->lsf_device_uevent_admitted != 1 ||
        !lsf_device_uevent_taps.taps) {
        lsf_device_uevent_taps.poisoned = 1;
        WRITE_ONCE(factory.uncertain, 1);
        goto out;
    }
    tap->lsf_device_uevent_admitted = 0;
    --lsf_device_uevent_taps.taps;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
}

/* Caller holds existing factory_lock. Reserve BEFORE real alloc_pages and
 * selected callbacks. Pending add publication and RCU-retiring removals count.
 * Static zero initialization is valid only for the actual built-in bool
 * profile; a late registrar cannot assert historical absence. */
static int lsf_factory_device_uevent_bank_enter(void)
{
    unsigned long flags;
    int error = -EBUSY;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_device_uevent_taps.poisoned && !lsf_device_uevent_taps.private_alive &&
        !lsf_device_uevent_taps.taps && !factory.pages) {
        lsf_device_uevent_taps.private_alive = 1;
        error = 0;
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return error;
}

/* Only the actual alloc_pages failure may undo the reservation: no backing
 * or device exists on that path. Initialization errors with pages, descriptor
 * close, zero records or timeout CANNOT clear the fence. Current provider has
 * no final backing-return path, so none is invented. Future real teardown must
 * prove all callbacks/queues/RCU retired, free backing, THEN clear this flag. */
static void lsf_factory_device_uevent_bank_allocation_failed(void)
{
    unsigned long flags;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.pages && lsf_device_uevent_taps.private_alive == 1 &&
        !lsf_device_uevent_taps.taps && !lsf_device_uevent_taps.poisoned)
        lsf_device_uevent_taps.private_alive = 0;
    else {
        lsf_device_uevent_taps.poisoned = 1;
        WRITE_ONCE(factory.uncertain, 1);
    }
    spin_unlock_irqrestore(&pool_lock, flags);
}
