/* SPDX-License-Identifier: GPL-2.0-only */
/* Include in exact pinned virtio_ring.c AFTER original private helpers.
 * Original nonallocation initializer copied below, with exact source proof.
 * All actual buffers/arrays/VQ already live in SAME prepaid Node bank. */
#include <net/lsf_stream_ring_profile_private.h>

static struct virtqueue *lsf_stream_ring_initialize(unsigned int index,
					       struct vring_virtqueue_split *vring_split,
					       struct virtio_device *vdev,
					       bool weak_barriers,
					       bool context,
					       bool (*notify)(struct virtqueue *),
					       void (*callback)(struct virtqueue *),
					       const char *name,
					       struct device *dma_dev,
                                               struct vring_virtqueue *prepaid_vq)
{
	struct vring_virtqueue *vq;

	if (virtio_has_feature(vdev, VIRTIO_F_RING_PACKED))
		return NULL;

	vq = prepaid_vq;
	if (!vq)
		return NULL;

	vq->packed_ring = false;
	vq->vq.callback = callback;
	vq->vq.vdev = vdev;
	vq->vq.name = name;
	vq->vq.index = index;
	vq->vq.reset = false;
	vq->we_own_ring = true; /* SAME paid Node owner; never heap-free. */
	vq->notify = notify;
	vq->weak_barriers = weak_barriers;
#ifdef CONFIG_VIRTIO_HARDEN_NOTIFICATION
	vq->broken = true;
#else
	vq->broken = false;
#endif
	vq->dma_dev = dma_dev;
	vq->use_dma_api = vring_use_dma_api(vdev);
	vq->premapped = false;
	vq->do_unmap = vq->use_dma_api;

	vq->indirect = virtio_has_feature(vdev, VIRTIO_RING_F_INDIRECT_DESC) &&
		!context;
	vq->event = virtio_has_feature(vdev, VIRTIO_RING_F_EVENT_IDX);

	if (virtio_has_feature(vdev, VIRTIO_F_ORDER_PLATFORM))
		vq->weak_barriers = false;

	virtqueue_vring_init_split(vring_split, vq);

	virtqueue_init(vq, vring_split->vring.num);
	virtqueue_vring_attach_split(vq, vring_split);

	spin_lock(&vdev->vqs_list_lock);
	list_add_tail(&vq->vq.list, &vdev->vqs);
	spin_unlock(&vdev->vqs_list_lock);
	return &vq->vq;
}

struct virtqueue *lsf_prepaid_stream_ring_create(unsigned int index, unsigned int num,
    unsigned int alignment, struct virtio_device *vdev, bool weak_barriers, bool context,
    bool (*notify)(struct virtqueue *), void (*callback)(struct virtqueue *), const char *name)
{
    struct lsf_stream_ring_views views;
    struct vring_virtqueue_split split = {};
    struct vring_desc_extra *extra;
    unsigned int i, expected = index ? LSF_STREAM_TX_DESCRIPTORS : LSF_STREAM_RX_DESCRIPTORS;
    if (index > 1 || num != expected || alignment != SMP_CACHE_BYTES ||
        vring_use_dma_api(vdev) || virtio_has_feature(vdev, VIRTIO_F_RING_PACKED) ||
        virtio_has_feature(vdev, VIRTIO_RING_F_INDIRECT_DESC) ||
        lsf_factory_stream_ring_views(vdev, index, PAGE_ALIGN(vring_size(num, alignment)),
            num * sizeof(struct vring_desc_state_split), num * sizeof(struct vring_desc_extra),
            sizeof(struct vring_virtqueue), &views))
        return NULL;
    /* Equivalent direct-DMA address construction to original vring_alloc_queue,
     * without allocating or freeing another page extent. Unsupported DMA was
     * refused BEFORE this tuple. No map/IOMMU/security setting is modified. */
    split.queue_dma_addr = virt_to_phys(views.ring);
    split.queue_size_in_bytes = vring_size(num, alignment);
    split.vring_align = alignment;
    split.may_reduce_num = false; // Exact funded geometry, no uncharged fallback.
    vring_init(&split.vring, num, views.ring, alignment);
    split.desc_state = views.state; split.desc_extra = views.extra;
    extra = views.extra;
    for (i = 0; i < num - 1; ++i)
        extra[i].next = i + 1; // Original vring_alloc_desc_extra free-list setup.
    return lsf_stream_ring_initialize(index, &split, vdev, weak_barriers, context,
        notify, callback, name, vdev->dev.parent, views.vq);
}

/* Stop-only use of the ORIGINAL reset/ACK/unused-buffer recycler. The public
 * virtqueue_reset API would re-enable the queue and is intentionally NOT used.
 * Driver has stopped TX/NAPI/refill and holds its actual device lock/Root loan.
 * No error/timeout/status bit substitutes for transport acknowledgement. */
int lsf_prepaid_stream_ring_stop(struct virtqueue *queue,
    void (*recycle)(struct virtqueue *, void *))
{
    struct vring_virtqueue *vq = to_vvq(queue);
    struct virtio_device *vdev;
    int result;
    if (lsf_factory_stream_ring_owned(vq, sizeof(*vq)) != 1) return -EOPNOTSUPP;
    vdev = queue->vdev; /* Only after original typed bank ownership check. */
    if (vq->packed_ring || vq->use_dma_api || queue->reset || !recycle ||
        !virtio_has_feature(vdev, VIRTIO_F_RING_RESET) ||
        !vdev->config->synchronize_cbs)
        return -EOPNOTSUPP;
    result = virtqueue_disable_and_recycle(queue, recycle);
    if (result) return result;
    /* Exact modern synchronize_cbs is vp_synchronize_vectors: includes shared
     * INTx/MSI-X and exclusive vectors. Actual reset callback already unlinked
     * this queue under the SAME shared IRQ list lock before setting reset. */
    vdev->config->synchronize_cbs(vdev);
    if (!queue->reset || queue->num_free != vq->split.vring.num)
        return -EBUSY;
    return 0;
}

int lsf_prepaid_stream_ring_release(struct virtqueue *queue)
{
    struct vring_virtqueue *vq = to_vvq(queue);
    int owned = lsf_factory_stream_ring_owned(vq, sizeof(*vq));
    if (owned != 1) return owned;
    /* reset is latched by actual pinned transport callback AFTER device ACK
     * and synchronize_irq. Last unused-buffer recycle precedes num_free==num.
     * Failure retains original bank, never reaches generic free/kfree. */
    if (vq->packed_ring || !queue->reset || vq->use_dma_api ||
        queue->num_free != vq->split.vring.num)
        return -1;
    return lsf_factory_stream_ring_return(queue->vdev, queue->index,
        vq->split.vring.desc, vq->split.desc_state, vq->split.desc_extra, vq);
}
