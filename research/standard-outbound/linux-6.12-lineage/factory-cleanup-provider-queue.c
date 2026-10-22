/* SPDX-License-Identifier: GPL-2.0-only */
int lsf_factory_cleanup_provider_profile_ready(void)
{
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = factory.cleanup_observer_prebirth && factory.pages && factory.opened && factory.device &&
        !factory.pool.stopped && !factory.pool.poisoned && !READ_ONCE(factory.uncertain) &&
        current->mm == factory.mm && task_tgid(current) == factory.tgid && current_cred() == factory.cred &&
        current->nsproxy && current->nsproxy->net_ns == factory.net;
    spin_unlock_irqrestore(&pool_lock, flags);
    return result; /* Marker is set ONLY by the real complete observer transaction. */
}

/* These are REAL short reader/registration borrows of the one charged Control
 * record. They are not allocation charges or an alternative lifetime ledger. */
void *lsf_factory_cleanup_provider_control_get(const void *candidate)
{
    struct lsf_cleanup_task_source source;
    struct lsf_prepaid_view *record;
    unsigned long flags;
    void *address = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.device || factory.device->cleanup_provider_control_retiring)
        goto out;
    source = (struct lsf_cleanup_task_source){factory.device->key, factory.device->root,
        factory.device->cleanup_request, factory.device->cleanup_task};
    address = lsf_cleanup_provider_part_locked(source, LSF_PROVIDER_CONTROL, candidate, candidate != NULL);
    record = lsf_provider_part_record_locked(source, LSF_PROVIDER_CONTROL, address);
    if (!record || (record->deferred != LSF_PREPAID_PUBLISHED && record->deferred != LSF_PREPAID_QUEUED)) {
        address = NULL;
        goto out;
    }
    if (factory.device->cleanup_provider_control_readers == LSF_ALLOCATION_SLOTS) {
        lsf_cleanup_lifecycle_poison_locked();
        address = NULL;
        goto out;
    }
    factory.device->cleanup_provider_control_readers++;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return address;
}

void lsf_factory_cleanup_provider_control_put(const void *candidate)
{
    struct lsf_cleanup_task_source source;
    unsigned long flags;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.device)
        goto poison;
    source = (struct lsf_cleanup_task_source){factory.device->key, factory.device->root,
        factory.device->cleanup_request, factory.device->cleanup_task};
    if (!candidate || !lsf_provider_part_record_locked(source, LSF_PROVIDER_CONTROL, candidate) ||
        !factory.device->cleanup_provider_control_readers)
        goto poison;
    factory.device->cleanup_provider_control_readers--;
    if (!factory.device->cleanup_provider_control_readers && factory.device->cleanup_provider_control_retiring &&
        !lsf_prepaid_cleanup_provider_retirement_kick_held((void *)candidate))
        goto poison;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
}

