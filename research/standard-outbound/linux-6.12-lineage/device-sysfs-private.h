/* SPDX-License-Identifier: GPL-2.0-only */
/* Uninstalled, explicit constructor source. No public registrar or owner adoption. */
#ifndef LSF_STREAM_DEVICE_SYSFS_PRIVATE_H
#define LSF_STREAM_DEVICE_SYSFS_PRIVATE_H
#include <net/lsf_stream_device_registration.h>
#include <linux/uidgid.h>

struct kernfs_node;
struct kobject;
int lsf_prepaid_device_kobject_registration_ready(const struct kobject *);
int lsf_factory_device_sysfs_pair(const void *, const void *,
    struct lsf_device_registration_source *);
char *lsf_factory_device_sysfs_name(struct lsf_device_registration_source, const char *);
int lsf_factory_device_sysfs_release(struct lsf_device_registration_source,
    const void *, unsigned int);
int lsf_factory_device_sysfs_iattrs(const struct kernfs_node *, int);
void lsf_prepaid_device_kernfs_free(struct kernfs_node *);
struct kernfs_node *lsf_prepaid_device_kernfs_new_node(
    struct lsf_device_registration_source, struct kernfs_node *, const char *,
    umode_t, kuid_t, kgid_t, unsigned int);
struct kernfs_node *lsf_prepaid_device_kernfs_create_dir_ns(
    struct lsf_device_registration_source, struct kernfs_node *, const char *,
    umode_t, kuid_t, kgid_t, void *, const void *);
#ifdef CONFIG_SECURITY_SELINUX
bool lsf_prepaid_device_selinux_kernfs_hook(
    int (*)(struct kernfs_node *, struct kernfs_node *));
#endif
#endif
