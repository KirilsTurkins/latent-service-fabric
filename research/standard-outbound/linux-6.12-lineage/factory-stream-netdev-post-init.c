/* SPDX-License-Identifier: GPL-2.0-only */
/* Same records, constructor actor and real positive VIRTIO parent. No new
 * allocation, field, table, borrowed-view adoption or authority renewal. */
#include <net/lsf_stream_netdev_post_init_private.h>

int lsf_factory_stream_netdev_preinit(struct net_device *dev,
    struct virtio_device **output)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *record, *birth;
    struct lsf_prepaid_ticket ticket = {}, parent = {}, same = {};
    struct virtio_device *vdev;
    unsigned long flags, base;
    int result = -EOPNOTSUPP;
    if (!output) return -EOPNOTSUPP;
    *output = NULL;
    if (!lsf_factory_selected_consumer()) return 0;
    spin_lock_irqsave(&pool_lock, flags);
    /* The ordinary register_netdevice caller supplies a live native object.
     * Preserve outside/outside routing; mixed ancestry is never adoption. */
    if (dev && !lsf_stream_rx_address_locked(dev)) {
        result = lsf_stream_rx_address_locked(dev->dev.parent) ? -EOPNOTSUPP : 0;
        if (!result) goto out;
        goto poison;
    }
    state = lsf_stream_rx_current_locked();
    record = lsf_stream_netdev_record_locked(state, dev, &ticket);
    if (!record || !lsf_stream_constructor_current_locked(state) ||
        record->deferred != LSF_PREPAID_PUBLISHED ||
        record->security_cache_location != 1u || record->security_cache_identity)
        goto poison;
    parent = (struct lsf_prepaid_ticket){record->cache_bucket, record->cache_anchor};
    birth = lsf_device_record(&factory.pool, state->owner, parent, LSF_DEVICE_VIRTIO);
    if (!birth || birth->bytes < sizeof(*vdev) ||
        birth->offset > LSF_BACKING_BYTES - sizeof(*vdev)) goto poison;
    base = (unsigned long)page_address(factory.pages);
    vdev = (void *)(base + birth->offset);
    if (!lsf_stream_rss_parent_locked(state, vdev, &same) ||
        same.slot != parent.slot || same.generation != parent.generation ||
        dev->dev.parent != &vdev->dev || dev_net(dev) != factory.net ||
        dev->reg_state != NETREG_UNINITIALIZED || dev->dev.kobj.state_initialized)
        goto poison;
    *output = vdev;
    result = 1;
    goto out;
poison:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
