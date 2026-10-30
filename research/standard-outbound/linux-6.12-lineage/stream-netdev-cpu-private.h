/* SPDX-License-Identifier: GPL-2.0-only */
/* Private typed CPU-indexed storage. NEVER an ordinary __percpu pointer. */
#ifndef LSF_STREAM_NETDEV_CPU_PRIVATE_H
#define LSF_STREAM_NETDEV_CPU_PRIVATE_H
#include <linux/atomic.h>
#include <linux/cpumask.h>
#include <linux/preempt.h>
#include <linux/smp.h>
struct net_device;
struct rtnl_link_stats64;
struct lsf_stream_netdev_cpu_storage {
    const struct net_device *device;
    unsigned int cpus;
    atomic_t fault;
    atomic_t references[NR_CPUS];
    atomic_long_t stats[NR_CPUS][4];
} __aligned(64);
int lsf_factory_stream_netdev_cpu_allocate(struct net_device *);
int lsf_factory_stream_netdev_cpu_retire(struct net_device *);
void lsf_stream_netdev_cpu_get(struct net_device *);
void lsf_stream_netdev_cpu_put(struct net_device *);
int lsf_stream_netdev_cpu_ref_read(const struct net_device *);
void lsf_stream_netdev_cpu_stats_inc(struct net_device *, u32);
void lsf_stream_netdev_cpu_stats_add(const struct net_device *, struct rtnl_link_stats64 *);
#endif
