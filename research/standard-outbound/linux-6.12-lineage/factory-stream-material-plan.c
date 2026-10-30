/* SPDX-License-Identifier: GPL-2.0-only */
/* UNSELECTED source. Include after stream RX state and original factory helpers.
 * This is the reservation/consumption primitive, NOT the complete ancestor
 * producer. Its immutable rows must come from the selected allocating TUs'
 * actual types and closed constructor paths. No helper below sets ANCESTORS.
 * Missing typed families must keep that bit clear and installation unavailable.
 * Every view, its parent and its phase use the ORIGINAL fixed record array.
 */

/* PRIVATE/PUBLISHED already mean real constructor ownership/publication.
 * RESERVED means prepaid storage which no constructor has yet consumed. */
enum { LSF_STREAM_MATERIAL_RESERVED = 3u };
static_assert(LSF_STREAM_MATERIAL_RESERVED != LSF_PREPAID_PRIVATE);
static_assert(LSF_STREAM_MATERIAL_RESERVED != LSF_PREPAID_PUBLISHED);
static_assert(LSF_STREAM_MATERIAL_RESERVED != LSF_PREPAID_QUEUED);

struct lsf_stream_material_row {
    u64 bytes, alignment;
    unsigned int kind;
    /* Zero is original Root, otherwise one plus an EARLIER row index. */
    unsigned int parent;
};

/* One small, paid Root child, not a second allocation/return table. The range
 * locates authoritative original records by their nonwrapping generations. */
struct lsf_stream_material_plan {
    struct lsf_prepaid_key owner;
    struct lsf_prepaid_ticket root, self;
    u64 first, end;
    unsigned int rows, consumed, sealed;
};

/* The first two real device births are visible in this actual factory TU.
 * These are a typed PREFIX only. Private transport/netdev, core/kernfs/name,
 * security and every other future allocation still need their own producers
 * and consumption sites before an ancestor producer can claim completeness. */
static int lsf_stream_material_device_prefix(struct lsf_stream_material_row rows[2])
{
    if (!rows || __alignof__(struct pci_dev) > 64u ||
        __alignof__(struct lsf_factory_device_firmware) > 64u)
        return -EOPNOTSUPP;
    rows[0] = (struct lsf_stream_material_row){
        .bytes = sizeof(struct pci_dev), .alignment = 64u,
        .kind = LSF_DEVICE_PCI, .parent = 0u
    };
    rows[1] = (struct lsf_stream_material_row){
        .bytes = sizeof(struct lsf_factory_device_firmware), .alignment = 64u,
        .kind = LSF_DEVICE_ACPI_REFERENCE, .parent = 1u
    };
    return 0;
}

static struct lsf_prepaid_view *lsf_stream_material_record_locked(
    struct lsf_prepaid_key owner, u64 generation, struct lsf_prepaid_ticket *ticket)
{
    struct lsf_prepaid_view *found = NULL;
    unsigned int i;
    lockdep_assert_held(&pool_lock);
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        struct lsf_prepaid_view *record = &factory.pool.records[i];
        if (record->generation != generation) continue;
        if (found || record->owner != owner.slot ||
            record->owner_generation != owner.generation ||
            (record->phase != LSF_PREPAID_LIVE && record->phase != LSF_PREPAID_RETURNED) ||
            !lsf_device_kind(record->kind) || !record->bytes ||
            record->offset < LSF_FACTORY_INFRA_OFFSET ||
            record->offset - LSF_FACTORY_INFRA_OFFSET > LSF_FACTORY_INFRA_BYTES ||
            record->bytes > LSF_FACTORY_INFRA_BYTES -
                (record->offset - LSF_FACTORY_INFRA_OFFSET))
            return NULL;
        found = record;
        *ticket = (struct lsf_prepaid_ticket){i, generation};
    }
    return found;
}

/* Classify a prior birth BEFORE dereferencing its payload. A pointer, range,
 * kind or copied generation alone cannot establish an owner. */
