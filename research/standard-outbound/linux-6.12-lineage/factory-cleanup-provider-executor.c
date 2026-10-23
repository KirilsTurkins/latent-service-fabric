/* SPDX-License-Identifier: GPL-2.0-only */
/* Fixed physical parts use the existing Root ancestry and record array. */
static unsigned int lsf_cleanup_provider_kind(unsigned int part)
{
    switch (part) {
    case LSF_PROVIDER_POOL: return LSF_DEVICE_CLEANUP_PROVIDER_POOL;
    case LSF_PROVIDER_WORKER: return LSF_DEVICE_CLEANUP_PROVIDER_WORKER;
    case LSF_PROVIDER_PWQ: return LSF_DEVICE_CLEANUP_PROVIDER_PWQ;
    case LSF_PROVIDER_ATTRS: return LSF_DEVICE_CLEANUP_PROVIDER_ATTRS;
    case LSF_PROVIDER_CONTROL: return LSF_DEVICE_CLEANUP_PROVIDER_CONTROL;
    case LSF_PROVIDER_CONTEXT: return LSF_DEVICE_CLEANUP_PROVIDER_CONTEXT;
    default: return 0;
    }
}

int lsf_factory_cleanup_provider_storage_reserve(struct lsf_cleanup_task_source source,
    struct lsf_cleanup_provider_storage *storage)
{
    unsigned long bytes[LSF_PROVIDER_PARTS], alignment[LSF_PROVIDER_PARTS], flags;
    struct lsf_prepaid_context *context;
    struct lsf_prepaid_ticket parent;
    lsf_u64 offsets[LSF_PROVIDER_PARTS], total = 0, rounded;
    unsigned int i, empty = 0;
    int result = -ENOMEM;
    if (!storage)
        return -EINVAL;
    *storage = (struct lsf_cleanup_provider_storage){0};
    for (i = 0; i < LSF_PROVIDER_PARTS; ++i) {
        if (lsf_prepaid_cleanup_provider_part_geometry(i, &bytes[i], &alignment[i]) ||
            !bytes[i] || bytes[i] > LSF_FACTORY_INFRA_BYTES || !alignment[i] ||
            alignment[i] > 64u || (alignment[i] & (alignment[i] - 1u)))
            return -EOPNOTSUPP;
        rounded = ((lsf_u64)bytes[i] + 63u) & ~(lsf_u64)63u;
        if (rounded > LSF_FACTORY_INFRA_BYTES - total)
            return -ENOMEM;
        total += rounded;
    }
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_factory_cleanup_task_source_locked(source) || factory.pool.stopped ||
        factory.pool.contexts[source.owner.slot].closed || factory.device->cleanup_task_claimed ||
        factory.device->cleanup_provider_storage_attempted ||
        factory.device->cleanup_lifecycle != LSF_CLEANUP_UNINITIALIZED ||
        current->mm != factory.mm || task_tgid(current) != factory.tgid ||
        current_cred() != factory.cred || !current->nsproxy || current->nsproxy->net_ns != factory.net)
        goto out;
    context = lsf_device_context(&factory.pool, source.owner);
    if (!context || context->cursor > LSF_FACTORY_INFRA_BYTES - total ||
        !factory.pool.next_generation || factory.pool.next_generation >= (lsf_u64)-LSF_PROVIDER_PARTS)
        goto out;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i)
        if (factory.pool.records[i].phase == LSF_PREPAID_EMPTY)
            empty++;
    if (empty < LSF_PROVIDER_PARTS)
        goto out;
    /* Complete fixed six-part/byte/generation preflight precedes every birth
     * and every memset. Partial invariant failure retains, never falls back. */
    factory.device->cleanup_provider_storage_attempted = 1u;
    for (i = 0; i < LSF_PROVIDER_PARTS; ++i) {
        parent = (i == LSF_PROVIDER_WORKER || i == LSF_PROVIDER_PWQ || i == LSF_PROVIDER_ATTRS) ?
            storage->tickets[LSF_PROVIDER_POOL] : source.root;
        if (!lsf_device_allocate(&factory.pool, source.owner, bytes[i],
                lsf_cleanup_provider_kind(i), parent, &storage->tickets[i], &offsets[i])) {
            lsf_cleanup_lifecycle_poison_locked();
            goto out;
        }
    }
    for (i = 0; i < LSF_PROVIDER_PARTS; ++i) {
        storage->addresses[i] = (char *)page_address(factory.pages) + offsets[i];
        memset(storage->addresses[i], 0, bytes[i]);
    }
    result = 0;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Read-only held metadata, including quarantine. This admits no allocation and
 * cannot turn a caller address into a birth. The authoritative record is first. */
