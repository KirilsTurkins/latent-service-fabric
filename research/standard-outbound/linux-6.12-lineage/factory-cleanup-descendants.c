/* SPDX-License-Identifier: GPL-2.0-only */
/* Same original pool, native backing and child records. No new allocator,
 * returned-address adoption, task-ref revival or destructor retry. */
static unsigned int lsf_cleanup_child_device_kind(unsigned int kind)
{
    switch (kind) {
    case LSF_CLEANUP_CRED: return LSF_DEVICE_CLEANUP_CRED;
    case LSF_CLEANUP_CRED_SECURITY: return LSF_DEVICE_CLEANUP_CRED_SECURITY;
    case LSF_CLEANUP_SIGHAND: return LSF_DEVICE_CLEANUP_SIGHAND;
    case LSF_CLEANUP_SIGNAL: return LSF_DEVICE_CLEANUP_SIGNAL;
    case LSF_CLEANUP_DELAY: return LSF_DEVICE_CLEANUP_DELAY;
    default: return 0;
    }
}

static int lsf_cleanup_child_source_locked(struct lsf_cleanup_task_source *source,
    struct task_struct **task)
{
    struct lsf_prepaid_view *record;
    if (!factory.device)
        return 0;
    *source = (struct lsf_cleanup_task_source){factory.device->key,
        factory.device->root, factory.device->cleanup_request, factory.device->cleanup_task};
    if (!source->task.slot || source->task.slot >= LSF_ALLOCATION_SLOTS)
        return 0;
    record = lsf_device_record(&factory.pool, source->owner, source->task,
        LSF_DEVICE_CLEANUP_TASK);
    if (!record)
        return 0;
    *task = (void *)((char *)page_address(factory.pages) + record->offset);
    return lsf_cleanup_lifecycle_identity_locked(*source, *task);
}

/* Only exact immutable born addresses are followed. The record's own full
 * generation and parent chain resolve the original task, not a supplied tag. */
static int lsf_cleanup_child_find_locked(const void *address, unsigned int kind,
    struct lsf_prepaid_ticket *ticket)
{
    struct lsf_cleanup_task_source source;
    struct task_struct *task;
    struct lsf_prepaid_view *record, *parent;
    unsigned long base, at = (unsigned long)address;
    unsigned int i, device_kind = lsf_cleanup_child_device_kind(kind);
    if (!factory.pages)
        return 0;
    base = (unsigned long)page_address(factory.pages);
    if (at < base || at - base >= LSF_BACKING_BYTES)
        return 0;
    if (!device_kind || !lsf_cleanup_child_source_locked(&source, &task))
        return -1;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->offset != at - base || record->kind != device_kind)
            continue;
        *ticket = (struct lsf_prepaid_ticket){i, record->generation};
        if (!lsf_device_record(&factory.pool, source.owner, *ticket, device_kind))
            return -1;
        if (kind != LSF_CLEANUP_CRED_SECURITY)
            return record->cache_bucket == source.task.slot &&
                record->cache_anchor == source.task.generation ? 1 : -1;
        if (!record->cache_bucket || record->cache_bucket >= LSF_ALLOCATION_SLOTS)
            return -1;
        parent = lsf_device_record(&factory.pool, source.owner,
            (struct lsf_prepaid_ticket){record->cache_bucket, record->cache_anchor},
            LSF_DEVICE_CLEANUP_CRED);
        return parent && parent->cache_bucket == source.task.slot &&
            parent->cache_anchor == source.task.generation ? 1 : -1;
    }
    return -1;
}

void *lsf_factory_cleanup_child_new(struct lsf_cleanup_task_source source,
    struct task_struct *task, unsigned int kind, const void *parent_address)
{
    struct lsf_prepaid_ticket parent, ticket;
    struct lsf_prepaid_view *record;
    unsigned long flags, bytes, alignment;
    unsigned int device_kind = lsf_cleanup_child_device_kind(kind);
    lsf_u64 offset;
    void *result = NULL;
    if (!device_kind || kind >= LSF_CLEANUP_CHILD_KINDS ||
        lsf_prepaid_cleanup_child_geometry(kind, &bytes, &alignment) ||
        !bytes || bytes > LSF_FACTORY_INFRA_BYTES || !alignment || alignment > 64u ||
        (alignment & (alignment - 1u)) || current != kthreadd_task || in_interrupt())
        return NULL;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_cleanup_lifecycle_identity_locked(source, task) || factory.pool.stopped ||
        factory.pool.contexts[source.owner.slot].closed ||
        (factory.device->cleanup_lifecycle != LSF_CLEANUP_INITIALIZED &&
         factory.device->cleanup_lifecycle != LSF_CLEANUP_METADATA) ||
        factory.device->cleanup_final_phase != LSF_CLEANUP_FINAL_NONE ||
        (factory.device->cleanup_child_attempted & (1u << kind)))
        goto out;
    parent = source.task;
    if (kind == LSF_CLEANUP_CRED_SECURITY) {
        if (lsf_cleanup_child_find_locked(parent_address, LSF_CLEANUP_CRED, &parent) != 1)
            goto poison;
    } else if (parent_address != task) {
        goto poison;
    }
    /* Finite one-shot constructor sites. No retry or reusable cursor. */
    factory.device->cleanup_child_attempted |= 1u << kind;
    if (!lsf_device_allocate(&factory.pool, source.owner, bytes, device_kind,
            parent, &ticket, &offset))
        goto out;
    record = lsf_device_record(&factory.pool, source.owner, ticket, device_kind);
    if (!record || record->bytes < bytes ||
        ((unsigned long)page_address(factory.pages) + offset) & (alignment - 1u))
        goto poison;
    result = (char *)page_address(factory.pages) + offset;
    memset(result, 0, bytes); /* Exact original charge precedes first write. */
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* The actual callback retains this SAME record until its physical final site.
 * Late legitimate drain after close is permitted; no new allocation occurs. */