static struct lsf_stream_material_plan *lsf_stream_material_current_locked(
    const struct lsf_stream_material_plan *candidate)
{
    struct lsf_prepaid_view *record;
    struct lsf_stream_material_plan *plan;
    unsigned long base, at = (unsigned long)candidate;
    unsigned int i;
    u64 bytes = (sizeof(*plan) + 63ull) & ~63ull;
    lockdep_assert_held(&pool_lock);
    if (!factory.pages || !factory.device || !candidate ||
        !lsf_device_context(&factory.pool, factory.device->key))
        return NULL;
    base = (unsigned long)page_address(factory.pages);
    if (at < base || at - base >= LSF_BACKING_BYTES) return NULL;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->offset != at - base) continue;
        if (record->bytes != bytes || record->kind != LSF_DEVICE_QUEUE ||
            record->deferred != LSF_PREPAID_PUBLISHED ||
            record->cache_bucket != factory.device->root.slot ||
            record->cache_anchor != factory.device->root.generation ||
            !lsf_device_record(&factory.pool, factory.device->key,
                (struct lsf_prepaid_ticket){i, record->generation}, LSF_DEVICE_QUEUE))
            return NULL;
        plan = (void *)at;
        if (plan->owner.slot != factory.device->key.slot ||
            plan->owner.generation != factory.device->key.generation ||
            plan->root.slot != factory.device->root.slot ||
            plan->root.generation != factory.device->root.generation ||
            plan->self.slot != i || plan->self.generation != record->generation ||
            !plan->rows || plan->rows >= LSF_ALLOCATION_SLOTS - 1u ||
            record->generation == U64_MAX || plan->first != record->generation + 1u ||
            plan->first > U64_MAX - plan->rows ||
            plan->end != plan->first + plan->rows ||
            plan->consumed > plan->rows || plan->sealed > 1u)
            return NULL;
        return plan;
    }
    return NULL;
}

/* Caller holds both original locks, BEFORE normal PCI construction. Whole
 * byte/padding/record/generation preflight precedes the first new birth. The
 * row list is private compiled geometry, never a userspace cost certificate.
 * This primitive deliberately cannot certify that the row list is complete. */