static void *lsf_cleanup_provider_part_locked(struct lsf_cleanup_task_source source,
    unsigned int part, const void *candidate, int exact)
{
    struct lsf_prepaid_view *root, *request, *task, *record, *parent;
    struct lsf_cleanup_task_source actual;
    unsigned int i, kind = lsf_cleanup_provider_kind(part);
    unsigned long bytes, alignment, base;
    void *result = NULL;
    if (!kind || !factory.pages || !factory.device ||
        lsf_prepaid_cleanup_provider_part_geometry(part, &bytes, &alignment))
        return NULL;
    actual = (struct lsf_cleanup_task_source){factory.device->key, factory.device->root,
        factory.device->cleanup_request, factory.device->cleanup_task};
    if (!lsf_cleanup_provider_same_task_source(source, actual))
        return NULL;
    root = lsf_cleanup_provider_held_record_locked(source, source.root, LSF_DEVICE_ROOT,
        (struct lsf_prepaid_ticket){0});
    request = lsf_cleanup_provider_held_record_locked(source, source.request,
        LSF_DEVICE_CLEANUP_REQUEST, source.root);
    task = lsf_cleanup_provider_held_record_locked(source, source.task,
        LSF_DEVICE_CLEANUP_TASK, source.request);
    if (!root || !request || !task || root->phase != LSF_PREPAID_LIVE)
        return NULL;
    base = (unsigned long)page_address(factory.pages);
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->kind != kind || record->phase != LSF_PREPAID_LIVE ||
            record->owner != source.owner.slot || record->owner_generation != source.owner.generation)
            continue;
        if (part == LSF_PROVIDER_WORKER || part == LSF_PROVIDER_PWQ || part == LSF_PROVIDER_ATTRS) {
            if (!record->cache_bucket || record->cache_bucket >= LSF_ALLOCATION_SLOTS)
                return NULL;
            parent = lsf_cleanup_provider_held_record_locked(source,
                (struct lsf_prepaid_ticket){record->cache_bucket, record->cache_anchor},
                LSF_DEVICE_CLEANUP_PROVIDER_POOL, source.root);
            if (!parent || parent->phase != LSF_PREPAID_LIVE)
                return NULL;
        } else if (record->cache_bucket != source.root.slot || record->cache_anchor != source.root.generation) {
            return NULL;
        }
        if (!lsf_cleanup_provider_held_record_locked(source,
                (struct lsf_prepaid_ticket){i, record->generation}, kind,
                (struct lsf_prepaid_ticket){record->cache_bucket, record->cache_anchor}) ||
            record->bytes < bytes || !alignment || record->offset % alignment || result)
            return NULL;
        result = (void *)(base + record->offset);
    }
    return exact && candidate != result ? NULL : result;
}

int lsf_factory_cleanup_provider_storage_current(struct lsf_cleanup_task_source source,
    unsigned int part, const void *candidate)
{
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = candidate && lsf_cleanup_provider_part_locked(source, part, candidate, 1);
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void *lsf_factory_cleanup_provider_control_current(const void *candidate)
{
    struct lsf_cleanup_task_source source;
    unsigned long flags;
    void *result = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    if (factory.device) {
        source = (struct lsf_cleanup_task_source){factory.device->key, factory.device->root,
            factory.device->cleanup_request, factory.device->cleanup_task};
        result = lsf_cleanup_provider_part_locked(source, LSF_PROVIDER_CONTROL, candidate, candidate != NULL);
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void lsf_factory_cleanup_provider_hold(struct lsf_cleanup_task_source source)
{
    struct lsf_cleanup_task_source actual;
    unsigned long flags;
    spin_lock_irqsave(&pool_lock, flags);
    if (factory.device) {
        actual = (struct lsf_cleanup_task_source){factory.device->key, factory.device->root,
            factory.device->cleanup_request, factory.device->cleanup_task};
        if (lsf_cleanup_provider_same_task_source(source, actual))
            lsf_cleanup_lifecycle_poison_locked();
    }
    spin_unlock_irqrestore(&pool_lock, flags);
}

int lsf_factory_cleanup_provider_pool_address(const void *candidate)
{
    struct lsf_cleanup_task_source source;
    unsigned long flags, base, address = (unsigned long)candidate;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.pages)
        goto out;
    base = (unsigned long)page_address(factory.pages);
    if (address < base || address - base >= LSF_BACKING_BYTES)
        goto out;
    result = -EIO; /* Unknown bank pools are never ordinary attribute matches. */
    if (factory.device) {
        source = (struct lsf_cleanup_task_source){factory.device->key, factory.device->root,
            factory.device->cleanup_request, factory.device->cleanup_task};
        if (lsf_cleanup_provider_part_locked(source, LSF_PROVIDER_POOL, candidate, 1))
            result = 1;
    }
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
