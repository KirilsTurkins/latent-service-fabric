/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef _LSF_STREAM_NETDEV_DIRECTORY_PRIVATE_H
#define _LSF_STREAM_NETDEV_DIRECTORY_PRIVATE_H
#include <linux/types.h>
#include <linux/gfp_types.h>
#include <linux/uidgid.h>
struct kobject; struct device; struct kernfs_node;
struct radix_tree_root; struct radix_tree_iter; struct idr;
enum {
    LSF_STREAM_NETDEV_DIRECTORY_NODE = 0x172,
    LSF_STREAM_NETDEV_DIRECTORY_NAME,
    LSF_STREAM_NETDEV_DIRECTORY_IDR
};
struct lsf_stream_netdev_directory_source {
    const void *address;
    u64 generation, netdev_generation;
    unsigned int slot, netdev_slot, kind;
};
int lsf_factory_stream_netdev_directory_kobject(const struct kobject *, struct lsf_stream_netdev_directory_source *);
int lsf_factory_stream_netdev_directory_added(const struct device *);
int lsf_factory_stream_netdev_directory_node(const void *, struct lsf_stream_netdev_directory_source *);
int lsf_factory_stream_netdev_directory_current(struct lsf_stream_netdev_directory_source);
void *lsf_factory_stream_netdev_directory_allocate(struct lsf_stream_netdev_directory_source, unsigned long, unsigned int);
char *lsf_factory_stream_netdev_directory_name(struct lsf_stream_netdev_directory_source, const char *);
int lsf_factory_stream_netdev_directory_abort_node(struct lsf_stream_netdev_directory_source, struct kernfs_node *, const char *);
int lsf_factory_stream_netdev_directory_abort_name(struct lsf_stream_netdev_directory_source, const void *);
int lsf_factory_stream_netdev_directory_release_name(struct lsf_stream_netdev_directory_source, const void *);
int lsf_factory_stream_netdev_directory_return_begin(const void *, unsigned int, struct lsf_stream_netdev_directory_source *);
int lsf_factory_stream_netdev_directory_return_finish(struct lsf_stream_netdev_directory_source);
int lsf_factory_stream_netdev_directory_iattrs(const struct kernfs_node *, int);
void lsf_factory_stream_netdev_directory_retain_unknown(void);
/* These are real allocating-TU bridges, never caller-provided eligibility. */
int lsf_prepaid_stream_netdev_directory_type(const struct kobject *);
int lsf_prepaid_stream_netdev_directory_ready(const struct kobject *);
struct kernfs_node *lsf_prepaid_stream_netdev_directory_kernfs_create_dir_ns(
    struct lsf_stream_netdev_directory_source, struct kernfs_node *, const char *,
    umode_t, kuid_t, kgid_t, void *, const void *);
int lsf_prepaid_stream_netdev_directory_idr_alloc_cyclic(struct lsf_stream_netdev_directory_source,
    struct idr *, void *, int, int, gfp_t);
void __rcu **lsf_prepaid_stream_netdev_directory_idr_get_free(struct lsf_stream_netdev_directory_source,
    struct radix_tree_root *, struct radix_tree_iter *, gfp_t, unsigned long);
#endif
