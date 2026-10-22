/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual source checks, no cached NULL-context assertion or observer ledger. */
int lsf_factory_cleanup_constructor_current(struct lsf_cleanup_task_source source,
    struct task_struct *task)
{
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = current == kthreadd_task && !in_interrupt() &&
        lsf_cleanup_lifecycle_identity_locked(source, task) &&
        factory.device->cleanup_lifecycle == LSF_CLEANUP_METADATA &&
        factory.device->cleanup_final_phase == LSF_CLEANUP_FINAL_NONE &&
        !factory.pool.stopped && !factory.pool.contexts[source.owner.slot].closed &&
        refcount_read(&task->usage) == 1 && refcount_read(&task->stack_refcount) == 1 &&
        READ_ONCE(task->__state) == TASK_NEW;
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* The ordinary perf caller already pins its target. Classify immutable birth
 * before any task fields. Known bank addresses never fall through to PMU or
 * task-context allocation, even when closed, returned or uncertain. */
int lsf_factory_cleanup_perf_target(const struct task_struct *target)
{
    struct lsf_cleanup_task_source source;
    struct task_struct *task;
    unsigned long flags, base, at = (unsigned long)target;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.pages)
        goto out;
    base = (unsigned long)page_address(factory.pages);
    if (at < base || at - base >= LSF_BACKING_BYTES)
        goto out;
    result = -1;
    if (!lsf_cleanup_child_source_locked(&source, &task) || target != task)
        goto poison;
    result = 1;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
