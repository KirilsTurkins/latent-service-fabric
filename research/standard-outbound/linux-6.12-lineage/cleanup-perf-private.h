/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef LSF_STREAM_CLEANUP_PERF_PRIVATE_H
#define LSF_STREAM_CLEANUP_PERF_PRIVATE_H
#include <linux/types.h>
#include <net/lsf_stream_cleanup_constructor.h>
int lsf_factory_cleanup_constructor_current(struct lsf_cleanup_task_source, struct task_struct *);
int lsf_factory_cleanup_perf_target(const struct task_struct *);
int lsf_prepaid_cleanup_perf_event_init_task(struct lsf_cleanup_task_source,
    struct task_struct *, u64);
#endif