static int lsf_stream_material_prepare_locked(const struct lsf_stream_material_row *rows,
    unsigned int count, struct lsf_stream_material_plan **output)
{
    struct lsf_prepaid_context *owner;
    struct lsf_stream_material_plan *plan;
    struct lsf_prepaid_ticket self, ticket, parent;
    u64 bytes = (sizeof(*plan) + 63ull) & ~63ull, offset, expected, first;
    unsigned int i, empty = 0;
    lockdep_assert_held(&factory_lock);
    lockdep_assert_held(&pool_lock);
    if (!output) return -EINVAL;
    *output = NULL;
    if (!rows || !count || count >= LSF_ALLOCATION_SLOTS - 1u ||
        !lsf_factory_selected_consumer() || !factory.pages || !factory.device ||
        lsf_stream_rx || factory.device->pci_attempted || factory.pool.stopped ||
        factory.pool.poisoned || READ_ONCE(factory.uncertain))
        return -EOPNOTSUPP;
    owner = lsf_device_context(&factory.pool, factory.device->key);
    if (!owner || owner->closed || !lsf_device_record(&factory.pool,
            factory.device->key, factory.device->root, LSF_DEVICE_ROOT))
        return -EPERM;
    expected = owner->cursor;
    if (!lsf_stream_geometry_add(&expected, bytes, 1, 64)) return -ENOBUFS;
    for (i = 0; i < count; ++i) {
        if (!lsf_device_kind(rows[i].kind) || rows[i].kind == LSF_DEVICE_ROOT ||
            rows[i].parent > i ||
            (rows[i].alignment != 64u && rows[i].alignment != 4096u) ||
            LSF_FACTORY_INFRA_OFFSET % rows[i].alignment ||
            !lsf_stream_geometry_add(&expected, rows[i].bytes, 1, rows[i].alignment))
            return -EOPNOTSUPP;
    }
    if (expected > LSF_FACTORY_INFRA_BYTES || !factory.pool.next_generation ||
        factory.pool.next_generation > U64_MAX - count - 1u)
        return -ENOBUFS;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        const struct lsf_prepaid_view *record = &factory.pool.records[i];
        empty += record->phase == LSF_PREPAID_EMPTY;
        /* No retry or reinterpretation of a previous plan/RX state child. */
        if (record->phase == LSF_PREPAID_LIVE && record->kind == LSF_DEVICE_QUEUE &&
            record->owner == factory.device->key.slot &&
            record->owner_generation == factory.device->key.generation &&
            record->cache_bucket == factory.device->root.slot &&
            record->cache_anchor == factory.device->root.generation)
            return -EALREADY;
    }
    if (empty < count + 1u) return -ENOBUFS;
    if (!lsf_device_allocate_stream_aligned(&factory.pool, factory.device->key,
            bytes, LSF_DEVICE_QUEUE, factory.device->root, &self, 64, &offset))
        goto poison;
    plan = (void *)((char *)page_address(factory.pages) + offset);
    memset(plan, 0, sizeof(*plan));
    first = factory.pool.next_generation;
    plan->owner = factory.device->key; plan->root = factory.device->root;
    plan->self = self; plan->first = first; plan->end = first + count; plan->rows = count;
    for (i = 0; i < count; ++i) {
        parent = plan->root;
        if (rows[i].parent && !lsf_stream_material_record_locked(plan->owner,
                first + rows[i].parent - 1u, &parent)) goto poison;
        if (!lsf_device_allocate_stream_aligned(&factory.pool, plan->owner,
                rows[i].bytes, rows[i].kind, parent, &ticket, rows[i].alignment, &offset) ||
            ticket.generation != first + i)
            goto poison;
        factory.pool.records[ticket.slot].deferred = LSF_STREAM_MATERIAL_RESERVED;
    }
    if (owner->cursor != expected || factory.pool.next_generation != plan->end ||
        !lsf_device_publish(&factory.pool, plan->owner, self, LSF_DEVICE_QUEUE))
        goto poison;
    *output = plan;
    return 0; /* Views prepaid; no constructor, DMA, fit or full-plan claim. */
poison:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
    return -EIO; /* Keep every partial view and SAME original physical bank. */
}

/* Only the original fenced constructor can consume a prepaid future birth.
 * Exactly one RESERVED record becomes PRIVATE; original initialization and
 * publication then run unchanged. No allocation, cursor movement or fallback. */
static int lsf_stream_material_take_locked(struct lsf_stream_material_plan *candidate,
    unsigned int kind, struct lsf_prepaid_ticket parent, unsigned long bytes,
    unsigned long alignment, struct lsf_prepaid_ticket *ticket, u64 *offset)
{
    struct lsf_stream_material_plan *plan = lsf_stream_material_current_locked(candidate);
    struct lsf_prepaid_view *record, *parent_record;
    struct lsf_prepaid_ticket actual;
    u64 generation, rounded;
    lockdep_assert_held(&pool_lock);
    if (!plan || plan->sealed || !ticket || !offset || !bytes || bytes > U64_MAX - 63u ||
        !alignment || alignment > 4096u || (alignment & (alignment - 1u)) ||
        !lsf_device_kind(kind) || kind == LSF_DEVICE_ROOT || factory.pool.stopped ||
        READ_ONCE(factory.uncertain) || !factory.device->constructor_active ||
        factory.device->constructor_task != current || current->mm != factory.mm ||
        current_cred() != factory.cred || task_tgid(current) != factory.tgid ||
        !current->nsproxy || current->nsproxy->net_ns != factory.net ||
        !parent.slot || parent.slot >= LSF_ALLOCATION_SLOTS)
        return -EPERM;
    parent_record = lsf_device_record(&factory.pool, plan->owner, parent,
        factory.pool.records[parent.slot].kind);
    if (!parent_record || parent_record->deferred == LSF_STREAM_MATERIAL_RESERVED)
        return -EPERM; /* A future parent is not an initialized constructor. */
    rounded = ((u64)bytes + 63u) & ~63ull;
    for (generation = plan->first; generation < plan->end; ++generation) {
        record = lsf_stream_material_record_locked(plan->owner, generation, &actual);
        if (!record) return -EIO;
        if (record->phase != LSF_PREPAID_LIVE ||
            record->deferred != LSF_STREAM_MATERIAL_RESERVED || record->kind != kind ||
            record->bytes != rounded || record->offset % alignment ||
            record->cache_bucket != parent.slot ||
            record->cache_anchor != parent.generation)
            continue;
        if (plan->consumed == plan->rows) return -EIO;
        record->deferred = LSF_PREPAID_PRIVATE;
        ++plan->consumed;
        *ticket = actual; *offset = record->offset;
        return 1;
    }
    return -ENOBUFS; /* Never allocate or adopt a replacement constructor view. */
}

