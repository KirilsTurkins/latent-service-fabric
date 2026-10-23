/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef LSF_STREAM_CLEANUP_ASSOCIATION_PRIVATE_H
#define LSF_STREAM_CLEANUP_ASSOCIATION_PRIVATE_H
#include <net/lsf_stream_cleanup_cgroup.h>
struct kthread_worker;
int lsf_prepaid_cleanup_worker_geometry(unsigned long *, unsigned long *, unsigned long *);
int lsf_factory_cleanup_worker_associate(struct lsf_cleanup_task_source, void *,
    struct kthread_worker *, struct task_struct *);
int lsf_prepaid_cleanup_worker_create_full(void);
#endif
