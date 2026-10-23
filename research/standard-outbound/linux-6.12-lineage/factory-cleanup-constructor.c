/* SPDX-License-Identifier: GPL-2.0-only */
/* Included after the real lifecycle/descendant/PID helpers. These are real
 * original-record transitions, not a second reference or allocation ledger. */
int lsf_factory_cleanup_child_live(const void *address, unsigned int kind)
{
    struct lsf_prepaid_ticket ticket;
    unsigned long flags;
    int origin;
    spin_lock_irqsave(&pool_lock, flags);
    origin = lsf_cleanup_child_find_locked(address, kind, &ticket);
    if (origin < 0)
        lsf_cleanup_lifecycle_poison_locked();
    spin_unlock_irqrestore(&pool_lock, flags);
    return origin;
}

int lsf_factory_cleanup_abort_kthread_absent(struct lsf_cleanup_task_source source,
    const struct task_struct *task)
{
    unsigned long flags;
    int absent;
    spin_lock_irqsave(&pool_lock, flags);
    /* A real error before/during set_kthread_struct can have NO child. Do not
     * follow a borrowed pointer or treat an existing/returned birth as absent. */
    absent = lsf_cleanup_lifecycle_identity_locked(source, task) &&
        factory.device->cleanup_lifecycle == LSF_CLEANUP_ABORT_STACK_RETURNED &&
        factory.device->cleanup_final_phase == LSF_CLEANUP_FINAL_ABORT_DESTRUCTORS &&
        !factory.device->cleanup_kthread.slot && !factory.device->cleanup_kthread.generation &&
        refcount_read(&task->usage) == 1 && !task->worker_private;
    spin_unlock_irqrestore(&pool_lock, flags);
    return absent;
}

