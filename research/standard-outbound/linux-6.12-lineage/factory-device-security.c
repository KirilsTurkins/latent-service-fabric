/* SPDX-License-Identifier: GPL-2.0-only */
/* Uninstalled tagged-owner branch. Included only after the actual device work
 * helpers. The generic entry points must dispatch this closed domain before
 * legacy application lookup/allocation; these helpers alone install nothing. */
#define LSF_DEVICE_SECURITY_DELEGATE 2
static_assert(LSF_DEVICE_AVC_NODE == LSF_DEVICE_SECURITY_AVC_NODE);
static_assert(LSF_DEVICE_AVC_XPERMS == LSF_DEVICE_SECURITY_AVC_XPERMS);
static_assert(LSF_DEVICE_AVC_DECISION == LSF_DEVICE_SECURITY_AVC_DECISION);
static_assert(LSF_DEVICE_AVC_DATA == LSF_DEVICE_SECURITY_AVC_DATA);
static_assert(LSF_DEVICE_SIDCACHE == LSF_DEVICE_SECURITY_SIDCACHE);
static_assert(LSF_DEVICE_AUDIT_STRING == LSF_DEVICE_SECURITY_AUDIT_STRING);
static_assert(LSF_DEVICE_AUDIT_BUFFER == LSF_DEVICE_SECURITY_AUDIT_BUFFER);
static_assert(LSF_DEVICE_AUDIT_SKB == LSF_DEVICE_SECURITY_AUDIT_SKB);
static_assert(LSF_DEVICE_AUDIT_HEAD == LSF_DEVICE_SECURITY_AUDIT_HEAD);
static struct lsf_factory_context *lsf_factory_context_current(struct lsf_factory_context *);

/* A tagged graph error must never turn the device owner into a NULL legacy
 * context. Preserve the original application poison path; device or unknown
 * carrier shape conservatively fences the whole original private factory. */
void lsf_factory_blob_poison(struct lsf_factory_blob source)
{
    if (lsf_factory_blob_shape(source) && source.domain == LSF_FACTORY_OWNER_APPLICATION)
        lsf_factory_poison(source.context);
    else
        lsf_factory_device_uevent_poison();
}

static struct lsf_prepaid_view *lsf_factory_device_security_record_locked(
    struct lsf_factory_blob source)
{
    struct lsf_prepaid_view *record;
    struct lsf_factory_device_firmware *owned;
    if (!factory.pages || !factory.device || source.domain != LSF_FACTORY_OWNER_DEVICE ||
        !lsf_factory_blob_shape(source))
        return NULL;
    record = lsf_device_security_record(&factory.pool, factory.device->key, source.device);
    if (!record || (char *)page_address(factory.pages) + record->offset != source.device.address ||
        !(owned = lsf_factory_device_registration_parent_locked(source.device)) ||
        !owned->core_initialized || owned->queued || owned->putting || owned->returned ||
        record->deferred > LSF_PREPAID_PUBLISHED)
        return NULL;
    if (source.device.kind == LSF_DEVICE_RECIPIENT_KIND_WORK &&
        !lsf_factory_device_recipient_current_locked(source.device, NULL))
        return NULL;
    return record;
}

/* Only this real current work source can enter the device-domain permission
 * chain. No NULL context cast, ordinary pointer or caller-supplied domain tag
 * mints a blob or creates a new original owner. */
int lsf_factory_device_recipient_blob(struct lsf_device_registration_source source,
    struct lsf_factory_blob *copy)
{
    unsigned long flags;
    int result = -1;
    spin_lock_irqsave(&pool_lock, flags);
    if (!copy || !lsf_factory_device_recipient_current_locked(source, NULL))
        goto poison;
    *copy = (struct lsf_factory_blob){
        .context = NULL, .ticket = {source.slot, source.generation},
        .domain = LSF_FACTORY_OWNER_DEVICE, .device = source,
    };
    result = 1;
    goto out;
poison:
    lsf_factory_device_firmware_poison();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Caller holds pool_lock. DELEGATE is private to the original dispatcher:
 * only a genuinely outside address or an original application-owned record
 * reaches its unchanged validation. Unknown device kinds/addresses never do. */
static int lsf_factory_device_security_lookup_locked(const void *address,
    unsigned int logical_kind, struct lsf_factory_blob *copy)
{
    struct lsf_prepaid_view *record;
    struct lsf_device_registration_source source;
    unsigned long base, value = (unsigned long)address;
    unsigned int i, physical_kind = lsf_device_security_physical_kind(logical_kind);
    if (!factory.pages)
        return LSF_DEVICE_SECURITY_DELEGATE;
    base = (unsigned long)page_address(factory.pages);
    if (value < base || value - base >= LSF_BACKING_BYTES)
        return LSF_DEVICE_SECURITY_DELEGATE;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->offset != value - base)
            continue;
        if (record->owner < LSF_FACTORY_CONTEXTS)
            return LSF_DEVICE_SECURITY_DELEGATE;
        if (!copy || !factory.device || !physical_kind || record->kind != physical_kind)
            goto poison;
        source = (struct lsf_device_registration_source){
            .address = address, .kind = physical_kind, .slot = i,
            .generation = record->generation, .pci_slot = record->cache_bucket,
            .pci_generation = record->cache_anchor,
        };
        *copy = (struct lsf_factory_blob){
            .context = NULL, .ticket = {i, record->generation},
            .domain = LSF_FACTORY_OWNER_DEVICE, .device = source,
        };
        if (!lsf_factory_device_security_record_locked(*copy))
            goto poison;
        return 1;
    }
