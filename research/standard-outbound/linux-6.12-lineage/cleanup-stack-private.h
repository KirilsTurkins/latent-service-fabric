/* SPDX-License-Identifier: GPL-2.0-only */
/* Private, unpublished-task stack only. No userspace address/certificate API. */
#ifndef LSF_STREAM_CLEANUP_STACK_PRIVATE_H
#define LSF_STREAM_CLEANUP_STACK_PRIVATE_H
#include <net/lsf_stream_cleanup_task.h>

int lsf_factory_cleanup_stack_reserve(struct lsf_cleanup_task_source,
    struct task_struct *, unsigned long, void **);
int lsf_prepaid_cleanup_stack_geometry(unsigned long *);
int lsf_factory_cleanup_stack_finish(struct lsf_cleanup_task_source, const void *);
void *lsf_factory_cleanup_stack_current(struct lsf_cleanup_task_source,
    const struct task_struct *);
void lsf_factory_cleanup_stack_poison(struct lsf_cleanup_task_source);
int lsf_prepaid_cleanup_stack_create(struct lsf_cleanup_task_source, struct task_struct *);
int lsf_prepaid_cleanup_stack_abort_unpublished(struct lsf_cleanup_task_source,
    struct task_struct *);
/* Called BEFORE ordinary remove_vm_area can unlink a private mapping. */
int lsf_prepaid_cleanup_stack_foreign_unmap(const void *);
#endif
