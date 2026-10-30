/* SPDX-License-Identifier: GPL-2.0-only */
/* Closed source-owned POST_INIT identities; no caller-selected callback list. */
#ifndef LSF_STREAM_NETDEV_POST_INIT_PRIVATE_H
#define LSF_STREAM_NETDEV_POST_INIT_PRIVATE_H
#include <linux/kconfig.h>
struct net_device;
struct notifier_block;
struct virtio_device;
#ifdef CONFIG_LSF_STREAM_FACTORY
#if !IS_BUILTIN(CONFIG_INET) || !IS_BUILTIN(CONFIG_IPV6) || \
    !IS_BUILTIN(CONFIG_VIRTIO) || !IS_BUILTIN(CONFIG_VIRTIO_NET)
#error "Unqualified private builtin NETDEV POST_INIT profile"
#endif
/* Output is borrowed only inside the original synchronous constructor. The
 * actual NETDEV record already holds its positive VIRTIO parent reference. */
int lsf_factory_stream_netdev_preinit(struct net_device *, struct virtio_device **);
int lsf_prepaid_stream_post_init_ipv4(const struct notifier_block *);
int lsf_prepaid_stream_post_init_fib4(const struct notifier_block *);
int lsf_prepaid_stream_post_init_rtnl(const struct notifier_block *);
int lsf_prepaid_stream_post_init_ipv6(const struct notifier_block *);
int lsf_prepaid_stream_post_init_virtnet_ops(const struct net_device *);
int lsf_prepaid_stream_post_init_virtio_quiet(struct virtio_device *);
#endif
#endif