poison:
    lsf_factory_device_firmware_poison();
    return -1;
}

static void *lsf_factory_device_security_allocate_locked(struct lsf_factory_blob source,
    unsigned long bytes, unsigned int logical_kind)
{
    struct lsf_prepaid_ticket parent = {source.device.pci_slot, source.device.pci_generation}, ticket;
    unsigned int kind = lsf_device_security_physical_kind(logical_kind);
    lsf_u64 offset;
    void *result;
    if (!kind || !bytes || bytes > LSF_FACTORY_INFRA_BYTES ||
        !lsf_factory_device_security_record_locked(source))
        goto poison;
    if (!lsf_device_allocate(&factory.pool, factory.device->key, bytes, kind,
            parent, &ticket, &offset))
        return NULL;
    result = (char *)page_address(factory.pages) + offset;
    memset(result, 0, bytes);
    /* The real cache/queue producer performs its own later publication. This
     * same-bank child is PRIVATE and retains the creator PCI in the meantime. */
    return result;
poison:
    lsf_factory_device_firmware_poison();
    return NULL;
}

static int lsf_factory_device_security_finish_locked(struct lsf_factory_blob source,
    unsigned int logical_kind)
{
    struct lsf_prepaid_view *record = lsf_factory_device_security_record_locked(source);
    unsigned int kind = lsf_device_security_physical_kind(logical_kind);
    if (!record || !kind || record->kind != kind ||
        !lsf_device_finish(&factory.pool, factory.device->key, source.ticket, kind)) {
        lsf_factory_device_firmware_poison();
        return 0;
    }
    return 1;
}

static int lsf_factory_device_security_phase_locked(struct lsf_factory_blob source,
    unsigned int phase)
{
    struct lsf_prepaid_view *record = lsf_factory_device_security_record_locked(source);
    if (!record || source.device.kind != LSF_DEVICE_SECURITY_AVC_NODE ||
        (phase != LSF_PREPAID_PRIVATE && phase != LSF_PREPAID_QUEUED) ||
        record->deferred != phase) {
        lsf_factory_device_firmware_poison();
        return 0;
    }
    return 1;
}

static int lsf_factory_device_security_publish_locked(struct lsf_factory_blob source,
    unsigned int location, lsf_u64 identity)
{
    if (!lsf_factory_device_security_record_locked(source) ||
        !lsf_device_security_publish(&factory.pool, factory.device->key,
            source.device, location, identity)) {
        lsf_factory_device_firmware_poison();
        return -1;
    }
    return 1;
}

static int lsf_factory_device_security_queue_locked(struct lsf_factory_blob source)
{
    if (!lsf_factory_device_security_record_locked(source) ||
        !lsf_device_security_queue(&factory.pool, factory.device->key, source.device)) {
        lsf_factory_device_firmware_poison();
        return -1;
    }
    return 1;
}

/* For mixed creator-domain AVC replacement. Validate both real records and
 * both original contexts completely BEFORE changing either publication. */
static struct lsf_prepaid_view *lsf_factory_security_avc_record_locked(
    struct lsf_factory_blob source, unsigned int phase, unsigned int bucket,
    struct lsf_prepaid_context **context)
{
    struct lsf_factory_context *application;
    struct lsf_prepaid_view *record;
    if (!context || !lsf_factory_blob_shape(source) || bucket >= 512u ||
        (phase != LSF_PREPAID_PRIVATE && phase != LSF_PREPAID_PUBLISHED))
        return NULL;
    if (source.domain == LSF_FACTORY_OWNER_DEVICE) {
        record = lsf_factory_device_security_record_locked(source);
        if (!record)
            return NULL;
        *context = lsf_device_context(&factory.pool, factory.device->key);
        if (source.device.kind != LSF_DEVICE_SECURITY_AVC_NODE ||
            record->deferred != phase || record->security_cache_location !=
            (phase == LSF_PREPAID_PRIVATE ? 0u : bucket + 1u))
            return NULL;
    } else {
        application = lsf_factory_context_current(source.context);
        if (!application || !lsf_prepaid_avc_node_valid(&factory.pool, application->key,
                source.ticket, phase, bucket))
            return NULL;
        record = &factory.pool.records[source.ticket.slot];
        if (record->security_cache_location || record->security_cache_identity)
            return NULL;
        *context = lsf_prepaid_context_for(&factory.pool, application->key);
    }
    return *context && (*context)->live ? record : NULL;
}

