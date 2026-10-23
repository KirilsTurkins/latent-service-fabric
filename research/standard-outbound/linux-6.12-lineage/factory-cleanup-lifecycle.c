/* SPDX-License-Identifier: GPL-2.0-only */
/* Included after the original task/stack factory helpers. No global reaper,
 * task-pointer adoption, second ledger, allocation or callback under pool_lock. */
static int lsf_cleanup_lifecycle_identity_locked(struct lsf_cleanup_task_source source,
    const struct task_struct *actual)
{
    struct lsf_prepaid_view *request, *task;
    if (!factory.pages || !factory.device || !factory.opened ||
        READ_ONCE(factory.uncertain) || factory.device->cleanup_task_claimed != 1u ||
        factory.device->key.slot != source.owner.slot ||
        factory.device->key.generation != source.owner.generation ||
        factory.device->root.slot != source.root.slot ||
        factory.device->root.generation != source.root.generation ||
        factory.device->cleanup_request.slot != source.request.slot ||
        factory.device->cleanup_request.generation != source.request.generation ||
        factory.device->cleanup_task.slot != source.task.slot ||
        factory.device->cleanup_task.generation != source.task.generation ||
        !lsf_device_record(&factory.pool, source.owner, source.root, LSF_DEVICE_ROOT))
        return 0;
    request = lsf_device_record(&factory.pool, source.owner, source.request,
        LSF_DEVICE_CLEANUP_REQUEST);
    task = lsf_device_record(&factory.pool, source.owner, source.task,
        LSF_DEVICE_CLEANUP_TASK);
    return request && task && request->deferred == LSF_PREPAID_PRIVATE &&
        (task->deferred == LSF_PREPAID_PRIVATE || task->deferred == LSF_PREPAID_PUBLISHED ||
         task->deferred == LSF_PREPAID_QUEUED) &&
        request->cache_bucket == source.root.slot &&
        request->cache_anchor == source.root.generation &&
        task->cache_bucket == source.request.slot &&
        task->cache_anchor == source.request.generation &&
        actual == (const void *)((char *)page_address(factory.pages) + task->offset);
}

static void lsf_cleanup_lifecycle_poison_locked(void)
{
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
    if (factory.device)
        factory.device->cleanup_lifecycle = LSF_CLEANUP_HELD;
}

/* Resolve the exact born address BEFORE reading task fields or acquiring a task
 * reference. A bank-interior wrong address is uncertainty, never normal SLUB. */
