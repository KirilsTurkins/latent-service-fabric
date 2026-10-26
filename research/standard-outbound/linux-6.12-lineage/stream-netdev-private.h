/* SPDX-License-Identifier: GPL-2.0-only */
/* Private exact allocating/freeing source ports; no external cost/origin API. */
#ifndef LSF_STREAM_NETDEV_PRIVATE_H
#define LSF_STREAM_NETDEV_PRIVATE_H
struct net_device;
struct netdev_hw_addr_list;
struct lsf_stream_netdev_source { const struct net_device *device; };
int lsf_factory_stream_hw_addr_parent(const struct netdev_hw_addr_list *,
    struct lsf_stream_netdev_source *);
void *lsf_factory_stream_hw_addr_allocate(struct lsf_stream_netdev_source);
int lsf_factory_stream_hw_addr_publish(const void *, struct lsf_stream_netdev_source);
int lsf_factory_stream_hw_addr_queue(const void *);
int lsf_factory_stream_hw_addr_finish(const void *);
#endif