int lsf_factory_cleanup_constructor_vm_prepared(struct lsf_cleanup_task_source source,
    struct task_struct *task, const void *address)
{
    struct lsf_prepaid_view *stack;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (current != kthreadd_task || !lsf_cleanup_lifecycle_identity_locked(source, task) ||
        factory.device->cleanup_lifecycle != LSF_CLEANUP_METADATA ||
        factory.device->cleanup_vm_prepared || refcount_read(&task->usage) != 1 ||
        refcount_read(&task->stack_refcount) != 1 || READ_ONCE(task->__state) != TASK_NEW ||
        factory.pool.stopped || factory.pool.contexts[source.owner.slot].closed)
        goto poison;
    stack = lsf_device_record(&factory.pool, source.owner, factory.device->cleanup_stack,
        LSF_DEVICE_CLEANUP_STACK);
    if (!stack || stack->deferred != LSF_PREPAID_PRIVATE ||
        stack->cache_bucket != source.task.slot || stack->cache_anchor != source.task.generation ||
        address != (char *)page_address(factory.pages) + stack->offset)
        goto poison;
    /* The actual VM body validated its exact live/mapped view before this
     * private call. The still-unpublished task cannot mutate it concurrently. */
    factory.device->cleanup_vm_prepared = 1;
    result = 1;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_cleanup_abort_stack_returned(struct lsf_cleanup_task_source source,
    struct task_struct *task)
{
    struct lsf_prepaid_ticket ticket;
    struct lsf_prepaid_view *record;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (current != kthreadd_task || !lsf_cleanup_lifecycle_identity_locked(source, task) ||
        factory.device->cleanup_lifecycle != LSF_CLEANUP_ABORTING ||
        factory.device->cleanup_retire_task || refcount_read(&task->usage) != 1 ||
        refcount_read(&task->stack_refcount) || task->stack || task->stack_vm_area)
        goto poison;
    ticket = factory.device->cleanup_stack;
    if (!ticket.slot || ticket.slot >= LSF_ALLOCATION_SLOTS || !ticket.generation)
        goto poison;
    record = &factory.pool.records[ticket.slot];
    if (record->phase != LSF_PREPAID_RETURNED || record->kind != LSF_DEVICE_CLEANUP_STACK ||
        record->generation != ticket.generation || record->owner != source.owner.slot ||
        record->owner_generation != source.owner.generation ||
        record->cache_bucket != source.task.slot || record->cache_anchor != source.task.generation ||
        lsf_prepaid_cleanup_irq_abort_locked(source, task))
        goto poison;
    factory.device->cleanup_lifecycle = LSF_CLEANUP_ABORT_STACK_RETURNED;
    result = 1;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Classify the actual born task before accessing mutable task fields. A
 * published usage-zero task continues to the separately latched normal tail. */
int lsf_factory_cleanup_abort_destruct_begin(struct task_struct *task)
{
    struct lsf_cleanup_task_source source;
    struct task_struct *actual;
    unsigned long flags, base, at = (unsigned long)task;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.pages)
        goto out;
    base = (unsigned long)page_address(factory.pages);
    if (at < base || at - base >= LSF_BACKING_BYTES)
        goto out;
    result = -1;
    if (!lsf_cleanup_child_source_locked(&source, &actual) || actual != task)
        goto poison;
    if (factory.device->cleanup_lifecycle == LSF_CLEANUP_STACK_RETURNED &&
        factory.device->cleanup_final_phase == LSF_CLEANUP_FINAL_DESTRUCTORS) {
        result = 0;
        goto out;
    }
    if (factory.device->cleanup_lifecycle != LSF_CLEANUP_ABORT_STACK_RETURNED ||
        factory.device->cleanup_final_phase != LSF_CLEANUP_FINAL_NONE ||
        refcount_read(&task->usage) != 1 || refcount_read(&task->stack_refcount) ||
        task == current || task->stack || task->stack_vm_area || factory.device->cleanup_retire_task)
        goto poison;
    factory.device->cleanup_final_phase = LSF_CLEANUP_FINAL_ABORT_DESTRUCTORS;
    result = 1;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_cleanup_abort_cache_final(struct task_struct *task)
{
    struct lsf_cleanup_task_source source;
    struct task_struct *actual;
    unsigned long flags, base, at = (unsigned long)task;
    int result = 0, notify = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.pages)
        goto out;
    base = (unsigned long)page_address(factory.pages);
    if (at < base || at - base >= LSF_BACKING_BYTES)
        goto out;
    result = 1;
    if (!lsf_cleanup_child_source_locked(&source, &actual) || actual != task)
        goto poison;
    if (factory.device->cleanup_lifecycle == LSF_CLEANUP_STACK_RETURNED &&
        factory.device->cleanup_final_phase == LSF_CLEANUP_FINAL_DESTRUCTORS) {
        result = 0;
        goto out;
    }
    if (factory.device->cleanup_lifecycle != LSF_CLEANUP_ABORT_STACK_RETURNED ||
        factory.device->cleanup_final_phase != LSF_CLEANUP_FINAL_ABORT_DESTRUCTORS ||
        refcount_read(&task->usage) != 1 || refcount_read(&task->stack_refcount) ||
        task == current || task->stack || task->stack_vm_area || task->worker_private ||
        factory.device->cleanup_retire_task)
        goto poison;
    factory.device->cleanup_final_phase = LSF_CLEANUP_FINAL_ABORT_WAITING;
    notify = !lsf_cleanup_final_children_locked();
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    if (notify)
        wake_up_process(kthreadd_task);
    return result;
}

int lsf_factory_cleanup_abort_pending(void)
{
    unsigned long flags;
    int pending;
    spin_lock_irqsave(&pool_lock, flags);
    pending = factory.device && !READ_ONCE(factory.uncertain) &&
        factory.device->cleanup_final_phase == LSF_CLEANUP_FINAL_ABORT_WAITING;
    spin_unlock_irqrestore(&pool_lock, flags);
    return pending;
}

void lsf_factory_cleanup_abort_drain(void)
{
    struct lsf_cleanup_task_source source;
    struct task_struct *task;
    unsigned long flags;
    if (current != kthreadd_task || in_interrupt() || irqs_disabled())
        return;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.device || READ_ONCE(factory.uncertain) ||
        factory.device->cleanup_final_phase != LSF_CLEANUP_FINAL_ABORT_WAITING)
        goto out;
    if (!lsf_cleanup_child_source_locked(&source, &task) ||
        factory.device->cleanup_lifecycle != LSF_CLEANUP_ABORT_STACK_RETURNED ||
        refcount_read(&task->usage) != 1 || refcount_read(&task->stack_refcount) ||
        task->stack || task->stack_vm_area || task->worker_private || factory.device->cleanup_retire_task)
        goto poison;
    if (lsf_cleanup_final_children_locked())
        goto out;
    if (!lsf_device_finish(&factory.pool, source.owner, source.task, LSF_DEVICE_CLEANUP_TASK))
        goto poison;
    factory.device->cleanup_final_phase = LSF_CLEANUP_FINAL_RETURNED;
    factory.device->cleanup_task_claimed = 2u;
    factory.device->cleanup_lifecycle = LSF_CLEANUP_TASK_RETURNED;
    goto out; /* No task refcount mutation or replay of real destructors. */
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
}