int lsf_factory_cleanup_child_defer(const void *address, unsigned int kind)
{
    struct lsf_prepaid_ticket ticket;
    struct lsf_prepaid_context *context;
    struct lsf_prepaid_view *record;
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_cleanup_child_find_locked(address, kind, &ticket);
    if (result != 1)
        goto out;
    context = lsf_device_context(&factory.pool, factory.device->key);
    record = &factory.pool.records[ticket.slot];
    if (!context || record->deferred != LSF_PREPAID_PRIVATE ||
        context->continuations == LSF_ALLOCATION_SLOTS)
        goto poison;
    record->deferred = LSF_PREPAID_QUEUED;
    context->continuations++;
    goto out;
poison:
    result = -1;
out:
    if (result < 0)
        lsf_cleanup_lifecycle_poison_locked();
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

static int lsf_cleanup_final_children_locked(void)
{
    unsigned int i;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        struct lsf_prepaid_view *record = &factory.pool.records[i];
        if (record->phase == LSF_PREPAID_LIVE &&
            record->owner == factory.device->key.slot &&
            record->owner_generation == factory.device->key.generation &&
            record->cache_bucket == factory.device->cleanup_task.slot &&
            record->cache_anchor == factory.device->cleanup_task.generation)
            return 1;
    }
    return 0;
}

int lsf_factory_cleanup_child_finish(const void *address, unsigned int kind)
{
    struct lsf_prepaid_ticket ticket;
    unsigned long flags;
    int result, notify = 0;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_cleanup_child_find_locked(address, kind, &ticket);
    if (result != 1)
        goto out;
    if (!lsf_device_finish(&factory.pool, factory.device->key, ticket,
            lsf_cleanup_child_device_kind(kind))) {
        result = -1;
        goto out;
    }
    notify = factory.device->cleanup_final_phase == LSF_CLEANUP_FINAL_WAITING &&
        !lsf_cleanup_final_children_locked();
out:
    if (result < 0)
        lsf_cleanup_lifecycle_poison_locked();
    spin_unlock_irqrestore(&pool_lock, flags);
    if (notify)
        wake_up_process(kthreadd_task); /* No lock and no child pointer use. */
    return result;
}

int lsf_factory_cleanup_task_destruct_begin(struct task_struct *task)
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
    if (!lsf_cleanup_child_source_locked(&source, &actual) || actual != task ||
        factory.device->cleanup_lifecycle != LSF_CLEANUP_STACK_RETURNED ||
        factory.device->cleanup_final_phase != LSF_CLEANUP_FINAL_NONE ||
        task == current || refcount_read(&task->usage) ||
        refcount_read(&task->stack_refcount) || task->stack || task->stack_vm_area)
        goto poison;
    factory.device->cleanup_final_phase = LSF_CLEANUP_FINAL_DESTRUCTORS;
    result = 1;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Actual free_task/cache boundary AFTER the original complete destructors.
 * Retain usage-zero physical storage while real credential/sighand RCU children
 * drain. Never call free_task or __put_task_struct a second time. */
int lsf_factory_cleanup_task_final(struct task_struct *task)
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
    if (!lsf_cleanup_child_source_locked(&source, &actual) || actual != task ||
        factory.device->cleanup_lifecycle != LSF_CLEANUP_STACK_RETURNED ||
        factory.device->cleanup_final_phase != LSF_CLEANUP_FINAL_DESTRUCTORS ||
        task == current || refcount_read(&task->usage) ||
        refcount_read(&task->stack_refcount) || task->stack || task->stack_vm_area ||
        task->worker_private)
        goto poison;
    factory.device->cleanup_final_phase = LSF_CLEANUP_FINAL_WAITING;
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

int lsf_factory_cleanup_final_pending(void)
{
    unsigned long flags;
    int pending;
    spin_lock_irqsave(&pool_lock, flags);
    pending = factory.device && !READ_ONCE(factory.uncertain) &&
        factory.device->cleanup_final_phase == LSF_CLEANUP_FINAL_WAITING &&
        !lsf_cleanup_final_children_locked();
    spin_unlock_irqrestore(&pool_lock, flags);
    return pending;
}

void lsf_factory_cleanup_final_drain(void)
{
    struct lsf_cleanup_task_source source;
    struct task_struct *task;
    unsigned long flags;
    if (current != kthreadd_task || in_interrupt() || irqs_disabled())
        return;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.device || READ_ONCE(factory.uncertain) ||
        factory.device->cleanup_final_phase != LSF_CLEANUP_FINAL_WAITING)
        goto out;
    if (!lsf_cleanup_child_source_locked(&source, &task) ||
        factory.device->cleanup_lifecycle != LSF_CLEANUP_STACK_RETURNED ||
        refcount_read(&task->usage) || refcount_read(&task->stack_refcount) ||
        task->stack || task->stack_vm_area || task->worker_private)
        goto poison;
    if (lsf_cleanup_final_children_locked())
        goto out;
    if (!lsf_device_finish(&factory.pool, source.owner, source.task, LSF_DEVICE_CLEANUP_TASK))
        goto poison;
    factory.device->cleanup_final_phase = LSF_CLEANUP_FINAL_RETURNED;
    factory.device->cleanup_task_claimed = 2u;
    factory.device->cleanup_lifecycle = LSF_CLEANUP_TASK_RETURNED;
    goto out; /* LAST task access preceded physical original-record return. */
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
}
