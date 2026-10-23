/* SPDX-License-Identifier: GPL-2.0-only */
/* Included after actual constructor helpers and before original PCI security.
 * Same original records and bounded bank. Shared cache births belong to the
 * actual Root and remain valid after their creating task physically returns. */
#define LSF_ROOT_SECURITY_DELEGATE 2
static_assert(LSF_ROOT_SECURITY_TASK_BIRTH == LSF_DEVICE_CLEANUP_TASK);

static unsigned int lsf_cleanup_security_physical_kind(unsigned int kind)
{
    switch (kind) {
    case LSF_PREPAID_AVC_NODE: return LSF_ROOT_SECURITY_AVC_NODE;
    case LSF_PREPAID_AVC_XPERMS: return LSF_ROOT_SECURITY_AVC_XPERMS;
    case LSF_PREPAID_AVC_DECISION: return LSF_ROOT_SECURITY_AVC_DECISION;
    case LSF_PREPAID_AVC_DATA: return LSF_ROOT_SECURITY_AVC_DATA;
    case LSF_PREPAID_SIDCACHE: return LSF_ROOT_SECURITY_SIDCACHE;
    case LSF_PREPAID_AUDIT_STRING: return LSF_ROOT_SECURITY_AUDIT_STRING;
    case LSF_PREPAID_AUDIT_BUFFER: return LSF_ROOT_SECURITY_AUDIT_BUFFER;
    case LSF_PREPAID_AUDIT_SKB: return LSF_ROOT_SECURITY_AUDIT_SKB;
    case LSF_PREPAID_AUDIT_HEAD: return LSF_ROOT_SECURITY_AUDIT_HEAD;
    default: return 0;
    }
}

static int lsf_cleanup_security_root_locked(struct lsf_cleanup_security_source source)
{
    /* Closing seals admission; it does not invalidate authentic late cache
     * callbacks. Root birth/full generations remain the same physical owner. */
    return factory.pages && factory.device && factory.opened &&
        source.owner.slot == factory.device->key.slot &&
        source.owner.generation == factory.device->key.generation &&
        source.root.slot == factory.device->root.slot &&
        source.root.generation == factory.device->root.generation &&
        lsf_device_record(&factory.pool, source.owner, source.root, LSF_DEVICE_ROOT);
}

static struct lsf_prepaid_view *lsf_cleanup_security_record_locked(struct lsf_factory_blob copy)
{
    struct lsf_cleanup_security_source source = copy.cleanup;
    struct lsf_cleanup_task_source task_source;
    struct task_struct *task;
    struct lsf_prepaid_view *record;
    if (copy.domain != LSF_FACTORY_OWNER_CLEANUP || !lsf_factory_blob_shape(copy) ||
        !lsf_cleanup_security_root_locked(source))
        return NULL;
    record = lsf_device_record(&factory.pool, source.owner, source.allocation, source.kind);
    if (!record || source.address != (char *)page_address(factory.pages) + record->offset ||
        record->deferred > LSF_PREPAID_PUBLISHED)
        return NULL;
    if (source.kind == LSF_ROOT_SECURITY_TASK_BIRTH) {
        /* Only the actual constructor may introduce the first carrier. */
        if (current != kthreadd_task ||
            !lsf_cleanup_child_source_locked(&task_source, &task) ||
            factory.device->cleanup_lifecycle != LSF_CLEANUP_METADATA ||
            factory.device->cleanup_final_phase != LSF_CLEANUP_FINAL_NONE ||
            record->deferred != LSF_PREPAID_PRIVATE || task != source.address ||
            task_source.task.slot != source.allocation.slot ||
            task_source.task.generation != source.allocation.generation)
            return NULL;
        return record;
    }
    if (!lsf_root_security_kind(source.kind) || record->cache_bucket != source.root.slot ||
        record->cache_anchor != source.root.generation)
        return NULL;
    if (source.kind == LSF_ROOT_SECURITY_AVC_NODE && record->deferred != LSF_PREPAID_PRIVATE) {
        if (!record->security_cache_location || record->security_cache_location > 512u ||
            record->security_cache_identity)
            return NULL;
    } else if (source.kind == LSF_ROOT_SECURITY_SIDCACHE && record->deferred != LSF_PREPAID_PRIVATE) {
        if (record->security_cache_location || !record->security_cache_identity)
            return NULL;
    } else if (record->security_cache_location || record->security_cache_identity) {
        return NULL;
    }
    return record;
}

