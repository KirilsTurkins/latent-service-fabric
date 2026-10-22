/* SPDX-License-Identifier: GPL-2.0-only */
/* Uninstalled task-creation prefix. No export, caller certificate or ready flag. */
#ifndef LSF_STREAM_CLEANUP_TASK_PRIVATE_H
#define LSF_STREAM_CLEANUP_TASK_PRIVATE_H
#include "prepaid.h"

struct task_struct;
struct lsf_cleanup_task_source {
    struct lsf_prepaid_key owner;
    struct lsf_prepaid_ticket root, request, task;
};

/* Only actual sizeof/alignment operands from the maintained private creator.
 * Reserve BOTH records before touching their storage. This does not create a
 * task, acquire an existing task/stack, or publish executor readiness. */
int lsf_factory_cleanup_task_reserve(unsigned long, unsigned long, unsigned long,
    struct lsf_cleanup_task_source *, void **);
struct task_struct *lsf_factory_cleanup_task_claim(struct lsf_cleanup_task_source);
int lsf_factory_cleanup_task_abort(struct lsf_cleanup_task_source,
    struct task_struct *);
int lsf_prepaid_cleanup_task_geometry(unsigned long *, unsigned long *);
struct task_struct *lsf_prepaid_cleanup_dup_task_struct(
    struct lsf_cleanup_task_source, int);
int lsf_prepaid_cleanup_worker_create(void);
#endif