/* Construction-only unused views can retire AFTER the actual constructor
 * fence and admission close. This does not certify callback/RCU/device tails;
 * claimed rows still require their original actual return sites. */
static int lsf_stream_material_seal_unused_locked(struct lsf_stream_material_plan *candidate)
{
    struct lsf_stream_material_plan *plan = lsf_stream_material_current_locked(candidate);
    struct lsf_prepaid_view *record;
    struct lsf_prepaid_ticket ticket;
    u64 generation;
    lockdep_assert_held(&factory_lock);
    lockdep_assert_held(&pool_lock);
    if (!plan || factory.device->constructor_active || factory.device->constructor_task ||
        factory.device->bootstrap_busy || factory.inflight || factory.reply_pending ||
        factory.device->bootstrap_state != LSF_FACTORY_BOOTSTRAP_CLOSED)
        return 0;
    plan->sealed = 1;
    /* Reverse original birth order: never return a reserved parent first. */
    for (generation = plan->end; generation-- > plan->first;) {
        record = lsf_stream_material_record_locked(plan->owner, generation, &ticket);
        if (!record) goto poison;
        if (record->phase == LSF_PREPAID_RETURNED ||
            record->deferred != LSF_STREAM_MATERIAL_RESERVED) continue;
        record->deferred = LSF_PREPAID_PRIVATE;
        if (!lsf_device_finish(&factory.pool, plan->owner, ticket, record->kind)) goto poison;
    }
    return 1; /* Original bank remains wholly paid and physically held. */
poison:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
    return 0;
}

/* No payload access or published alias may remain after the metadata view
 * returns. Every claimed row must already have its real original return. */
static int lsf_stream_material_finish_locked(struct lsf_stream_material_plan **link)
{
    struct lsf_stream_material_plan *plan;
    struct lsf_prepaid_key owner;
    struct lsf_prepaid_ticket ticket, self;
    struct lsf_prepaid_view *record;
    u64 generation;
    lockdep_assert_held(&factory_lock);
    lockdep_assert_held(&pool_lock);
    if (!link || !(plan = lsf_stream_material_current_locked(*link)) || !plan->sealed)
        return 0;
    for (generation = plan->first; generation < plan->end; ++generation) {
        record = lsf_stream_material_record_locked(plan->owner, generation, &ticket);
        if (!record || record->phase != LSF_PREPAID_RETURNED) return 0;
    }
    owner = plan->owner; self = plan->self;
    *link = NULL;
    if (!lsf_device_queue(&factory.pool, owner, self, LSF_DEVICE_QUEUE) ||
        !lsf_device_finish(&factory.pool, owner, self, LSF_DEVICE_QUEUE)) {
        *link = plan;
        factory.pool.poisoned = 1;
        WRITE_ONCE(factory.uncertain, 1);
        return 0;
    }
    return 1; /* Metadata VIEW only, never physical backing or native credit. */
}
