/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef LSF_STREAM_DEVICE_DELIVERY_PRIVATE_H
#define LSF_STREAM_DEVICE_DELIVERY_PRIVATE_H
#include <linux/netlink.h>
#include <net/netlink.h>
#include <net/lsf_stream_device_notification.h>
#include <net/lsf_stream_sidcache_private.h>
struct cred;
struct file;
struct user_namespace;
struct lsf_factory_blob;
struct socket;
struct msghdr;
int lsf_prepaid_device_broadcast_filtered(struct sock *, struct sk_buff *, u32,
    u32, gfp_t, netlink_filter_fn, void *);
int lsf_prepaid_device_recvmsg_tail(struct socket *, struct msghdr *, size_t,
    int, struct sk_buff *);
int lsf_prepaid_device_security_secctx(struct lsf_device_registration_source,
    u32, char **, u32 *);
int lsf_prepaid_device_security_release_secctx(struct lsf_device_registration_source,
    char *, u32);
int lsf_prepaid_device_file_ns_capable(struct lsf_device_registration_source,
    const struct file *, struct user_namespace *, int);
int lsf_prepaid_device_security_capable(struct lsf_device_registration_source,
    const struct cred *, struct user_namespace *, int, unsigned int);
#ifdef CONFIG_SECURITY_SELINUX
bool lsf_prepaid_device_selinux_capable_hook(
    int (*)(const struct cred *, struct user_namespace *, int, unsigned int));
int lsf_prepaid_device_selinux_capable(const struct lsf_factory_blob *,
    const struct cred *, struct user_namespace *, int, unsigned int);
bool lsf_prepaid_device_selinux_secctx_hook(int (*)(u32, char **, u32 *));
bool lsf_prepaid_device_selinux_release_secctx_hook(void (*)(char *, u32));
int lsf_prepaid_device_selinux_secctx(const struct lsf_factory_blob *, u32, char **, u32 *);
int lsf_prepaid_device_selinux_release_secctx(const struct lsf_factory_blob *, char *, u32);
#endif
#endif
