/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef LSF_STREAM_CLEANUP_CLONE_PRIVATE_H
#define LSF_STREAM_CLEANUP_CLONE_PRIVATE_H
#include <linux/types.h>
#include <net/lsf_stream_cleanup_audit.h>
int lsf_factory_cleanup_constructor_request(const void *, unsigned long,
    struct lsf_cleanup_task_source *);
int lsf_prepaid_cleanup_clone_args_current(struct lsf_cleanup_task_source,
    const struct kernel_clone_args *);
pid_t lsf_prepaid_cleanup_kernel_clone(struct lsf_cleanup_task_source, struct kernel_clone_args *);
pid_t lsf_prepaid_cleanup_kernel_thread(struct lsf_cleanup_task_source,
    int (*)(void *), void *, const char *, unsigned long);
#endif