int lsf_factory_cleanup_provider_control_seal(struct lsf_cleanup_task_source source, const void *candidate)
{
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (factory.device && lsf_provider_part_record_locked(source, LSF_PROVIDER_CONTROL, candidate)) {
        /* Blocks new readers. The LAST actual put notifies the paid original
         * worker; queued/running retire work is never duplicated. */
        factory.device->cleanup_provider_control_retiring = 1u;
        result = !factory.device->cleanup_provider_control_readers;
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

static int lsf_provider_original_opener_locked(struct lsf_cleanup_task_source source)
{
    struct lsf_cleanup_task_source actual;
    if (!factory.pages || !factory.device || !factory.opened ||
        current->mm != factory.mm || task_tgid(current) != factory.tgid || current_cred() != factory.cred ||
        !current->nsproxy || current->nsproxy->net_ns != factory.net)
        return 0;
    actual = (struct lsf_cleanup_task_source){factory.device->key, factory.device->root,
        factory.device->cleanup_request, factory.device->cleanup_task};
    return lsf_cleanup_provider_same_task_source(source, actual) &&
        lsf_cleanup_provider_held_record_locked(source, source.request,
            LSF_DEVICE_CLEANUP_REQUEST, source.root);
}

int lsf_factory_cleanup_provider_submit(struct lsf_cleanup_task_source source, const void *worker)
{
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (lsf_provider_original_opener_locked(source) && !factory.pool.stopped &&
        !factory.pool.poisoned && !READ_ONCE(factory.uncertain) &&
        !factory.device->cleanup_task_claimed && !factory.device->cleanup_provider_submitted &&
        factory.device->cleanup_physical_role == LSF_CLEANUP_PHYSICAL_PROVIDER &&
        lsf_cleanup_provider_part_locked(source, LSF_PROVIDER_WORKER, worker, 1)) {
        /* Actual kthread_create_lock is held by the only call site. This
         * immutable publication latch precedes WRITE_ONCE(pending, owned),
         * closing the cleared-pending/before-Task-claim cancellation race. */
        factory.device->cleanup_provider_submitted = 1u;
        result = 1;
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void lsf_factory_cleanup_provider_task_failed(struct lsf_cleanup_task_source source)
{
    unsigned long flags;
    spin_lock_irqsave(&pool_lock, flags);
    if (lsf_provider_original_opener_locked(source) && factory.device->cleanup_provider_submitted &&
        !factory.device->cleanup_worker_associated)
        factory.device->cleanup_provider_task_failed = 1u;
    else
        lsf_cleanup_lifecycle_poison_locked();
    spin_unlock_irqrestore(&pool_lock, flags);
}

int lsf_factory_cleanup_provider_cancel_unsubmitted(struct lsf_cleanup_task_source source)
{
    struct lsf_prepaid_view *task;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_provider_original_opener_locked(source) || factory.device->cleanup_provider_submitted ||
        factory.device->cleanup_task_claimed || factory.device->cleanup_lifecycle != LSF_CLEANUP_UNINITIALIZED)
        goto out;
    task = lsf_device_record(&factory.pool, source.owner, source.task, LSF_DEVICE_CLEANUP_TASK);
    if (!task || task->deferred != LSF_PREPAID_PRIVATE ||
        lsf_prepaid_cleanup_provider_irq_abort_opener_locked(source,
            (void *)((char *)page_address(factory.pages) + task->offset)) ||
        !lsf_device_finish(&factory.pool, source.owner, source.task, LSF_DEVICE_CLEANUP_TASK))
        goto poison;
    /* No create request was ever published. Neither creator nor opener can
     * perform another request access. No zeroed Task field is dereferenced. */
    factory.device->cleanup_request_users = 0;
    factory.device->cleanup_task_claimed = 2u;
    factory.device->cleanup_lifecycle = LSF_CLEANUP_TASK_RETURNED;
    factory.device->cleanup_final_phase = LSF_CLEANUP_FINAL_RETURNED;
    factory.device->cleanup_provider_task_failed = 1u;
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

int lsf_factory_cleanup_provider_unused_worker_finish(struct lsf_cleanup_task_source source)
{
    struct lsf_prepaid_view *task, *worker;
    struct lsf_prepaid_ticket ticket;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.device || !factory.device->cleanup_provider_task_failed ||
        factory.device->cleanup_worker_associated || factory.device->cleanup_request_users)
        goto out;
    task = lsf_cleanup_provider_held_record_locked(source, source.task,
        LSF_DEVICE_CLEANUP_TASK, source.request);
    if (!task || task->phase != LSF_PREPAID_RETURNED)
        goto out;
    ticket = factory.device->cleanup_provider_worker;
    worker = lsf_cleanup_provider_held_record_locked(source, ticket,
        LSF_DEVICE_CLEANUP_PROVIDER_WORKER, factory.device->cleanup_provider_pool);
    if (!worker || worker->phase != LSF_PREPAID_LIVE)
        goto out;
    if (!lsf_provider_part_queue_locked(source, worker) ||
        !lsf_device_finish(&factory.pool, source.owner, ticket, LSF_DEVICE_CLEANUP_PROVIDER_WORKER))
        goto poison;
    lsf_provider_pool_finish_if_ready_locked(source);
    result = 1;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_cleanup_provider_core_retired(struct lsf_cleanup_task_source source)
{
    struct lsf_prepaid_view *record;
    struct lsf_prepaid_ticket parent;
    unsigned long flags;
    unsigned int i, part, seen = 0;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.device)
        goto out;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->owner != source.owner.slot || record->owner_generation != source.owner.generation)
            continue;
        if (record->kind < LSF_DEVICE_CLEANUP_PROVIDER_POOL || record->kind > LSF_DEVICE_CLEANUP_PROVIDER_ATTRS)
            continue;
        part = record->kind - LSF_DEVICE_CLEANUP_PROVIDER_POOL;
        parent = part ? factory.device->cleanup_provider_pool : source.root;
        if ((seen & (1u << part)) || record->phase != LSF_PREPAID_RETURNED ||
            !lsf_cleanup_provider_held_record_locked(source,
                (struct lsf_prepaid_ticket){i, record->generation}, record->kind, parent))
            goto out;
        seen |= 1u << part;
    }
    result = seen == 15u; /* Exact four original records, never an empty scan. */
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_cleanup_provider_request_close(void)
{
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (factory.device && factory.device->cleanup_physical_role == LSF_CLEANUP_PHYSICAL_PROVIDER) {
        factory.device->cleanup_provider_close_requested = 1u;
        result = 1;
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void lsf_factory_cleanup_provider_queue_closed(void)
{
    /* Called after the actual ACPI adapter closes its sole Root producer.
     * This closes only our Root's admission, never ordinary ACPI operations. */
    lsf_cleanup_admission_close();
    (void)lsf_factory_cleanup_provider_request_close();
}

int lsf_factory_cleanup_provider_close_ready(struct lsf_cleanup_task_source source)
{
    struct lsf_factory_device_firmware *firmware;
    struct lsf_cleanup_task_source actual;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.device)
        goto out;
    actual = (struct lsf_cleanup_task_source){factory.device->key, factory.device->root,
        factory.device->cleanup_request, factory.device->cleanup_task};
    if (!lsf_cleanup_provider_same_task_source(source, actual) ||
        !factory.device->cleanup_provider_close_requested)
        goto out;
    if (!factory.pool.stopped || !factory.pool.contexts[source.owner.slot].closed ||
        factory.device->constructor_active)
        goto out;
    if (!factory.device->firmware.slot) {
        result = 1; /* Admission is closed; the one-shot descriptor cannot be born. */
        goto out;
    }
    firmware = lsf_factory_device_firmware_locked();
    if (firmware && firmware->returned &&
        factory.pool.records[factory.device->firmware.slot].phase == LSF_PREPAID_RETURNED)
        result = 1; /* Actual sole producer completed; no racy queue-emptiness guess. */
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