static int lsf_factory_security_avc_replace_locked(struct lsf_factory_blob source,
    const struct lsf_factory_blob *prior, unsigned int bucket)
{
    struct lsf_prepaid_context *next_context = NULL, *prior_context = NULL;
    struct lsf_prepaid_view *next, *old = NULL;
    next = lsf_factory_security_avc_record_locked(source, LSF_PREPAID_PRIVATE,
        bucket, &next_context);
    if (!next)
        goto poison;
    if (prior) {
        if (source.ticket.slot == prior->ticket.slot)
            goto poison;
        old = lsf_factory_security_avc_record_locked(*prior, LSF_PREPAID_PUBLISHED,
            bucket, &prior_context);
        if (!old || !prior_context || prior_context->continuations >= LSF_ALLOCATION_SLOTS)
            goto poison;
    }
    if (source.domain == LSF_FACTORY_OWNER_DEVICE)
        next->security_cache_location = bucket + 1u;
    else
        next->cache_bucket = bucket + 1u;
    next->deferred = LSF_PREPAID_PUBLISHED;
    if (old) {
        old->deferred = LSF_PREPAID_QUEUED;
        prior_context->continuations++;
    }
    return 1;
poison:
    lsf_factory_device_firmware_poison();
    return 0;
}

/* A drain candidate contains only scalar identities. In particular its address
 * is NULL: no stale cache pointer is saved across the original cache lock or
 * policy RCU acquisition. This is not a blob and cannot authorize allocation.
 * Caller holds pool_lock; both scans and revalidation use this same check. */
static struct lsf_prepaid_view *lsf_factory_device_security_drain_record_locked(
    unsigned int slot, unsigned int kind)
{
    struct lsf_prepaid_context *context;
    struct lsf_prepaid_view *record;
    struct lsf_prepaid_ticket ticket;
    if (!factory.pages || !factory.device || !slot || slot >= LSF_ALLOCATION_SLOTS ||
        (kind != LSF_DEVICE_SECURITY_AVC_NODE && kind != LSF_DEVICE_SECURITY_SIDCACHE))
        return NULL;
    context = lsf_device_context(&factory.pool, factory.device->key);
    if (!context || !context->closed)
        return NULL;
    record = &factory.pool.records[slot];
    ticket = (struct lsf_prepaid_ticket){slot, record->generation};
    if (record != lsf_device_record(&factory.pool, factory.device->key, ticket, kind) ||
        record->deferred != LSF_PREPAID_PUBLISHED)
        return NULL;
    if ((kind == LSF_DEVICE_SECURITY_AVC_NODE &&
         (!record->security_cache_location || record->security_cache_location > 512u ||
          record->security_cache_identity)) ||
        (kind == LSF_DEVICE_SECURITY_SIDCACHE &&
         (record->security_cache_location || !record->security_cache_identity))) {
        lsf_factory_device_firmware_poison();
        return NULL;
    }
    return record;
}

int lsf_factory_device_security_candidate(unsigned int slot, unsigned int kind,
    struct lsf_device_registration_source *candidate, unsigned int *location,
    lsf_u64 *identity)
{
    struct lsf_prepaid_view *record;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    record = lsf_factory_device_security_drain_record_locked(slot, kind);
    if (record && candidate && location && identity) {
        *candidate = (struct lsf_device_registration_source){
            .address = NULL, .kind = kind, .slot = slot,
            .generation = record->generation, .pci_slot = record->cache_bucket,
            .pci_generation = record->cache_anchor,
        };
        *location = record->security_cache_location;
        *identity = record->security_cache_identity;
        result = 1;
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Called only while the real AVC slot lock or SID table cache lock is held.
 * For SID, the caller must first match identity to the current policy's table
 * under RCU. No cached address is dereferenced before this locked check. A
 * stale candidate simply cannot witness the later current cache incarnation. */
int lsf_factory_device_security_current(struct lsf_device_registration_source candidate,
    unsigned int location, lsf_u64 identity, void **address)
{
    struct lsf_prepaid_view *record;
    struct lsf_factory_blob copy;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    record = lsf_factory_device_security_drain_record_locked(candidate.slot, candidate.kind);
    if (!record || !address || candidate.address ||
        record->generation != candidate.generation ||
        record->cache_bucket != candidate.pci_slot || record->cache_anchor != candidate.pci_generation ||
        record->security_cache_location != location || record->security_cache_identity != identity)
        goto out;
    copy = (struct lsf_factory_blob){
        .context = NULL, .ticket = {candidate.slot, candidate.generation},
        .domain = LSF_FACTORY_OWNER_DEVICE, .device = candidate,
    };
    copy.device.address = (char *)page_address(factory.pages) + record->offset;
    if (lsf_factory_device_security_record_locked(copy)) {
        *address = (void *)copy.device.address;
        result = 1;
    }
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
