/* SPDX-License-Identifier: GPL-2.0-only */
/* Uninstalled, kernel-private task lifecycle. No registrar or userspace ABI. */
#ifndef LSF_STREAM_CLEANUP_LIFECYCLE_PRIVATE_H
#define LSF_STREAM_CLEANUP_LIFECYCLE_PRIVATE_H
#include <net/lsf_stream_cleanup_stack.h>

enum lsf_cleanup_lifecycle {
    LSF_CLEANUP_UNINITIALIZED,
    LSF_CLEANUP_INITIALIZED,
    LSF_CLEANUP_METADATA,
    LSF_CLEANUP_PUBLISHED,
    LSF_CLEANUP_CAPTURED,
    LSF_CLEANUP_PENDING,
    LSF_CLEANUP_CLAIMED,
    LSF_CLEANUP_STACK_RETURNED,
    LSF_CLEANUP_TASK_RETURNED,
    LSF_CLEANUP_ABORTING,
    LSF_CLEANUP_HELD
};

int lsf_factory_cleanup_lifecycle_source(const struct task_struct *,
    struct lsf_cleanup_task_source *, void **);
int lsf_factory_cleanup_task_initialized(struct lsf_cleanup_task_source,
    struct task_struct *);
int lsf_factory_cleanup_task_abort_begin(struct lsf_cleanup_task_source,
    struct task_struct *);
int lsf_factory_cleanup_task_abort_ready(struct lsf_cleanup_task_source,
    struct task_struct *);
int lsf_factory_cleanup_kthread_reserve(struct lsf_cleanup_task_source,
    struct task_struct *, unsigned long, void **);
void *lsf_factory_cleanup_kthread_current(struct lsf_cleanup_task_source,
    const struct task_struct *);
void *lsf_factory_cleanup_request_current(struct lsf_cleanup_task_source,
    const struct task_struct *);
int lsf_factory_cleanup_kthread_finish(struct lsf_cleanup_task_source,
    struct task_struct *, const void *);
/* Called only by the VM-validated private publication wrapper. The future
 * complete copy_process chain must call that wrapper before task visibility;
 * the present partial constructor NEVER calls either transition. */
int lsf_factory_cleanup_task_publish(struct lsf_cleanup_task_source,
    struct task_struct *);
int lsf_factory_cleanup_stack_capture(struct lsf_cleanup_task_source,
    struct task_struct *, const void *);
int lsf_factory_cleanup_stack_enqueue(struct lsf_cleanup_task_source,
    struct task_struct *);
int lsf_factory_cleanup_retire_pending(void);
struct task_struct *lsf_factory_cleanup_retire_take(struct lsf_cleanup_task_source *);
int lsf_factory_cleanup_stack_returned(struct lsf_cleanup_task_source,
    struct task_struct *, const void *);
int lsf_factory_cleanup_task_final(struct task_struct *);

int lsf_prepaid_cleanup_kthread_geometry(unsigned long *);
struct task_struct *lsf_prepaid_cleanup_dup_initialized(
    struct lsf_cleanup_task_source, int);
int lsf_prepaid_cleanup_abort_initialized(struct lsf_cleanup_task_source,
    struct task_struct *);
/* Called only at the original final stack-ref boundary. Nonzero means owned
 * or uncertain: the ordinary VMAP cache/free path MUST NOT follow. */
int lsf_prepaid_cleanup_stack_release(struct task_struct *);
int lsf_prepaid_cleanup_stack_publish(struct lsf_cleanup_task_source,
    struct task_struct *);
int lsf_prepaid_cleanup_stack_retire(struct lsf_cleanup_task_source,
    struct task_struct *);
int lsf_prepaid_cleanup_kthread_free(struct task_struct *);
void lsf_prepaid_cleanup_retire_one(void);
#endif
