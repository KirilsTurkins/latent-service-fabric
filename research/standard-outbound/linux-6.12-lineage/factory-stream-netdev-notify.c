/* SPDX-License-Identifier: GPL-2.0-only */
/* Finite unselected NETDEV notification profile. No new allocation, reference,
 * state field, table or lock. Original actors and positive parents remain held. */
#include <net/lsf_stream_netdev_notify_private.h>

int lsf_factory_stream_netdev_notify_kind(const struct device *device)
{
    if (!lsf_factory_selected_consumer()) return 0;
    return lsf_factory_stream_netdev_core_classify(device, 0);
}

/* Physical/lifecycle authentication, not admission to a new constructor. This
 * permits the paired pre-file remove while the original context is closing.
 * Poisoned or unknown native state is retained; no late payload is adopted. */
int lsf_factory_stream_netdev_notify_lifetime(const struct device *device)
{
    struct lsf_stream_rx_state *state;
    struct lsf_stream_netdev_directory_source source;
    struct lsf_prepaid_ticket parent, child;
    struct lsf_prepaid_view *r, *metadata;
    struct net_device *dev, *same;
    unsigned long flags, bytes, alignment, base;
    int kind = lsf_factory_stream_netdev_notify_kind(device), result = -EOPNOTSUPP;
    if (kind <= 0) return kind;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    r = lsf_stream_netdev_core_parent_locked(state, device, 0, &parent, &dev);
    if (!r || r->deferred != LSF_PREPAID_PUBLISHED ||
        r->security_cache_identity != LSF_STREAM_NETDEV_CORE) goto poison;
    lsf_stream_netdev_directory_copy(&dev->dev.kobj, parent, LSF_DEVICE_NETDEV, r, &source);
    if (lsf_stream_netdev_directory_parent_locked(state, source, &same) != r || same != dev ||
        !lsf_stream_netdev_core_shape(&bytes, &alignment)) goto poison;
    metadata = lsf_stream_netdev_core_child_locked(state, parent, &child);
    if (!metadata || lsf_device_record(&factory.pool, state->owner, child,
            LSF_DEVICE_NETDEV_CORE) != metadata ||
        metadata->deferred != LSF_PREPAID_PUBLISHED || metadata->offset % alignment ||
        metadata->bytes != ((bytes + 63u) & ~63ull)) goto poison;
    base = (unsigned long)page_address(factory.pages);
    if (dev->dev.p != (void *)(base + metadata->offset) || dev->dev.platform_data != dev ||
        !dev->dev.kobj.state_initialized || !dev->dev.kobj.state_in_sysfs ||
        dev->dev.kobj.state_add_uevent_sent || dev->dev.kobj.state_remove_uevent_sent ||
        !dev->dev.kobj.sd || !dev->dev.kobj.parent ||
        dev->dev.fwnode || dev->dev.of_node || dev->dev.type || dev->dev.bus || dev->dev.driver)
        goto poison;
    result = 1;
    goto out;
poison:
    lsf_stream_netdev_directory_unknown_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_netdev_notify_profile(const struct device *device)
{
    int kind = lsf_factory_stream_netdev_notify_kind(device);
    if (kind <= 0) return kind;
    if (lsf_factory_stream_netdev_directory_added(device) != 1)
        return -EOPNOTSUPP;
    return lsf_factory_stream_netdev_notify_lifetime(device);
}

/* Guard only the actual maintained owned NETDEV route. These finite setter
 * cuts are not a theorem about arbitrary kernel direct writes. A rejected
 * void mutator poisons the ORIGINAL bank: the constructor's post-call check
 * observes refusal, and no successful/clean receipt or refund can follow. */
int lsf_factory_stream_netdev_notify_firmware_write(const struct device *device)
{
    int kind = lsf_factory_stream_netdev_notify_kind(device);
    if (!kind) return 0; /* Ordinary/PCI source keeps its original body. */
    lsf_factory_stream_netdev_directory_retain_unknown();
    return -EOPNOTSUPP;
}

/* Inspect the actual software notifier's LOCAL decision before its first
 * link/get/put. A pre-call pool check is not used as a native writer lock. */
int lsf_factory_stream_netdev_notify_software_decision(const struct device *device,
    const void *node)
{
    int kind = lsf_factory_stream_netdev_notify_kind(device);
    if (kind <= 0) return kind;
    if (!node && lsf_factory_stream_netdev_notify_lifetime(device) == 1) return 1;
    lsf_factory_stream_netdev_directory_retain_unknown();
    return -EOPNOTSUPP;
}
