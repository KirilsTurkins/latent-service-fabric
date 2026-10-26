/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef _LSF_STREAM_NETDEV_NAME_PRIVATE_H
#define _LSF_STREAM_NETDEV_NAME_PRIVATE_H
struct net_device;
int lsf_prepaid_stream_netdev_name_geometry(unsigned long *, unsigned long *);
int lsf_factory_stream_netdev_name_parent(const struct net_device *);
void *lsf_factory_stream_netdev_name_allocate(struct net_device *);
int lsf_factory_stream_netdev_name_publish(struct net_device *, const void *);
int lsf_factory_stream_netdev_name_return(const void *);
#endif
