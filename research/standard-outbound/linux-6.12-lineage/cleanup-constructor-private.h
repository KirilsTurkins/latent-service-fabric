/* SPDX-License-Identifier: GPL-2.0-only */
/* Uninstalled full-constructor publication and separate usage-one abort. */
#ifndef LSF_STREAM_CLEANUP_CONSTRUCTOR_PRIVATE_H
#define LSF_STREAM_CLEANUP_CONSTRUCTOR_PRIVATE_H
#include <net/lsf_stream_cleanup_pid.h>
struct kernel_clone_args;
struct mempolicy;

int lsf_factory_cleanup_child_live(const void *, unsigned int);
int lsf_prepaid_cleanup_mpol_geometry(unsigned long *, unsigned long *);
struct mempolicy *lsf_prepaid_cleanup_mpol_dup(struct lsf_cleanup_task_source,
    struct task_struct *, struct mempolicy *);
int lsf_prepaid_cleanup_task_security_geometry(unsigned long *, unsigned long *);
int lsf_prepaid_cleanup_security_task_alloc(struct lsf_cleanup_task_source,
    struct task_struct *, unsigned long);
int lsf_factory_cleanup_abort_kthread_absent(struct lsf_cleanup_task_source,
    const struct task_struct *);

int lsf_factory_cleanup_constructor_vm_prepared(struct lsf_cleanup_task_source,
    struct task_struct *, const void *);
int lsf_prepaid_cleanup_constructor_prepare(struct lsf_cleanup_task_source,
    struct task_struct *);
int lsf_prepaid_cleanup_request_geometry(unsigned long *);
/* Only the real factory reserve/publish/abort paths call these while holding
 * their SAME pool lock, after original admission and exact born-address checks.
 * They perform no factory callback, allocation, task dereference or wait. */
int lsf_prepaid_cleanup_irq_birth_locked(struct lsf_cleanup_task_source,
    struct task_struct *, void *, unsigned long);
int lsf_prepaid_cleanup_irq_commit(struct lsf_cleanup_task_source, struct task_struct *);
int lsf_prepaid_cleanup_irq_abort_locked(struct lsf_cleanup_task_source, struct task_struct *);

int lsf_factory_cleanup_abort_stack_returned(struct lsf_cleanup_task_source,
    struct task_struct *);
int lsf_factory_cleanup_abort_destruct_begin(struct task_struct *);
int lsf_factory_cleanup_abort_cache_final(struct task_struct *);
int lsf_factory_cleanup_abort_pending(void);
void lsf_factory_cleanup_abort_drain(void);
int lsf_prepaid_cleanup_constructor_abort_stack(struct lsf_cleanup_task_source,
    struct task_struct *);
int lsf_prepaid_cleanup_kthread_prepare(struct lsf_cleanup_task_source,
    struct task_struct *);
struct task_struct *lsf_prepaid_cleanup_copy_process(struct lsf_cleanup_task_source,
    struct kernel_clone_args *, int);
#endif
