/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in factory.c after its original locks and device state. The request
 * and task live in the original infrastructure bank, not a second task pool. */
static int lsf_factory_cleanup_task_source_locked(struct lsf_cleanup_task_source source)
{
    struct lsf_prepaid_view *request, *task;
    if (!factory.pages || !factory.device || !factory.opened ||
        READ_ONCE(factory.uncertain) ||
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
        task->deferred == LSF_PREPAID_PRIVATE &&
        request->cache_bucket == source.root.slot &&
        request->cache_anchor == source.root.generation &&
        task->cache_bucket == source.request.slot &&
        task->cache_anchor == source.request.generation;
}

int lsf_factory_cleanup_task_reserve(unsigned long request_bytes,
    unsigned long task_bytes, unsigned long alignment,
    struct lsf_cleanup_task_source *source, void **request_address)
{
    struct lsf_prepaid_context *context;
    struct lsf_prepaid_ticket request, task;
    unsigned long flags;
    lsf_u64 first, second, request_offset, task_offset;
    unsigned long actual_task_bytes, actual_alignment;
    unsigned int i, empty = 0;
    int result = -EOPNOTSUPP;
    if (!source || !request_address)
        return result;
    *source = (struct lsf_cleanup_task_source){0};
    *request_address = NULL;
    if (lsf_prepaid_cleanup_task_geometry(&actual_task_bytes, &actual_alignment) ||
        task_bytes != actual_task_bytes || alignment != actual_alignment ||
        !request_bytes || !task_bytes || !alignment || alignment > 64u ||
        (alignment & (alignment - 1u)) ||
        request_bytes > LSF_FACTORY_INFRA_BYTES || task_bytes > LSF_FACTORY_INFRA_BYTES)
        return result;
    first = ((lsf_u64)request_bytes + 63u) & ~(lsf_u64)63u;
    second = ((lsf_u64)task_bytes + 63u) & ~(lsf_u64)63u;
    spin_lock_irqsave(&pool_lock, flags);
    /* Actual original opener only. No task pointer or scope is accepted from
     * the caller. The later kthreadd consumer receives only these born tokens. */
    if (!factory.pages || !factory.device || !factory.opened ||
        READ_ONCE(factory.uncertain) || factory.pool.stopped ||
        current->mm != factory.mm || task_tgid(current) != factory.tgid ||
        current_cred() != factory.cred || !current->nsproxy ||
        current->nsproxy->net_ns != factory.net ||
        factory.device->cleanup_attempted || factory.device->pci_attempted ||
        !lsf_device_record(&factory.pool, factory.device->key,
            factory.device->root, LSF_DEVICE_ROOT))
        goto out;
    context = lsf_device_context(&factory.pool, factory.device->key);
    if (!context || context->closed || first > LSF_FACTORY_INFRA_BYTES ||
        second > LSF_FACTORY_INFRA_BYTES - first ||
        context->cursor > LSF_FACTORY_INFRA_BYTES - first - second ||
        !factory.pool.next_generation ||
        factory.pool.next_generation >= (lsf_u64)-2)
        goto out;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i)
        if (factory.pool.records[i].phase == LSF_PREPAID_EMPTY)
            empty++;
    if (empty < 2u)
        goto out;
    /* Complete two-record/byte preflight above precedes either admission,
     * any memset, and all actual task initialization. No allocation retries. */
    factory.device->cleanup_attempted = 1;
    if (!lsf_device_allocate(&factory.pool, factory.device->key, request_bytes,
            LSF_DEVICE_CLEANUP_REQUEST, factory.device->root, &request, &request_offset) ||
        !lsf_device_allocate(&factory.pool, factory.device->key, task_bytes,
            LSF_DEVICE_CLEANUP_TASK, request, &task, &task_offset))
        goto poison;
    factory.device->cleanup_request = request;
    factory.device->cleanup_task = task;
    *source = (struct lsf_cleanup_task_source){factory.device->key,
        factory.device->root, request, task};
    *request_address = (char *)page_address(factory.pages) + request_offset;
    memset(*request_address, 0, request_bytes);
    memset((char *)page_address(factory.pages) + task_offset, 0, task_bytes);
    result = 0;
    goto out;
poison:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

struct task_struct *lsf_factory_cleanup_task_claim(struct lsf_cleanup_task_source source)
{
    struct task_struct *result = NULL;
    struct lsf_prepaid_view *task;
    unsigned long task_bytes, alignment;
    unsigned long flags;
    if (lsf_prepaid_cleanup_task_geometry(&task_bytes, &alignment))
        return NULL;
    spin_lock_irqsave(&pool_lock, flags);
    /* kthreadd is the actual existing constructor, not a borrowed callback
     * actor inferred from a thread name or supplied by a request. */
    if (current != kthreadd_task || !lsf_factory_cleanup_task_source_locked(source) ||
        factory.pool.stopped || factory.pool.contexts[source.owner.slot].closed ||
        factory.device->cleanup_task_claimed)
        goto out;
    task = &factory.pool.records[source.task.slot];
    if (task->bytes < task_bytes ||
        ((unsigned long)page_address(factory.pages) + task->offset) & (alignment - 1u))
        goto out;
    factory.device->cleanup_task_claimed = 1;
    result = (void *)((char *)page_address(factory.pages) + task->offset);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_cleanup_task_abort(struct lsf_cleanup_task_source source,
    struct task_struct *task)
{
    struct lsf_prepaid_view *record;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (current != kthreadd_task || !lsf_factory_cleanup_task_source_locked(source) ||
        factory.device->cleanup_task_claimed != 1u)
        goto poison;
    record = &factory.pool.records[source.task.slot];
    if ((const void *)task != (char *)page_address(factory.pages) + record->offset ||
        !lsf_device_finish(&factory.pool, source.owner, source.task, LSF_DEVICE_CLEANUP_TASK))
        goto poison;
    factory.device->cleanup_task_claimed = 2u;
    /* Only this never-published task view returned. Request, cursor, physical
     * bank and original native reservation stay held; no reusable budget. */
    result = 1;
    goto out;
poison:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
