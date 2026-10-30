/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef _LSF_STREAM_NETDEV_CORE_PRIVATE_H
#define _LSF_STREAM_NETDEV_CORE_PRIVATE_H
struct net_device;
#define LSF_STREAM_NETDEV_RELEASE 1u
#define LSF_STREAM_NETDEV_CORE 2u
#define LSF_STREAM_NETDEV_TAIL_ACTIVE 4u
#define LSF_STREAM_NETDEV_TAIL_DONE 8u
int lsf_prepaid_stream_netdev_core_geometry(unsigned long *, unsigned long *);
int lsf_factory_stream_netdev_core_classify(const void *, unsigned int);
int lsf_factory_stream_netdev_core_begin(struct net_device *);
int lsf_factory_stream_netdev_core_name(struct net_device *);
int lsf_factory_stream_netdev_core_name_return(const void *, const void *);
int lsf_factory_stream_netdev_core_owned(const void *);
void *lsf_factory_stream_netdev_core_allocate(const void *, unsigned long);
int lsf_factory_stream_netdev_core_return(const void *, const void *);
int lsf_factory_stream_netdev_core_tail_enter(const void *);
int lsf_factory_stream_netdev_core_tail_finish(const void *);
#endif
