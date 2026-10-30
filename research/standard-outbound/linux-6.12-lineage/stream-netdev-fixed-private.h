/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef LSF_STREAM_NETDEV_FIXED_PRIVATE_H
#define LSF_STREAM_NETDEV_FIXED_PRIVATE_H
struct net_device;
struct virtio_device;
enum lsf_stream_netdev_fixed_child { LSF_STREAM_NETDEV_TX, LSF_STREAM_NETDEV_RX, LSF_STREAM_NETDEV_ETHTOOL };
struct net_device *lsf_prepaid_stream_alloc_netdev_mqs(struct virtio_device *, int,
    const char *, unsigned char, void (*)(struct net_device *), unsigned int, unsigned int);
struct net_device *lsf_prepaid_stream_alloc_etherdev_mqs(struct virtio_device *, int,
    unsigned int, unsigned int);
int lsf_factory_stream_netdev_selected(struct virtio_device *);
void *lsf_factory_stream_netdev_allocate(struct virtio_device *, unsigned long, int);
void *lsf_factory_stream_netdev_fixed_allocate(struct net_device *, enum lsf_stream_netdev_fixed_child, unsigned long);
int lsf_factory_stream_netdev_fixed_return(struct net_device *, enum lsf_stream_netdev_fixed_child);
int lsf_factory_stream_netdev_publish(struct net_device *);
int lsf_factory_stream_netdev_release(struct net_device *);
#endif
