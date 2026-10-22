/* SPDX-License-Identifier: GPL-2.0-only */
/* Included after the private request/worker definition in maintained kthread.c.
 * This is not a second executor or a successful partial fork implementation. */
int lsf_prepaid_cleanup_kthread_geometry(unsigned long *bytes)
{
    if (!bytes || !sizeof(struct kthread) || sizeof(struct kthread) > LSF_FACTORY_INFRA_BYTES)
        return -EOPNOTSUPP;
    *bytes = sizeof(struct kthread);
    return 0;
}

/* The initialization statements are the exact maintained set_kthread_struct
 * body after its sole allocator. Actual sizeof is charged before first write. */
static int lsf_cleanup_kthread_prepare(struct lsf_cleanup_task_source source,
    struct task_struct *p)
{
    struct kthread *kthread;
    void *address;
    int error;
    if (WARN_ON_ONCE(to_kthread(p)))
        return -EIO;
    error = lsf_factory_cleanup_kthread_reserve(source, p, sizeof(*kthread), &address);
    if (error)
        return error;
    kthread = address;
    init_completion(&kthread->exited);
    init_completion(&kthread->parked);
    p->vfork_done = &kthread->exited;
    p->worker_private = kthread;
    return 0;
}

int lsf_prepaid_cleanup_kthread_free(struct task_struct *task)
{
    struct lsf_cleanup_task_source source;
    struct lsf_cleanup_request *request;
    struct kthread *owned;
    void *stack;
    int result = lsf_factory_cleanup_lifecycle_source(task, &source, &stack);
    if (!result)
        return 0;
    if (result < 0)
        return 1;
    /* Exact task address was authenticated before dereferencing either task
     * fields or its child pointer. No borrowed worker_private origin proof. */
    owned = lsf_factory_cleanup_kthread_current(source, task);
    request = lsf_factory_cleanup_request_current(source, task);
    if (!owned || !request || task->worker_private != owned ||
        (owned->full_name && owned->full_name != request->name))
        goto poison;
#ifdef CONFIG_BLK_CGROUP
    /* Preserve the original warning, but do not return the view while an
     * actual CSS owner remains. Its original release path must run first. */
    if (WARN_ON_ONCE(owned->blkcg_css))
        goto poison;
#endif
    task->vfork_done = NULL;
    task->worker_private = NULL;
    /* The full name is embedded in the still-live original request. Neither
     * that bank string nor struct kthread may enter the ordinary kfree path. */
    if (!lsf_factory_cleanup_kthread_finish(source, task, owned))
        goto poison;
    return 1;
poison:
    lsf_factory_cleanup_stack_poison(source);
    return 1;
}

static struct task_struct *lsf_cleanup_prepare_unpublished(struct lsf_cleanup_request *owned)
{
    struct task_struct *task;
    int error;
    task = lsf_prepaid_cleanup_dup_initialized(owned->source, owned->create.node);
    if (IS_ERR(task))
        return task;
    error = lsf_cleanup_kthread_prepare(owned->source, task);
    /* PID/credentials/security/instrumentation and actual copy_process
     * publication remain unclosed. NEVER return this partial task as success,
     * call wake_up_new_task, or use the publication transition here. */
    if (!lsf_factory_cleanup_task_abort_begin(owned->source, task))
        return ERR_PTR(-EIO);
    if (!error && !lsf_prepaid_cleanup_kthread_free(task))
        return ERR_PTR(-EIO);
    if (lsf_prepaid_cleanup_abort_initialized(owned->source, task))
        return ERR_PTR(-EIO);
    return ERR_PTR(error ? error : -EOPNOTSUPP);
}

void lsf_prepaid_cleanup_retire_one(void)
{
    struct lsf_cleanup_task_source source;
    struct task_struct *task = lsf_factory_cleanup_retire_take(&source);
    if (!task)
        return;
    if (lsf_prepaid_cleanup_stack_retire(source, task))
        return; /* Keep actual held ref on uncertainty; no retry or refund. */
    /* This may execute the ORIGINAL final task destructors and private cache
     * guard. It is outside all creation/pool/VM locks. LAST task access. */
    put_task_struct(task);
}