int lsf_factory_cleanup_task_constructor_blob(const struct task_struct *actual,
    struct lsf_factory_blob *copy)
{
    struct lsf_cleanup_task_source source;
    struct task_struct *task;
    unsigned long flags, base, at = (unsigned long)actual;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.pages)
        goto out;
    base = (unsigned long)page_address(factory.pages);
    if (at < base || at - base >= LSF_BACKING_BYTES)
        goto out;
    result = -1;
    /* The actual composite lbs_task may be zero. Authority is the already-paid
     * original Task birth, never a guessed/nonexistent security-child pointer. */
    if (!copy || !lsf_cleanup_child_source_locked(&source, &task) || task != actual)
        goto poison;
    *copy = (struct lsf_factory_blob){.ticket = source.task, .domain = LSF_FACTORY_OWNER_CLEANUP,
        .cleanup = {source.owner, source.root, source.task, task, LSF_ROOT_SECURITY_TASK_BIRTH}};
    if (!lsf_cleanup_security_record_locked(*copy))
        goto poison;
    result = 1;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

static int lsf_cleanup_security_lookup_locked(const void *address, unsigned int logical_kind,
    struct lsf_factory_blob *copy)
{
    struct lsf_prepaid_view *record;
    struct lsf_cleanup_security_source source;
    unsigned long base, at = (unsigned long)address;
    unsigned int i, kind = lsf_cleanup_security_physical_kind(logical_kind);
    if (!factory.pages)
        return LSF_ROOT_SECURITY_DELEGATE;
    base = (unsigned long)page_address(factory.pages);
    if (at < base || at - base >= LSF_BACKING_BYTES)
        return LSF_ROOT_SECURITY_DELEGATE;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->offset != at - base)
            continue;
        if (!lsf_root_security_kind(record->kind))
            return LSF_ROOT_SECURITY_DELEGATE;
        if (!factory.device || !copy || !kind || record->kind != kind)
            goto poison;
        source = (struct lsf_cleanup_security_source){factory.device->key,
            factory.device->root, {i, record->generation}, address, kind};
        *copy = (struct lsf_factory_blob){.ticket = source.allocation,
            .domain = LSF_FACTORY_OWNER_CLEANUP, .cleanup = source};
        if (!lsf_cleanup_security_record_locked(*copy))
            goto poison;
        return 1;
    }
    return LSF_ROOT_SECURITY_DELEGATE;
poison:
    lsf_cleanup_lifecycle_poison_locked();
    return -1;
}

static void *lsf_cleanup_security_allocate_locked(struct lsf_factory_blob source,
    unsigned long bytes, unsigned int logical_kind)
{
    struct lsf_prepaid_ticket ticket;
    unsigned int kind = lsf_cleanup_security_physical_kind(logical_kind);
    lsf_u64 offset;
    void *result;
    if (!kind || !bytes || bytes > LSF_FACTORY_INFRA_BYTES ||
        !lsf_cleanup_security_record_locked(source)) {
        lsf_cleanup_lifecycle_poison_locked();
        return NULL;
    }
    /* Shared AVC/SID/audit descendants outlive their creator. The real Root,
     * never a PCI carrier or task continuation, is their original parent. */
    if (!lsf_device_allocate(&factory.pool, source.cleanup.owner, bytes, kind,
            source.cleanup.root, &ticket, &offset))
        return NULL;
    result = (char *)page_address(factory.pages) + offset;
    memset(result, 0, bytes);
    return result;
}

static int lsf_cleanup_security_finish_locked(struct lsf_factory_blob source,
    unsigned int logical_kind)
{
    struct lsf_prepaid_view *record = lsf_cleanup_security_record_locked(source);
    unsigned int kind = lsf_cleanup_security_physical_kind(logical_kind);
    if (!record || !kind || record->kind != kind ||
        !lsf_device_finish(&factory.pool, source.cleanup.owner, source.ticket, kind)) {
        lsf_cleanup_lifecycle_poison_locked();
        return 0;
    }
    return 1;
}

static int lsf_cleanup_security_phase_locked(struct lsf_factory_blob source, unsigned int phase)
{
    struct lsf_prepaid_view *record = lsf_cleanup_security_record_locked(source);
    if (!record || source.cleanup.kind != LSF_ROOT_SECURITY_AVC_NODE ||
        (phase != LSF_PREPAID_PRIVATE && phase != LSF_PREPAID_QUEUED) || record->deferred != phase) {
        lsf_cleanup_lifecycle_poison_locked();
        return 0;
    }
    return 1;
}

static int lsf_cleanup_security_publish_locked(struct lsf_factory_blob source,
    unsigned int location, lsf_u64 identity)
{
    struct lsf_prepaid_view *record = lsf_cleanup_security_record_locked(source);
    if (!record || record->deferred != LSF_PREPAID_PRIVATE ||
        record->security_cache_location || record->security_cache_identity)
        goto poison;
    if (source.cleanup.kind == LSF_ROOT_SECURITY_AVC_NODE) {
        if (location >= 512u || identity)
            goto poison;
        record->security_cache_location = location + 1u;
    } else if (source.cleanup.kind == LSF_ROOT_SECURITY_SIDCACHE) {
        if (location || !identity)
            goto poison;
        record->security_cache_identity = identity;
    } else {
        goto poison;
    }
    record->deferred = LSF_PREPAID_PUBLISHED;
    return 1;
poison:
    lsf_cleanup_lifecycle_poison_locked();
    return -1;
}

