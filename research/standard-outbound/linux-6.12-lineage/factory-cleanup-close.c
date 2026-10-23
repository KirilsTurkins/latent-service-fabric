/* SPDX-License-Identifier: GPL-2.0-only */
/* Same charged Root metadata, not a second lifetime ledger. Task storage may
 * already be returned: these checks inspect scalar birth records ONLY. */
static void lsf_cleanup_admission_close(void)
{
    unsigned int i;
    unsigned long flags;
    spin_lock_irqsave(&pool_lock, flags);
    factory.pool.stopped = 1;
    /* Normal close is not evidence of corruption. Actual poison is sticky. */
    for (i = 0; i < LSF_FACTORY_CONTEXTS; ++i)
        factory.pool.contexts[i].closed = 1;
    if (factory.device)
        (void)lsf_device_close(&factory.pool, factory.device->key);
    spin_unlock_irqrestore(&pool_lock, flags);
}

static int lsf_cleanup_request_identity_locked(struct lsf_cleanup_task_source source)
{
    struct lsf_prepaid_view *request;
    if (!factory.pages || !factory.device || !factory.opened ||
        READ_ONCE(factory.uncertain) || factory.pool.poisoned ||
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
    return request && request->deferred == LSF_PREPAID_PRIVATE &&
        request->cache_bucket == source.root.slot &&
        request->cache_anchor == source.root.generation;
}

int lsf_factory_cleanup_request_put(struct lsf_cleanup_task_source source, unsigned int role)
{
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if ((role != LSF_CLEANUP_REQUEST_CREATOR && role != LSF_CLEANUP_REQUEST_OPENER) ||
        !lsf_cleanup_request_identity_locked(source) ||
        !(factory.device->cleanup_request_users & role) ||
        (role == LSF_CLEANUP_REQUEST_CREATOR && current != kthreadd_task) ||
        (role == LSF_CLEANUP_REQUEST_OPENER &&
         (current->mm != factory.mm || task_tgid(current) != factory.tgid ||
          current_cred() != factory.cred || !current->nsproxy ||
          current->nsproxy->net_ns != factory.net)))
        goto poison;
    /* Caller has completed its LAST request access. Borrowed completion is
     * separate: the actual complete(done) must still run outside this lock. */
    factory.device->cleanup_request_users &= ~role;
    result = 1;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    if (result)
        wake_up_process(kthreadd_task);
    return result;
}

int lsf_factory_cleanup_creator_error(struct lsf_cleanup_task_source source)
{
    struct lsf_prepaid_view *task;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (current != kthreadd_task || !lsf_cleanup_request_identity_locked(source))
        goto poison;
    if (!factory.device->cleanup_task_claimed) {
        /* No actual Task initializer, ref or stack ever existed. Return only
         * this unused original view; NEVER inspect zeroed Task fields or run
         * usage-zero/usage-one destructors on unconstructed storage. */
        task = lsf_device_record(&factory.pool, source.owner, source.task,
            LSF_DEVICE_CLEANUP_TASK);
        if (!task || factory.device->cleanup_lifecycle != LSF_CLEANUP_UNINITIALIZED ||
            task->deferred != LSF_PREPAID_PRIVATE ||
            task->cache_bucket != source.request.slot ||
            task->cache_anchor != source.request.generation ||
            lsf_prepaid_cleanup_irq_abort_locked(source,
                (void *)((char *)page_address(factory.pages) + task->offset)) ||
            !lsf_device_finish(&factory.pool, source.owner, source.task,
                LSF_DEVICE_CLEANUP_TASK))
            goto poison;
        factory.device->cleanup_task_claimed = 2u;
        factory.device->cleanup_lifecycle = LSF_CLEANUP_TASK_RETURNED;
        factory.device->cleanup_final_phase = LSF_CLEANUP_FINAL_RETURNED;
    } else if (factory.device->cleanup_lifecycle != LSF_CLEANUP_TASK_RETURNED &&
               factory.device->cleanup_lifecycle != LSF_CLEANUP_ABORT_STACK_RETURNED)
        goto poison;
    result = 1;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_cleanup_worker_stop_take(struct lsf_cleanup_task_source *source,
    struct kthread_worker **worker, struct task_struct **task)
{
    struct lsf_prepaid_view *request;
    unsigned long flags, request_bytes, worker_offset, worker_bytes;
    int result = 0;
    if (!source || !worker || !task || in_interrupt() || irqs_disabled() ||
        lsf_prepaid_cleanup_worker_geometry(&request_bytes, &worker_offset, &worker_bytes) ||
        worker_bytes != sizeof(**worker) || worker_offset > request_bytes ||
        worker_bytes > request_bytes - worker_offset)
        return -1;
    *worker = NULL;
    *task = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.device || !factory.device->cleanup_worker_associated)
        goto out;
    *source = (struct lsf_cleanup_task_source){factory.device->key, factory.device->root,
        factory.device->cleanup_request, factory.device->cleanup_task};
    if (!lsf_cleanup_request_identity_locked(*source) || !factory.pool.stopped ||
        !factory.pool.contexts[source->owner.slot].closed ||
        (factory.device->cleanup_request_users & LSF_CLEANUP_REQUEST_OPENER) ||
        factory.device->cleanup_worker_stop)
        goto poison;
    request = lsf_device_record(&factory.pool, source->owner, source->request,
        LSF_DEVICE_CLEANUP_REQUEST);
    *task = (void *)((char *)page_address(factory.pages) +
        factory.pool.records[source->task.slot].offset);
    /* Exact Task birth BEFORE its fields or reference acquisition. This real
     * stop continuation is independent of the final-stack continuation. */
    if (!request || request->bytes < request_bytes ||
        !lsf_cleanup_lifecycle_identity_locked(*source, *task) ||
        factory.device->cleanup_lifecycle != LSF_CLEANUP_PUBLISHED ||
        READ_ONCE((*task)->__state) == TASK_DEAD || !tryget_task_struct(*task))
        goto poison;
    *worker = (void *)((char *)page_address(factory.pages) + request->offset + worker_offset);
    factory.device->cleanup_worker_stop = 1u;
    result = 1;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
    *task = NULL;
    result = -1;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_cleanup_worker_stopped(struct lsf_cleanup_task_source source)
{
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_cleanup_request_identity_locked(source) ||
        !factory.device->cleanup_worker_associated ||
        factory.device->cleanup_worker_stop != 1u)
        goto poison;
    /* Actual worker lists/flush/stop have finished outside all pool/create
     * locks. No Task field is read and no Task/Stack/Request is returned here. */
    factory.device->cleanup_worker_stop = 2u;
    result = 1;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

static int lsf_cleanup_request_ready_locked(struct lsf_cleanup_task_source source)
{
    struct lsf_prepaid_view *task;
    if (!lsf_cleanup_request_identity_locked(source) ||
        factory.device->cleanup_request_users ||
        factory.device->cleanup_task_claimed != 2u ||
        factory.device->cleanup_lifecycle != LSF_CLEANUP_TASK_RETURNED ||
        factory.device->cleanup_final_phase != LSF_CLEANUP_FINAL_RETURNED ||
        (factory.device->cleanup_worker_associated && factory.device->cleanup_worker_stop != 2u) ||
        source.task.slot >= LSF_ALLOCATION_SLOTS)
        return 0;
    /* The fixed original record cannot be reused. Validate the returned birth
     * WITHOUT following its former Task address. Real children held its return. */
    task = &factory.pool.records[source.task.slot];
    return task->phase == LSF_PREPAID_RETURNED &&
        task->generation == source.task.generation && task->kind == LSF_DEVICE_CLEANUP_TASK &&
        task->owner == source.owner.slot && task->owner_generation == source.owner.generation &&
        task->cache_bucket == source.request.slot && task->cache_anchor == source.request.generation;
}

int lsf_factory_cleanup_request_pending(void)
{
    struct lsf_cleanup_task_source source;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (factory.device && !factory.device->cleanup_request_returned) {
        source = (struct lsf_cleanup_task_source){factory.device->key, factory.device->root,
            factory.device->cleanup_request, factory.device->cleanup_task};
        result = lsf_cleanup_request_ready_locked(source);
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void lsf_factory_cleanup_request_drain(void)
{
    struct lsf_cleanup_task_source source;
    unsigned long flags;
    if (current != kthreadd_task || in_interrupt() || irqs_disabled())
        return;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.device || factory.device->cleanup_request_returned)
        goto out;
    source = (struct lsf_cleanup_task_source){factory.device->key, factory.device->root,
        factory.device->cleanup_request, factory.device->cleanup_task};
    if (!lsf_cleanup_request_ready_locked(source))
        goto out;
    spin_unlock_irqrestore(&pool_lock, flags);
    /* Actual descriptor BUSY epilogue, NO pool/create/VM/rq lock held. */
    if (lsf_prepaid_cleanup_request_irq_quiesce(source)) {
        lsf_factory_cleanup_stack_poison(source);
        return;
    }
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_cleanup_request_ready_locked(source) ||
        !lsf_device_finish(&factory.pool, source.owner, source.request, LSF_DEVICE_CLEANUP_REQUEST)) {
        lsf_cleanup_lifecycle_poison_locked();
        goto out;
    }
    factory.device->cleanup_request_returned = 1u;
    /* Original view only. No bank reuse, physical pages or native refund. */
out:
    spin_unlock_irqrestore(&pool_lock, flags);
}
