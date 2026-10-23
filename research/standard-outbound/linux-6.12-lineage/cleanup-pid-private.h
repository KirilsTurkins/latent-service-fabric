/* SPDX-License-Identifier: GPL-2.0-only */
/* Uninstalled selected init-PID constructor. No PID namespace/user ABI. */
#ifndef LSF_STREAM_CLEANUP_PID_PRIVATE_H
#define LSF_STREAM_CLEANUP_PID_PRIVATE_H
#include <linux/types.h>
#include <net/lsf_stream_cleanup_descendants.h>
struct pid;
struct pid_namespace;
struct idr;
struct radix_tree_root;
struct radix_tree_iter;

/* A shared init-PID IDR node is a NodeFixed root child, not a task/PID child.
 * Its actual final callback can run after that original task has returned. */
struct lsf_cleanup_pid_radix_source {
    struct lsf_prepaid_key owner;
    struct lsf_prepaid_ticket root, allocation;
    const void *address;
};
int lsf_prepaid_cleanup_pid_geometry(unsigned long *, unsigned long *);
int lsf_prepaid_cleanup_pid_radix_geometry(unsigned long *, unsigned long *);
int lsf_factory_cleanup_pid_origin(const struct pid *);
int lsf_factory_cleanup_pid_constructing(struct lsf_cleanup_task_source,
    struct task_struct *, const struct pid *);
void *lsf_factory_cleanup_pid_radix_new(struct lsf_cleanup_task_source,
    struct task_struct *, const struct pid *);
int lsf_factory_cleanup_pid_radix_publish(struct lsf_cleanup_task_source,
    struct task_struct *, const struct pid *, const void *);
int lsf_factory_cleanup_pid_radix_return_begin(const void *,
    struct lsf_cleanup_pid_radix_source *);
int lsf_factory_cleanup_pid_radix_return_finish(struct lsf_cleanup_pid_radix_source);

struct pid *lsf_prepaid_cleanup_alloc_pid(struct lsf_cleanup_task_source,
    struct task_struct *, struct pid_namespace *, pid_t *, size_t);
int lsf_prepaid_cleanup_pid_preload(struct lsf_cleanup_task_source,
    struct task_struct *, const struct pid *, struct idr *);
int lsf_prepaid_cleanup_pid_idr_alloc_cyclic(struct lsf_cleanup_task_source,
    struct task_struct *, const struct pid *, struct idr *, void *, int, int, gfp_t);
void __rcu **lsf_prepaid_cleanup_pid_idr_get_free(struct lsf_cleanup_task_source,
    struct task_struct *, const struct pid *, struct radix_tree_root *,
    struct radix_tree_iter *, gfp_t, unsigned long);
#endif
