/* SPDX-License-Identifier: GPL-2.0-only */
/* Retained physical identity reads the SAME born records through quarantine.
 * It creates no allocation admission, operation grant or second ledger. */
static struct lsf_prepaid_view *lsf_cleanup_provider_held_record_locked(
    struct lsf_cleanup_task_source source, struct lsf_prepaid_ticket ticket,
    unsigned int kind, struct lsf_prepaid_ticket parent)
{
    struct lsf_prepaid_view *record;
    if (!factory.pages || !factory.device || !factory.pool.initialized ||
        !ticket.slot || ticket.slot >= LSF_ALLOCATION_SLOTS || !ticket.generation)
        return NULL;
    record = &factory.pool.records[ticket.slot];
    if ((record->phase != LSF_PREPAID_LIVE && record->phase != LSF_PREPAID_RETURNED) ||
        record->kind != kind || record->generation != ticket.generation ||
        record->owner != source.owner.slot || record->owner_generation != source.owner.generation ||
        record->cache_bucket != parent.slot || record->cache_anchor != parent.generation ||
        record->offset < LSF_FACTORY_INFRA_OFFSET ||
        record->offset - LSF_FACTORY_INFRA_OFFSET > LSF_FACTORY_INFRA_BYTES ||
        record->bytes > LSF_FACTORY_INFRA_BYTES - (record->offset - LSF_FACTORY_INFRA_OFFSET))
        return NULL;
    return record;
}

static int lsf_cleanup_provider_physical_locked(struct lsf_cleanup_task_source *source)
{
    struct lsf_prepaid_view *root, *request, *task;
    unsigned long base, address = (unsigned long)current;
    unsigned int role;
    if (!factory.pages)
        return 0;
    base = (unsigned long)page_address(factory.pages);
    if (address < base || address - base >= LSF_BACKING_BYTES)
        return 0;
    if (!factory.device)
        return -EIO;
    *source = (struct lsf_cleanup_task_source){factory.device->key, factory.device->root,
        factory.device->cleanup_request, factory.device->cleanup_task};
    if (source->owner.slot != LSF_DEVICE_OWNER_SLOT || !source->owner.generation ||
        factory.device->cleanup_task_claimed != 1u)
        return -EIO;
    root = lsf_cleanup_provider_held_record_locked(*source, source->root, LSF_DEVICE_ROOT,
        (struct lsf_prepaid_ticket){0});
    request = lsf_cleanup_provider_held_record_locked(*source, source->request,
        LSF_DEVICE_CLEANUP_REQUEST, source->root);
    task = lsf_cleanup_provider_held_record_locked(*source, source->task,
        LSF_DEVICE_CLEANUP_TASK, source->request);
    if (!root || !request || !task || root->phase != LSF_PREPAID_LIVE ||
        request->phase != LSF_PREPAID_LIVE || task->phase != LSF_PREPAID_LIVE ||
        root->bytes < sizeof(*factory.device) || task->bytes < sizeof(*current) ||
        factory.device != (void *)(base + root->offset) ||
        (task->deferred != LSF_PREPAID_PUBLISHED && task->deferred != LSF_PREPAID_QUEUED) ||
        address != base + task->offset)
        return -EIO;
    /* All original births/ranges precede the first current Task field. */
    if (!refcount_read(&current->usage) || !(current->flags & PF_KTHREAD))
        return -EIO;
    role = factory.device->cleanup_physical_role;
    if (role == LSF_CLEANUP_PHYSICAL_PRIVATE)
        return 1;
    return role == LSF_CLEANUP_PHYSICAL_PROVIDER ? 2 : -EIO;
}

int lsf_factory_cleanup_provider_physical_current(struct lsf_cleanup_task_source *source)
{
    unsigned long flags;
    int result;
    if (!source || !in_task())
        return 0;
    *source = (struct lsf_cleanup_task_source){0};
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_cleanup_provider_physical_locked(source);
    spin_unlock_irqrestore(&pool_lock, flags);
    return result; /* Read-only identity; even quarantine is not operation authority. */
}

static int lsf_cleanup_provider_same_task_source(struct lsf_cleanup_task_source first,
    struct lsf_cleanup_task_source second)
{
    return first.owner.slot == second.owner.slot && first.owner.generation == second.owner.generation &&
        first.root.slot == second.root.slot && first.root.generation == second.root.generation &&
        first.request.slot == second.request.slot && first.request.generation == second.request.generation &&
        first.task.slot == second.task.slot && first.task.generation == second.task.generation;
}

