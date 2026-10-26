/* SPDX-License-Identifier: GPL-2.0-only */
/* Unselected proposed physical geometry, NOT a guest/runtime budget/profile. */
#ifndef LSF_STREAM_RING_PROFILE_PRIVATE_H
#define LSF_STREAM_RING_PROFILE_PRIVATE_H
#include <linux/errno.h>
#include <linux/overflow.h>
#include <linux/types.h>

#define LSF_STREAM_RX_DESCRIPTORS 32u
#define LSF_STREAM_TX_DESCRIPTORS 64u
#define LSF_STREAM_GEOMETRY_NET 1u
#define LSF_STREAM_GEOMETRY_RING 2u
#define LSF_STREAM_GEOMETRY_ANCESTORS 4u
#define LSF_STREAM_GEOMETRY_ALL 7u

/* Private producer-computed values, never userspace/serialized inputs. Each
 * producer uses its actual compiled types and owns its geometry bit. This is
 * arithmetic, not an allocation ticket, authority or physical-return proof. */
struct lsf_stream_ring_geometry {
    u64 rx_head_bytes, rx_header_bytes;
    u64 rx_queue_bytes, tx_queue_bytes;
    u64 rx_ring_bytes, tx_ring_bytes, ring_alignment;
    u64 rx_state_bytes, tx_state_bytes;
    u64 rx_extra_bytes, tx_extra_bytes;
    u64 rx_vq_bytes, tx_vq_bytes;
    /* Actual original Root/device/security/neighbour/cleanup/borrow-plan
     * extent and records. Missing source producers MUST leave its bit clear. */
    u64 ancestor_bytes, ancestor_records;
    unsigned int computed;
};

int lsf_prepaid_stream_net_geometry(struct lsf_stream_ring_geometry *);
int lsf_prepaid_stream_ring_geometry(struct lsf_stream_ring_geometry *);

struct pci_dev;
struct virtio_device;
struct virtqueue;
enum lsf_stream_queue_view {
    LSF_STREAM_RX_QUEUE, LSF_STREAM_TX_QUEUE,
    LSF_STREAM_RX_RING, LSF_STREAM_TX_RING,
    LSF_STREAM_RX_STATE, LSF_STREAM_TX_STATE,
    LSF_STREAM_RX_EXTRA, LSF_STREAM_TX_EXTRA,
    LSF_STREAM_RX_VQ, LSF_STREAM_TX_VQ
};
int lsf_factory_stream_queue_count(struct pci_dev *, struct virtio_device *, unsigned int, unsigned int);
void *lsf_factory_stream_queue_view(struct virtio_device *, enum lsf_stream_queue_view, unsigned long);
struct virtqueue *lsf_prepaid_stream_ring_create(unsigned int, unsigned int,
    unsigned int, struct virtio_device *, bool, bool,
    bool (*)(struct virtqueue *), void (*)(struct virtqueue *), const char *);
int lsf_prepaid_stream_direct_dma(struct virtio_device *);
int lsf_prepaid_stream_ring_release(struct virtqueue *);
int lsf_prepaid_stream_ring_stop(struct virtqueue *, void (*)(struct virtqueue *, void *));
int lsf_prepaid_stream_net_quiesce(struct virtio_device *);
int lsf_factory_stream_ring_owned(const void *, unsigned long);
int lsf_factory_stream_ring_return(struct virtio_device *, unsigned int,
    const void *, const void *, const void *, const void *);
struct lsf_stream_ring_views { void *ring, *state, *extra, *vq; };
struct lsf_stream_net_views { void *rx, *tx; };
int lsf_factory_stream_net_queues(struct virtio_device *, unsigned int, bool,
    bool, bool, unsigned long, unsigned long, struct lsf_stream_net_views *);
int lsf_factory_stream_net_queues_return(struct virtio_device *, const void *, const void *);
struct sk_buff;
int lsf_factory_stream_rx_take(struct virtio_device *, unsigned long, void **);
int lsf_factory_stream_rx_unposted(void *);
int lsf_factory_stream_rx_header(void *, unsigned long, struct sk_buff **);
int lsf_factory_stream_rx_data_return(const void *);
int lsf_factory_stream_rx_header_return(const void *);
int lsf_factory_stream_ring_views(struct virtio_device *, unsigned int,
    unsigned long, unsigned long, unsigned long, unsigned long,
    struct lsf_stream_ring_views *);
#endif
