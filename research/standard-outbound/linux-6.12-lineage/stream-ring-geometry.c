/* SPDX-License-Identifier: GPL-2.0-only */
/* Include in selected pinned virtio_ring.c AFTER its private type definitions.
 * No allocations, queue resize or changes to ordinary/constructor paths. */
#include <net/lsf_stream_ring_profile_private.h>

int lsf_prepaid_stream_ring_geometry(struct lsf_stream_ring_geometry *g)
{
    if (!g || (g->computed & LSF_STREAM_GEOMETRY_RING) || SMP_CACHE_BYTES > 64 ||
        __alignof__(struct vring_virtqueue) > 64 ||
        __alignof__(struct vring_desc_state_split) > 64 ||
        __alignof__(struct vring_desc_extra) > 64)
        return -EOPNOTSUPP;
    if (PAGE_SIZE != 4096) return -EOPNOTSUPP;
    g->ring_alignment = PAGE_SIZE;
    /* Split rings only. Packed/indirect/IOMMU/transport feature admission
     * remains the actual producer's job, not inferred from these numbers. */
    g->rx_ring_bytes = PAGE_ALIGN(vring_size(LSF_STREAM_RX_DESCRIPTORS, SMP_CACHE_BYTES));
    g->tx_ring_bytes = PAGE_ALIGN(vring_size(LSF_STREAM_TX_DESCRIPTORS, SMP_CACHE_BYTES));
    g->rx_state_bytes = sizeof(struct vring_desc_state_split) * LSF_STREAM_RX_DESCRIPTORS;
    g->tx_state_bytes = sizeof(struct vring_desc_state_split) * LSF_STREAM_TX_DESCRIPTORS;
    g->rx_extra_bytes = sizeof(struct vring_desc_extra) * LSF_STREAM_RX_DESCRIPTORS;
    g->tx_extra_bytes = sizeof(struct vring_desc_extra) * LSF_STREAM_TX_DESCRIPTORS;
    g->rx_vq_bytes = g->tx_vq_bytes = sizeof(struct vring_virtqueue);
    g->computed |= LSF_STREAM_GEOMETRY_RING;
    return 0;
}

int lsf_prepaid_stream_direct_dma(struct virtio_device *vdev)
{
    return vdev && !vring_use_dma_api(vdev);
}