int lsf_factory_cleanup_provider_snapshot_source(struct lsf_cleanup_task_source source,
    void **worker_address, void **pool_address)
{
    struct lsf_cleanup_task_source actual;
    struct lsf_prepaid_view *worker, *pool;
    unsigned long flags, worker_bytes, worker_alignment, pool_bytes, pool_alignment;
    int result = -EIO;
    if (!worker_address || !pool_address || !in_task() ||
        lsf_prepaid_cleanup_provider_geometry(&worker_bytes, &worker_alignment,
            &pool_bytes, &pool_alignment))
        return result;
    *worker_address = NULL;
    *pool_address = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    if (lsf_cleanup_provider_physical_locked(&actual) != 2 ||
        !lsf_cleanup_provider_same_task_source(source, actual))
        goto out;
    pool = lsf_cleanup_provider_held_record_locked(source, factory.device->cleanup_provider_pool,
        LSF_DEVICE_CLEANUP_PROVIDER_POOL, source.root);
    worker = lsf_cleanup_provider_held_record_locked(source, factory.device->cleanup_provider_worker,
        LSF_DEVICE_CLEANUP_PROVIDER_WORKER, factory.device->cleanup_provider_pool);
    if (!pool || !worker || pool->phase != LSF_PREPAID_LIVE || worker->phase != LSF_PREPAID_LIVE ||
        pool->bytes < pool_bytes || worker->bytes < worker_bytes ||
        !worker_alignment || worker_alignment > 64u || !pool_alignment || pool_alignment > 64u ||
        worker->offset % worker_alignment || pool->offset % pool_alignment)
        goto out;
    *worker_address = (char *)page_address(factory.pages) + worker->offset;
    *pool_address = (char *)page_address(factory.pages) + pool->offset;
    result = 1;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_cleanup_provider_bind(struct lsf_cleanup_task_source source,
    struct lsf_prepaid_ticket pool_ticket, struct lsf_prepaid_ticket worker_ticket)
{
    struct lsf_prepaid_view *pool, *worker;
    unsigned long flags, worker_bytes, worker_alignment, pool_bytes, pool_alignment;
    int result = -EOPNOTSUPP;
    if (lsf_prepaid_cleanup_provider_geometry(&worker_bytes, &worker_alignment,
            &pool_bytes, &pool_alignment))
        return result;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_factory_cleanup_task_source_locked(source) || factory.pool.stopped ||
        factory.pool.contexts[source.owner.slot].closed || factory.device->cleanup_task_claimed ||
        factory.device->cleanup_lifecycle != LSF_CLEANUP_UNINITIALIZED ||
        factory.device->cleanup_physical_role != LSF_CLEANUP_PHYSICAL_PRIVATE ||
        factory.device->cleanup_provider_pool.slot || factory.device->cleanup_provider_pool.generation ||
        factory.device->cleanup_provider_worker.slot || factory.device->cleanup_provider_worker.generation ||
        current->mm != factory.mm || task_tgid(current) != factory.tgid ||
        current_cred() != factory.cred || !current->nsproxy || current->nsproxy->net_ns != factory.net)
        goto out;
    pool = lsf_device_record(&factory.pool, source.owner, pool_ticket, LSF_DEVICE_CLEANUP_PROVIDER_POOL);
    worker = lsf_device_record(&factory.pool, source.owner, worker_ticket, LSF_DEVICE_CLEANUP_PROVIDER_WORKER);
    if (!pool || !worker || pool->deferred != LSF_PREPAID_PRIVATE || worker->deferred != LSF_PREPAID_PRIVATE ||
        pool->cache_bucket != source.root.slot || pool->cache_anchor != source.root.generation ||
        worker->cache_bucket != pool_ticket.slot || worker->cache_anchor != pool_ticket.generation ||
        pool->bytes < pool_bytes || worker->bytes < worker_bytes ||
        !worker_alignment || worker_alignment > 64u || !pool_alignment || pool_alignment > 64u ||
        worker->offset % worker_alignment || pool->offset % pool_alignment)
        goto out;
    factory.device->cleanup_provider_pool = pool_ticket;
    factory.device->cleanup_provider_worker = worker_ticket;
    /* Immutable physical role, written once BEFORE actual Task claim/publication. */
    factory.device->cleanup_physical_role = LSF_CLEANUP_PHYSICAL_PROVIDER;
    result = 0;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void lsf_factory_cleanup_provider_dispatch_begin(void)
{
    struct lsf_cleanup_task_source source, actual;
    struct work_struct *work;
    work_func_t function;
    unsigned long flags;
    int origin = lsf_factory_cleanup_provider_physical_current(&source);
    if (origin != 2)
        return;
    /* Snapshot derives actual current Task/worker/pool/current_work/function;
     * none is accepted from a producer or from a callback's arguments. */
    origin = lsf_prepaid_cleanup_provider_snapshot(source, &work, &function);
    spin_lock_irqsave(&pool_lock, flags);
    if (lsf_cleanup_provider_physical_locked(&actual) != 2 ||
        !lsf_cleanup_provider_same_task_source(source, actual))
        goto out;
    if (origin || factory.device->cleanup_operation_active) {
        factory.device->cleanup_operation_active = 2u;
        lsf_cleanup_lifecycle_poison_locked();
        goto out;
    }
    factory.device->cleanup_operation_work = work;
    factory.device->cleanup_operation_function = function;
    factory.device->cleanup_operation_active = 1u; /* Real dispatch lifetime, not admission. */
out:
    spin_unlock_irqrestore(&pool_lock, flags);
}

void lsf_factory_cleanup_provider_dispatch_end(void)
{
    struct lsf_cleanup_task_source source;
    unsigned long flags;
    if (!in_task())
        return;
    spin_lock_irqsave(&pool_lock, flags);
    if (lsf_cleanup_provider_physical_locked(&source) == 2) {
        /* Only the actual executing Task clears its tuple, before WQ returns
         * worker metadata. Descriptor return inside callback is permitted. */
        factory.device->cleanup_operation_active = 0;
        factory.device->cleanup_operation_work = NULL;
        factory.device->cleanup_operation_function = NULL;
    }
    spin_unlock_irqrestore(&pool_lock, flags);
}

int lsf_factory_cleanup_provider_operation_current(void)
{
    struct lsf_cleanup_task_source source;
    struct lsf_factory_device_firmware *owned;
    struct lsf_prepaid_view *record;
    struct lsf_prepaid_ticket pci;
    unsigned long flags, base, address;
    int result = 0, role;
    if (!in_task())
        return 0;
    spin_lock_irqsave(&pool_lock, flags);
    role = lsf_cleanup_provider_physical_locked(&source);
    if (role < 0)
        goto poison;
    if (!role) {
        result = 0;
        goto out;
    }
    if (role == 1) {
        /* Preserve existing private-operation behavior through normal close. */
        if (!lsf_cleanup_lifecycle_identity_locked(source, current) ||
            factory.device->cleanup_lifecycle != LSF_CLEANUP_PUBLISHED ||
            factory.device->cleanup_final_phase != LSF_CLEANUP_FINAL_NONE)
            goto poison;
        result = 1;
        goto out;
    }
    if (!factory.device->cleanup_operation_active)
        goto out; /* Real provider idle/init/exit, even during Root quarantine. */
    if (factory.device->cleanup_operation_active != 1u)
        goto poison;
    address = (unsigned long)factory.device->cleanup_operation_work;
    base = (unsigned long)page_address(factory.pages);
    if (address < base || address - base >= LSF_BACKING_BYTES)
        goto out; /* Ordinary callback retains ONLY original provider semantics. */
    /* An in-bank work candidate never takes normal fallback, including after
     * logical return or quarantine. The exact actual WORK grants no new owner. */
    owned = lsf_factory_device_firmware_locked();
    if (!owned || factory.pool.poisoned || READ_ONCE(factory.uncertain) ||
        factory.device->cleanup_operation_work != &owned->work ||
        factory.device->cleanup_operation_function != lsf_factory_device_firmware_put)
        goto poison;
    record = &factory.pool.records[factory.device->firmware.slot];
    if (record->phase != LSF_PREPAID_LIVE || record->deferred != LSF_PREPAID_QUEUED ||
        !owned->retirement || !owned->queued || !owned->putting || owned->returned ||
        lsf_factory_device_firmware_pci(owned->pci_address, &pci) != 1 ||
        !lsf_factory_device_firmware_for_pci(owned->pci_address, pci))
        goto poison;
    result = 1;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
    result = -EIO;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
