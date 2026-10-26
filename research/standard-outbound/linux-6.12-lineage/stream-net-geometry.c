/* SPDX-License-Identifier: GPL-2.0-only */
/* Include in selected pinned virtio_net.c AFTER its private type definitions.
 * Actual sizes only; does not allocate, negotiate features, refill or publish. */
#include <net/lsf_stream_ring_profile_private.h>

int lsf_prepaid_stream_net_geometry(struct lsf_stream_ring_geometry *g)
{
    if (!g || (g->computed & LSF_STREAM_GEOMETRY_NET) ||
        SMP_CACHE_BYTES > 64 || __alignof__(struct skb_shared_info) > 64 ||
        __alignof__(struct sk_buff) > 64 || __alignof__(struct receive_queue) > 64 ||
        __alignof__(struct send_queue) > 64 ||
        LSF_STREAM_TX_DESCRIPTORS <= MAX_SKB_FRAGS + 2)
        return -EOPNOTSUPP;
    /* Fixed proposed modern VERSION_1, no mergeable/hash report/GSO/XDP;
     * actual feature admission MUST confirm these before the first allocation.
     * VERSION_1 still uses the original mrg_rxbuf header geometry. */
    g->rx_head_bytes = SKB_DATA_ALIGN(sizeof(struct virtio_net_hdr_mrg_rxbuf) +
        VIRTNET_RX_PAD + GOOD_PACKET_LEN) + SKB_DATA_ALIGN(sizeof(struct skb_shared_info));
    g->rx_header_bytes = sizeof(struct sk_buff);
    g->rx_queue_bytes = sizeof(struct receive_queue);
    g->tx_queue_bytes = sizeof(struct send_queue);
    g->computed |= LSF_STREAM_GEOMETRY_NET;
    return 0;
}

/* Original small-buffer recycler, with its real DMA/unposted ownership rules.
 * Only the previously admitted one-pair/small-RX platform can call this path. */
static void lsf_stream_rq_recycle(struct virtqueue *vq, void *buf)
{
    virtnet_rq_unmap_free_buf(vq, buf);
}

/* Called ONLY with actual vdev device_lock + SAME bank/device loan held by
 * factory stop. This leaves the original driver/device registered and paid;
 * original PCI driver removal must still execute every later release tail.
 * A failure leaves this partially stopped graph quarantined, never retries a
 * reset or proceeds through generic removal on the strength of an error. */
int lsf_prepaid_stream_net_quiesce(struct virtio_device *vdev)
{
    struct virtnet_info *vi;
    int result;
    if (!vdev || !vdev->dev.driver || !vdev->priv ||
        !vdev->config->synchronize_cbs)
        return -EOPNOTSUPP;
    vi = vdev->priv;
    if (vi->vdev != vdev || vi->max_queue_pairs != 1 || vi->has_cvq ||
        vi->big_packets || vi->mergeable_rx_bufs ||
        !vi->rq || !vi->sq || !vi->rq[0].vq || !vi->sq[0].vq ||
        vi->rq[0].xsk_pool || rcu_access_pointer(vi->rq[0].xdp_prog))
        return -EOPNOTSUPP;
    /* Original ndo_stop retires NAPI/refill/config/dim. Clearing IFF_UP via
     * dev_close prevents duplicate napi_disable in later unregister_netdev. */
    rtnl_lock();
    netif_device_detach(vi->dev);
    dev_close(vi->dev);
    rtnl_unlock();
    virtio_config_driver_disable(vdev);
    cancel_work_sync(&vi->config_work);
    disable_rx_mode_work(vi);
    flush_work(&vi->rx_mode_work);
    disable_delayed_refill(vi);
    cancel_delayed_work_sync(&vi->refill);
    synchronize_net();
    result = lsf_prepaid_stream_ring_stop(vi->sq[0].vq, virtnet_sq_free_unused_buf);
    if (result) return result;
    virtnet_sq_free_unused_buf_done(vi->sq[0].vq);
    result = lsf_prepaid_stream_ring_stop(vi->rq[0].vq, lsf_stream_rq_recycle);
    if (result) return result;
    return 0; /* Both queues remain reset; NO enable/resize/new allocation. */
}
