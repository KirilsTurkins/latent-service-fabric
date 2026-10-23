/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef LSF_STREAM_CLEANUP_CGROUP_PRIVATE_H
#define LSF_STREAM_CLEANUP_CGROUP_PRIVATE_H
#include <net/lsf_stream_cleanup_io.h>
int lsf_prepaid_cleanup_cgroup_can_fork(struct lsf_cleanup_task_source,
    struct task_struct *, struct kernel_clone_args *);
#endif