static int lsf_cleanup_security_queue_locked(struct lsf_factory_blob source)
{
    struct lsf_prepaid_view *record = lsf_cleanup_security_record_locked(source);
    if (!record || record->deferred != LSF_PREPAID_PUBLISHED ||
        (source.cleanup.kind != LSF_ROOT_SECURITY_AVC_NODE &&
         source.cleanup.kind != LSF_ROOT_SECURITY_SIDCACHE) ||
        !lsf_device_queue(&factory.pool, source.cleanup.owner, source.ticket, source.cleanup.kind)) {
        lsf_cleanup_lifecycle_poison_locked();
        return -1;
    }
    return 1;
}

static struct lsf_prepaid_view *lsf_cleanup_security_avc_record_locked(
    struct lsf_factory_blob source, unsigned int phase, unsigned int bucket,
    struct lsf_prepaid_context **context)
{
    struct lsf_prepaid_view *record = lsf_cleanup_security_record_locked(source);
    if (!record || !context || bucket >= 512u || source.cleanup.kind != LSF_ROOT_SECURITY_AVC_NODE ||
        (phase != LSF_PREPAID_PRIVATE && phase != LSF_PREPAID_PUBLISHED) ||
        record->deferred != phase || record->security_cache_location !=
            (phase == LSF_PREPAID_PRIVATE ? 0u : bucket + 1u))
        return NULL;
    *context = lsf_device_context(&factory.pool, source.cleanup.owner);
    return *context && (*context)->live ? record : NULL;
}

static struct lsf_prepaid_view *lsf_cleanup_security_drain_record_locked(
    unsigned int slot, unsigned int kind)
{
    struct lsf_prepaid_view *record;
    struct lsf_prepaid_context *context;
    if (!factory.device || !slot || slot >= LSF_ALLOCATION_SLOTS ||
        (kind != LSF_ROOT_SECURITY_AVC_NODE && kind != LSF_ROOT_SECURITY_SIDCACHE))
        return NULL;
    context = lsf_device_context(&factory.pool, factory.device->key);
    if (!context || !context->closed)
        return NULL;
    record = &factory.pool.records[slot];
    if (record != lsf_device_record(&factory.pool, factory.device->key,
            (struct lsf_prepaid_ticket){slot, record->generation}, kind) ||
        record->deferred != LSF_PREPAID_PUBLISHED)
        return NULL;
    if (record->cache_bucket != factory.device->root.slot ||
        record->cache_anchor != factory.device->root.generation ||
        (kind == LSF_ROOT_SECURITY_AVC_NODE &&
         (!record->security_cache_location || record->security_cache_location > 512u ||
          record->security_cache_identity)) ||
        (kind == LSF_ROOT_SECURITY_SIDCACHE &&
         (record->security_cache_location || !record->security_cache_identity))) {
        lsf_cleanup_lifecycle_poison_locked();
        return NULL;
    }
    return record;
}

int lsf_factory_cleanup_security_candidate(unsigned int slot, unsigned int kind,
    struct lsf_cleanup_security_source *candidate, unsigned int *location, lsf_u64 *identity)
{
    struct lsf_prepaid_view *record;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    record = lsf_cleanup_security_drain_record_locked(slot, kind);
    if (record && candidate && location && identity) {
        /* Scalar candidate cannot allocate or authorize a pointer access. */
        *candidate = (struct lsf_cleanup_security_source){factory.device->key,
            factory.device->root, {slot, record->generation}, NULL, kind};
        *location = record->security_cache_location;
        *identity = record->security_cache_identity;
        result = 1;
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_cleanup_security_current(struct lsf_cleanup_security_source candidate,
    unsigned int location, lsf_u64 identity, void **address)
{
    struct lsf_prepaid_view *record;
    struct lsf_factory_blob copy;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    record = lsf_cleanup_security_drain_record_locked(candidate.allocation.slot, candidate.kind);
    if (!record || !address || candidate.address ||
        !lsf_cleanup_security_root_locked(candidate) ||
        record->generation != candidate.allocation.generation ||
        record->cache_bucket != candidate.root.slot || record->cache_anchor != candidate.root.generation ||
        record->security_cache_location != location || record->security_cache_identity != identity)
        goto out;
    candidate.address = (char *)page_address(factory.pages) + record->offset;
    copy = (struct lsf_factory_blob){.ticket = candidate.allocation,
        .domain = LSF_FACTORY_OWNER_CLEANUP, .cleanup = candidate};
    if (lsf_cleanup_security_record_locked(copy)) {
        *address = (void *)candidate.address;
        result = 1;
    }
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