int lsf_factory_cleanup_lifecycle_source(const struct task_struct *actual,
    struct lsf_cleanup_task_source *source, void **stack_address)
{
    struct lsf_prepaid_view *stack;
    unsigned long flags, address = (unsigned long)actual, base;
    int result = 0;
    if (!source || !stack_address)
        return -1;
    *source = (struct lsf_cleanup_task_source){0};
    *stack_address = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.pages)
        goto out;
    base = (unsigned long)page_address(factory.pages);
    if (address < base || address - base >= LSF_BACKING_BYTES)
        goto out;
    result = -1;
    if (!factory.device)
        goto poison;
    *source = (struct lsf_cleanup_task_source){factory.device->key,
        factory.device->root, factory.device->cleanup_request, factory.device->cleanup_task};
    if (!lsf_cleanup_lifecycle_identity_locked(*source, actual))
        goto poison;
    if (factory.device->cleanup_lifecycle != LSF_CLEANUP_STACK_RETURNED) {
        stack = lsf_device_record(&factory.pool, source->owner,
            factory.device->cleanup_stack, LSF_DEVICE_CLEANUP_STACK);
        if (!stack || stack->cache_bucket != source->task.slot ||
            stack->cache_anchor != source->task.generation)
            goto poison;
        *stack_address = (char *)page_address(factory.pages) + stack->offset;
    }
    result = 1;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_cleanup_task_initialized(struct lsf_cleanup_task_source source,
    struct task_struct *task)
{
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (current != kthreadd_task || !lsf_cleanup_lifecycle_identity_locked(source, task) ||
        factory.device->cleanup_lifecycle != LSF_CLEANUP_UNINITIALIZED ||
        refcount_read(&task->usage) != 1 || refcount_read(&task->stack_refcount) != 1)
        goto poison;
    factory.device->cleanup_lifecycle = LSF_CLEANUP_INITIALIZED;
    result = 1;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_cleanup_task_abort_begin(struct lsf_cleanup_task_source source,
    struct task_struct *task)
{
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (current != kthreadd_task || !lsf_cleanup_lifecycle_identity_locked(source, task) ||
        (factory.device->cleanup_lifecycle != LSF_CLEANUP_INITIALIZED &&
         factory.device->cleanup_lifecycle != LSF_CLEANUP_METADATA) ||
        refcount_read(&task->usage) != 1 || refcount_read(&task->stack_refcount) != 1 ||
        factory.pool.records[source.task.slot].deferred != LSF_PREPAID_PRIVATE)
        goto poison;
    factory.device->cleanup_lifecycle = LSF_CLEANUP_ABORTING;
    result = 1;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_cleanup_kthread_reserve(struct lsf_cleanup_task_source source,
    struct task_struct *task, unsigned long bytes, void **address)
{
    struct lsf_prepaid_ticket ticket;
    unsigned long flags, actual;
    lsf_u64 offset;
    int result = -EOPNOTSUPP;
    if (!address || lsf_prepaid_cleanup_kthread_geometry(&actual) || bytes != actual)
        return result;
    *address = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    if (current != kthreadd_task || !lsf_cleanup_lifecycle_identity_locked(source, task) ||
        factory.pool.stopped || factory.pool.contexts[source.owner.slot].closed ||
        factory.device->cleanup_lifecycle != LSF_CLEANUP_INITIALIZED ||
        factory.device->cleanup_kthread_attempted)
        goto out;
    factory.device->cleanup_kthread_attempted = 1;
    if (!lsf_device_allocate(&factory.pool, source.owner, bytes, LSF_DEVICE_CLEANUP_KTHREAD,
            source.task, &ticket, &offset))
        goto out;
    factory.device->cleanup_kthread = ticket;
    *address = (char *)page_address(factory.pages) + offset;
    memset(*address, 0, bytes);
    factory.device->cleanup_lifecycle = LSF_CLEANUP_METADATA;
    result = 0;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_cleanup_task_abort_ready(struct lsf_cleanup_task_source source,
    struct task_struct *task)
{
    struct lsf_prepaid_view *child;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (current != kthreadd_task || !lsf_cleanup_lifecycle_identity_locked(source, task) ||
        factory.device->cleanup_lifecycle != LSF_CLEANUP_ABORTING ||
        refcount_read(&task->usage) != 1 || refcount_read(&task->stack_refcount) != 1 ||
        task->worker_private || task->user_cpus_ptr)
        goto poison;
    child = lsf_device_record(&factory.pool, source.owner, factory.device->cleanup_kthread,
        LSF_DEVICE_CLEANUP_KTHREAD);
    if (child)
        goto poison;
    result = 1;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void *lsf_factory_cleanup_kthread_current(struct lsf_cleanup_task_source source,
    const struct task_struct *task)
{
    struct lsf_prepaid_view *record;
    unsigned long flags;
    void *result = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_cleanup_lifecycle_identity_locked(source, task))
        goto out;
    record = lsf_device_record(&factory.pool, source.owner, factory.device->cleanup_kthread,
        LSF_DEVICE_CLEANUP_KTHREAD);
    if (record && record->cache_bucket == source.task.slot &&
        record->cache_anchor == source.task.generation)
        result = (char *)page_address(factory.pages) + record->offset;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void *lsf_factory_cleanup_request_current(struct lsf_cleanup_task_source source,
    const struct task_struct *task)
{
    unsigned long flags;
    void *result = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    if (lsf_cleanup_lifecycle_identity_locked(source, task))
        result = (char *)page_address(factory.pages) +
            factory.pool.records[source.request.slot].offset;
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_cleanup_kthread_finish(struct lsf_cleanup_task_source source,
    struct task_struct *task, const void *address)
{
    struct lsf_prepaid_ticket ticket;
    struct lsf_prepaid_view *record;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_cleanup_lifecycle_identity_locked(source, task) ||
        (factory.device->cleanup_lifecycle != LSF_CLEANUP_ABORTING &&
         factory.device->cleanup_lifecycle != LSF_CLEANUP_STACK_RETURNED))
        goto poison;
    ticket = factory.device->cleanup_kthread;
    record = lsf_device_record(&factory.pool, source.owner, ticket, LSF_DEVICE_CLEANUP_KTHREAD);
    if (!record || record->cache_bucket != source.task.slot ||
        record->cache_anchor != source.task.generation ||
        address != (char *)page_address(factory.pages) + record->offset ||
        !lsf_device_finish(&factory.pool, source.owner, ticket, LSF_DEVICE_CLEANUP_KTHREAD))
        goto poison;
    result = 1;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_cleanup_task_publish(struct lsf_cleanup_task_source source,
    struct task_struct *task)
{
    struct lsf_prepaid_view *metadata;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    /* This transition is not called by the present partial constructor. */
    if (current != kthreadd_task || !lsf_cleanup_lifecycle_identity_locked(source, task) ||
        factory.device->cleanup_lifecycle != LSF_CLEANUP_METADATA ||
        READ_ONCE(task->__state) != TASK_NEW || refcount_read(&task->stack_refcount) != 1 ||
        factory.device->cleanup_retire_task)
        goto poison;
    metadata = lsf_device_record(&factory.pool, source.owner, factory.device->cleanup_kthread,
        LSF_DEVICE_CLEANUP_KTHREAD);
    if (!metadata || metadata->cache_bucket != source.task.slot ||
        metadata->cache_anchor != source.task.generation ||
        task->worker_private != (char *)page_address(factory.pages) + metadata->offset ||
        !tryget_task_struct(task))
        goto poison;
    /* Reserve the REAL final-stack continuation reference before task
     * visibility. A stack reader may outlive the scheduler/RCU usage ref. */
    factory.device->cleanup_retire_task = task;
    if (!lsf_device_publish(&factory.pool, source.owner, source.task, LSF_DEVICE_CLEANUP_TASK) ||
        !lsf_device_publish(&factory.pool, source.owner, factory.device->cleanup_stack,
            LSF_DEVICE_CLEANUP_STACK) ||
        !lsf_device_publish(&factory.pool, source.owner, factory.device->cleanup_kthread,
            LSF_DEVICE_CLEANUP_KTHREAD))
        goto poison;
    factory.device->cleanup_lifecycle = LSF_CLEANUP_PUBLISHED;
    result = 1;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_cleanup_stack_capture(struct lsf_cleanup_task_source source,
    struct task_struct *task, const void *address)
{
    struct lsf_prepaid_view *stack;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_cleanup_lifecycle_identity_locked(source, task) ||
        factory.device->cleanup_lifecycle != LSF_CLEANUP_PUBLISHED)
        goto poison;
    stack = lsf_device_record(&factory.pool, source.owner, factory.device->cleanup_stack,
        LSF_DEVICE_CLEANUP_STACK);
    if (!stack || stack->deferred != LSF_PREPAID_PUBLISHED ||
        stack->cache_bucket != source.task.slot || stack->cache_anchor != source.task.generation ||
        address != (char *)page_address(factory.pages) + stack->offset ||
        task == current || READ_ONCE(task->__state) != TASK_DEAD ||
        refcount_read(&task->stack_refcount) != 0 || refcount_read(&task->usage) < 1 ||
        factory.device->cleanup_retire_task != task)
        goto poison;
    /* Consume the original pre-publication continuation; never increment or
     * revive task usage here, and never put it under this lock. */
    factory.device->cleanup_lifecycle = LSF_CLEANUP_CAPTURED;
    result = 1;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_cleanup_stack_enqueue(struct lsf_cleanup_task_source source,
    struct task_struct *task)
{
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_cleanup_lifecycle_identity_locked(source, task) ||
        factory.device->cleanup_lifecycle != LSF_CLEANUP_CAPTURED ||
        factory.device->cleanup_retire_task != task || task->stack || task->stack_vm_area ||
        !lsf_device_queue(&factory.pool, source.owner, factory.device->cleanup_stack,
            LSF_DEVICE_CLEANUP_STACK) ||
        !lsf_device_queue(&factory.pool, source.owner, source.task, LSF_DEVICE_CLEANUP_TASK) ||
        !lsf_device_queue(&factory.pool, source.owner, factory.device->cleanup_kthread,
            LSF_DEVICE_CLEANUP_KTHREAD))
        goto poison;
    factory.device->cleanup_lifecycle = LSF_CLEANUP_PENDING;
    result = 1;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_cleanup_retire_pending(void)
{
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = factory.device && !READ_ONCE(factory.uncertain) &&
        factory.device->cleanup_lifecycle == LSF_CLEANUP_PENDING;
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

struct task_struct *lsf_factory_cleanup_retire_take(struct lsf_cleanup_task_source *source)
{
    struct task_struct *task = NULL;
    unsigned long flags;
    if (!source || current != kthreadd_task)
        return NULL;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.device || factory.device->cleanup_lifecycle != LSF_CLEANUP_PENDING)
        goto out;
    *source = (struct lsf_cleanup_task_source){factory.device->key,
        factory.device->root, factory.device->cleanup_request, factory.device->cleanup_task};
    task = factory.device->cleanup_retire_task;
    if (!lsf_cleanup_lifecycle_identity_locked(*source, task) || task->stack ||
        task->stack_vm_area || READ_ONCE(task->__state) != TASK_DEAD ||
        refcount_read(&task->stack_refcount) != 0) {
        lsf_cleanup_lifecycle_poison_locked();
        task = NULL;
        goto out;
    }
    factory.device->cleanup_lifecycle = LSF_CLEANUP_CLAIMED;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return task;
}

int lsf_factory_cleanup_stack_returned(struct lsf_cleanup_task_source source,
    struct task_struct *task, const void *address)
{
    struct lsf_prepaid_ticket ticket;
    struct lsf_prepaid_view *stack;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (current != kthreadd_task || !lsf_cleanup_lifecycle_identity_locked(source, task) ||
        factory.device->cleanup_lifecycle != LSF_CLEANUP_CLAIMED ||
        factory.device->cleanup_retire_task != task || task->stack || task->stack_vm_area)
        goto poison;
    ticket = factory.device->cleanup_stack;
    stack = lsf_device_record(&factory.pool, source.owner, ticket, LSF_DEVICE_CLEANUP_STACK);
    if (!stack || address != (char *)page_address(factory.pages) + stack->offset ||
        !lsf_device_finish(&factory.pool, source.owner, ticket, LSF_DEVICE_CLEANUP_STACK))
        goto poison;
    factory.device->cleanup_retire_task = NULL;
    factory.device->cleanup_lifecycle = LSF_CLEANUP_STACK_RETURNED;
    result = 1;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Original free_task has already run the real final task destructors. This is
 * the actual allocation-cache boundary, not stop completion or task unlink. */
int lsf_factory_cleanup_task_final(struct task_struct *task)
{
    struct lsf_cleanup_task_source source;
    unsigned long flags, base, address = (unsigned long)task;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.pages)
        goto out;
    base = (unsigned long)page_address(factory.pages);
    if (address < base || address - base >= LSF_BACKING_BYTES)
        goto out;
    result = 1; /* Known bank storage NEVER enters the ordinary SLUB free. */
    if (!factory.device)
        goto poison;
    source = (struct lsf_cleanup_task_source){factory.device->key,
        factory.device->root, factory.device->cleanup_request, factory.device->cleanup_task};
    if (!lsf_cleanup_lifecycle_identity_locked(source, task) ||
        factory.device->cleanup_lifecycle != LSF_CLEANUP_STACK_RETURNED ||
        task == current || refcount_read(&task->usage) != 0 ||
        refcount_read(&task->stack_refcount) != 0 || task->stack || task->stack_vm_area ||
        task->worker_private ||
        !lsf_device_finish(&factory.pool, source.owner, source.task, LSF_DEVICE_CLEANUP_TASK))
        goto poison;
    factory.device->cleanup_task_claimed = 2u;
    factory.device->cleanup_lifecycle = LSF_CLEANUP_TASK_RETURNED;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
