/* SPDX-License-Identifier: GPL-2.0-only */
/* Original virtio_net always allocates its RSS header, even when RSS is off.
 * This fixed source port funds that actual typed birth, never a caller cost
 * certificate. No control/RSS command, replacement or ambient allocation. */
#include <net/lsf_stream_material_geometry_private.h>

/* RSS birth precedes alloc_queues. Authenticate the original VIRTIO and PCI
 * records before dereferencing either, rather than adopting vdev->priv. */
static int lsf_stream_rss_parent_locked(struct lsf_stream_rx_state *state,
    struct virtio_device *vdev, struct lsf_prepaid_ticket *parent)
{
    struct lsf_prepaid_view *birth = NULL, *pci_record;
    struct lsf_prepaid_ticket pci_ticket;
    struct pci_dev *pci;
    unsigned long base, at = (unsigned long)vdev;
    unsigned int i;
    lockdep_assert_held(&pool_lock);
    if (!state || !parent || state->closing || state->stopped ||
        !lsf_stream_rx_address_locked(vdev)) return 0;
    base = (unsigned long)page_address(factory.pages);
    if (at - base > LSF_BACKING_BYTES - sizeof(*vdev)) return 0;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        struct lsf_prepaid_view *record = &factory.pool.records[i];
        if (record->offset != at - base || record->bytes < sizeof(*vdev) ||
            (record->deferred != LSF_PREPAID_PRIVATE && record->deferred != LSF_PREPAID_PUBLISHED))
            continue;
        if (lsf_device_record(&factory.pool, state->owner,
                (struct lsf_prepaid_ticket){i, record->generation}, LSF_DEVICE_VIRTIO)) {
            birth = record; *parent = (struct lsf_prepaid_ticket){i, record->generation}; break;
        }
    }
    if (!birth) return 0;
    pci_ticket = (struct lsf_prepaid_ticket){birth->cache_bucket, birth->cache_anchor};
    pci_record = lsf_device_record(&factory.pool, state->owner, pci_ticket, LSF_DEVICE_PCI);
    if (!pci_record || pci_record->bytes < sizeof(*pci)) return 0;
    pci = (void *)(base + pci_record->offset);
    if (vdev->dev.parent != &pci->dev || vdev->id.device != VIRTIO_ID_NET ||
        !virtio_has_feature(vdev, VIRTIO_F_VERSION_1) ||
        !virtio_has_feature(vdev, VIRTIO_F_RING_RESET) || !vdev->config->synchronize_cbs ||
        virtio_has_feature(vdev, VIRTIO_F_RING_PACKED) ||
        virtio_has_feature(vdev, VIRTIO_RING_F_INDIRECT_DESC) ||
        !lsf_prepaid_stream_direct_dma(vdev) ||
        (state->virtio && state->virtio != vdev) || (state->pci && state->pci != pci))
        return 0;
    state->pci = pci; state->virtio = vdev;
    return 1;
}

int lsf_factory_stream_rss_take(struct virtio_device *vdev, bool rss, bool hash_report,
    unsigned long actual_bytes, struct virtio_net_rss_config_hdr **slot)
{
    struct lsf_stream_net_material_geometry geometry;
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_ticket parent, ticket;
    u64 offset;
    unsigned long flags;
    int result = -EOPNOTSUPP;
    if (!slot) return -EINVAL;
    if (!lsf_factory_selected_consumer()) return 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (vdev && !lsf_stream_rx_address_locked(vdev)) {
        result = lsf_stream_rx_address_locked(vdev->dev.parent) ? -EOPNOTSUPP : 0;
        goto out;
    }
    if (*slot || rss || hash_report ||
        lsf_prepaid_stream_net_material_geometry(&geometry) ||
        !geometry.rss_bytes || geometry.rss_bytes > ULONG_MAX - 63u ||
        actual_bytes != geometry.rss_bytes) goto out;
    state = lsf_stream_rx_current_locked();
    if (!lsf_stream_rss_parent_locked(state, vdev, &parent)) goto out;
    result = lsf_stream_constructor_allocate_locked(state, LSF_DEVICE_RSS_HEADER,
        parent, geometry.rss_bytes, geometry.rss_alignment, &ticket, &offset);
    if (result == 1) {
        memset((char *)page_address(factory.pages) + offset, 0, geometry.rss_bytes);
        if (!lsf_device_publish(&factory.pool, state->owner, ticket, LSF_DEVICE_RSS_HEADER)) {
            factory.pool.poisoned = state->poisoned = 1;
            WRITE_ONCE(factory.uncertain, 1); result = -EIO; goto out;
        }
        *slot = (void *)((char *)page_address(factory.pages) + offset);
    }
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Successful remove reaches this only after the original flush/unregister/
 * reset/free_vqs path. Never dereference vdev after its original device put.
 * A failed probe may not reach that path: its row then remains paid/retained,
 * rather than claiming a free which the original source does not perform. */
int lsf_factory_stream_rss_return(struct virtio_device *vdev,
    struct virtio_net_rss_config_hdr **slot)
{
    struct lsf_stream_net_material_geometry geometry;
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *record, *parent;
    struct lsf_prepaid_ticket ticket;
    unsigned long flags, at, base;
    unsigned int i;
    int result = 0;
    if (!slot || !*slot) return 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_stream_rx_address_locked(*slot)) goto out;
    result = -1;
    state = lsf_stream_rx_current_locked();
    if (!state || state->virtio != vdev ||
        lsf_prepaid_stream_net_material_geometry(&geometry) ||
        !geometry.rss_bytes || geometry.rss_bytes > ULONG_MAX - 63u) goto poison;
    base = (unsigned long)page_address(factory.pages); at = (unsigned long)*slot;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->offset != at - base) continue;
        ticket = (struct lsf_prepaid_ticket){i, record->generation};
        if (!lsf_device_record(&factory.pool, state->owner, ticket, LSF_DEVICE_RSS_HEADER) ||
            record->deferred != LSF_PREPAID_PUBLISHED ||
            record->bytes != ((geometry.rss_bytes + 63u) & ~63ull)) goto poison;
        parent = lsf_device_record(&factory.pool, state->owner,
            (struct lsf_prepaid_ticket){record->cache_bucket, record->cache_anchor}, LSF_DEVICE_VIRTIO);
        if (!parent || (void *)(base + parent->offset) != vdev) goto poison;
        *slot = NULL; /* Actual driver alias clears before actual view return. */
        if (!lsf_device_queue(&factory.pool, state->owner, ticket, LSF_DEVICE_RSS_HEADER) ||
            !lsf_device_finish(&factory.pool, state->owner, ticket, LSF_DEVICE_RSS_HEADER))
            goto poison;
        result = 1; goto out;
    }
poison:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
