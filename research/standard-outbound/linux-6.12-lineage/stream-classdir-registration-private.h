/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef _LSF_STREAM_CLASSDIR_REGISTRATION_PRIVATE_H
#define _LSF_STREAM_CLASSDIR_REGISTRATION_PRIVATE_H
#include <linux/types.h>
#include <linux/gfp_types.h>
#include <linux/uidgid.h>
struct kobject; struct kernfs_node;
struct radix_tree_root; struct radix_tree_iter; struct idr;
#define LSF_STREAM_CLASSDIR_TAIL_DONE 32u
/* Disjoint actual births, never caller-provided scope or allocation adoption. */
enum {
    LSF_STREAM_CLASSDIR_NODE = 0x16f,
    LSF_STREAM_CLASSDIR_NAME,
    LSF_STREAM_CLASSDIR_IDR
};
struct lsf_stream_classdir_registration_source {
    const void *address;
    u64 generation, class_generation;
    unsigned int slot, class_slot, kind;
};
int lsf_factory_stream_classdir_kobject(const struct kobject *,
    struct lsf_stream_classdir_registration_source *);
int lsf_factory_stream_classdir_node(const void *,
    struct lsf_stream_classdir_registration_source *);
int lsf_factory_stream_classdir_current(struct lsf_stream_classdir_registration_source);
void *lsf_factory_stream_classdir_allocate(struct lsf_stream_classdir_registration_source,
    unsigned long, unsigned int);
char *lsf_factory_stream_classdir_name(struct lsf_stream_classdir_registration_source, const char *);
int lsf_factory_stream_classdir_abort_node(struct lsf_stream_classdir_registration_source,
    struct kernfs_node *, const char *);
int lsf_factory_stream_classdir_abort_name(struct lsf_stream_classdir_registration_source, const void *);
int lsf_factory_stream_classdir_release_name(struct lsf_stream_classdir_registration_source, const void *);
int lsf_factory_stream_classdir_return_begin(const void *, unsigned int,
    struct lsf_stream_classdir_registration_source *);
int lsf_factory_stream_classdir_return_finish(struct lsf_stream_classdir_registration_source);
int lsf_factory_stream_classdir_iattrs(const struct kernfs_node *, int);
void lsf_factory_stream_classdir_retain_unknown(void);
int lsf_prepaid_stream_classdir_registration_ready(const struct kobject *);
struct kernfs_node *lsf_prepaid_stream_classdir_kernfs_create_dir_ns(
    struct lsf_stream_classdir_registration_source, struct kernfs_node *,
    const char *, umode_t, kuid_t, kgid_t, void *, const void *);
int lsf_prepaid_stream_classdir_idr_alloc_cyclic(struct lsf_stream_classdir_registration_source,
    struct idr *, void *, int, int, gfp_t);
void __rcu **lsf_prepaid_stream_classdir_idr_get_free(struct lsf_stream_classdir_registration_source,
    struct radix_tree_root *, struct radix_tree_iter *, gfp_t, unsigned long);
#endif
