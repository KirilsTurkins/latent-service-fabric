/* SPDX-License-Identifier: GPL-2.0-only */
/* Original Root bank/records only. Included after the original Q35 factory. */
#include <net/lsf_stream_msi_descriptor_private.h>

static unsigned int lsf_msi_store_kind(unsigned int role)
{
    return role < LSF_MSI_STORE_PARTS ? LSF_MSI_DESC_KIND + role : 0;
}

static int lsf_msi_store_geometry(unsigned int role, unsigned long *bytes,
    unsigned long *alignment)
{
    return role == LSF_MSI_NODE_ROLE ? lsf_msi_node_geometry(bytes, alignment) :
        role < LSF_MSI_NODE_ROLE ? lsf_msi_desc_geometry(bytes, alignment) : -EOPNOTSUPP;
}

/* Context identity is captured at birth, never recovered from node->array.
 * First descriptor records link to the original context envelope. Its sibling
 * descriptor/node records link to that first record. All retain the same PCI
 * parent directly, so native context cleanup may finish before an RCU callback;
 * all physical bytes still belong to the unreturned Root bank. */
static struct lsf_prepaid_view *lsf_msi_store_record_locked(const void *value,
    unsigned int role, struct device **actual, struct lsf_prepaid_ticket *ticket)
{
    struct lsf_prepaid_view *record, *first, *context, *pci;
    unsigned long base, at = (unsigned long)value, bytes, alignment, offset;
    unsigned int i;
    lockdep_assert_held(&pool_lock);
    if (!factory.pages || !factory.device || !value || role > LSF_MSI_ANY_DESC_ROLE)
        return NULL;
    base = (unsigned long)page_address(factory.pages);
    if (at < base || at - base >= LSF_BACKING_BYTES) return NULL;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->offset != at - base) continue;
        if (role == LSF_MSI_ANY_DESC_ROLE) {
            if (record->kind < LSF_MSI_DESC_KIND ||
                record->kind >= LSF_MSI_DESC_KIND + LSF_MSI_NODE_ROLE) return NULL;
            role = record->kind - LSF_MSI_DESC_KIND;
        }
        if (lsf_msi_store_geometry(role, &bytes, &alignment)) return NULL;
        if (record->kind != lsf_msi_store_kind(role) ||
            lsf_device_record(&factory.pool, factory.device->key,
                (struct lsf_prepaid_ticket){i, record->generation}, record->kind) != record ||
            record->deferred != LSF_PREPAID_PUBLISHED ||
            record->bytes != ((bytes + 63u) & ~63ul) ||
            record->offset % alignment || record->bytes > LSF_BACKING_BYTES ||
            record->offset > LSF_BACKING_BYTES - record->bytes) return NULL;
        first = record;
        if (role) {
            if (!record->security_cache_location ||
                record->security_cache_location >= LSF_ALLOCATION_SLOTS) return NULL;
            first = &factory.pool.records[record->security_cache_location];
            if (first->generation != record->security_cache_identity ||
                first->kind != lsf_msi_store_kind(0)) return NULL;
        }
        if ((first->phase != LSF_PREPAID_LIVE && first->phase != LSF_PREPAID_RETURNED) ||
            first->owner != record->owner || first->owner_generation != record->owner_generation ||
            first->cache_bucket != record->cache_bucket || first->cache_anchor != record->cache_anchor ||
            !first->security_cache_location ||
            first->security_cache_location >= LSF_ALLOCATION_SLOTS) return NULL;
        context = &factory.pool.records[first->security_cache_location];
        if (context->generation != first->security_cache_identity ||
            context->kind != LSF_STREAM_MSI_CONTEXT_DR ||
            (context->phase != LSF_PREPAID_LIVE && context->phase != LSF_PREPAID_RETURNED) ||
            context->owner != record->owner || context->owner_generation != record->owner_generation ||
            context->cache_bucket != record->cache_bucket || context->cache_anchor != record->cache_anchor ||
            lsf_prepaid_stream_msi_devres_geometry(LSF_STREAM_MSI_CONTEXT,
                &bytes, &alignment, &offset) || context->bytes != ((bytes + 63u) & ~63ul)) return NULL;
        pci = lsf_device_record(&factory.pool, factory.device->key,
            (struct lsf_prepaid_ticket){record->cache_bucket, record->cache_anchor}, LSF_DEVICE_PCI);
        if (!pci || pci->bytes < sizeof(struct pci_dev) ||
            pci->offset > LSF_BACKING_BYTES - sizeof(struct pci_dev) ||
            (pci->deferred != LSF_PREPAID_PUBLISHED && pci->deferred != LSF_PREPAID_QUEUED)) return NULL;
        *actual = &((struct pci_dev *)(base + pci->offset))->dev;
        *ticket = (struct lsf_prepaid_ticket){i, record->generation};
        return record;
    }
    return NULL;
}

/* Only exact embedded store addresses in a paid complete context are selected.
 * No context payload is read merely because an address lies in the Root bank. */
static struct lsf_prepaid_view *lsf_msi_store_context_locked(const struct xarray *xa,
    struct device **actual, struct lsf_prepaid_ticket *ticket)
{
    unsigned long bytes, alignment, data_offset, base, at = (unsigned long)xa, store_offset;
    struct lsf_prepaid_view *context;
    unsigned int role;
    if (!factory.pages || lsf_prepaid_stream_msi_devres_geometry(LSF_STREAM_MSI_CONTEXT,
        &bytes, &alignment, &data_offset)) return NULL;
    base = (unsigned long)page_address(factory.pages);
    store_offset = lsf_msi_store_offset();
    if (at < base || at - base >= LSF_BACKING_BYTES || data_offset > at - base ||
        store_offset > at - base - data_offset) return NULL;
    context = lsf_stream_msi_envelope_locked((const void *)(at - data_offset -
        store_offset), NULL, actual, &role, ticket);
    return context && role == LSF_STREAM_MSI_CONTEXT ? context : NULL;
}

static struct lsf_prepaid_view *lsf_msi_store_first_locked(struct lsf_prepaid_ticket pci,
    struct lsf_prepaid_ticket context, unsigned int *attempts)
{
    struct lsf_prepaid_view *record, *latest = NULL;
    unsigned int i;
    *attempts = 0;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->kind != lsf_msi_store_kind(0) || record->cache_bucket != pci.slot ||
            record->cache_anchor != pci.generation || record->security_cache_location != context.slot ||
            record->security_cache_identity != context.generation ||
            record->owner != factory.device->key.slot ||
            record->owner_generation != factory.device->key.generation) continue;
        ++*attempts;
        if (!latest || record->generation > latest->generation) latest = record;
    }
    return latest;
}

int lsf_msi_store_prepare(struct device *dev, unsigned int nvec, struct lsf_msi_store_plan *plan)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_ticket pci, context_ticket, ticket;
    struct lsf_prepaid_view *context, *latest;
    struct device *actual;
    unsigned long bytes[4], align[4], flags;
    unsigned int role, attempts;
    u64 offset;
    int result = -EOPNOTSUPP;
    if (!plan || (nvec != 2u && nvec != 3u)) return result;
    *plan = (struct lsf_msi_store_plan){};
    for (role = 0; role < 4; ++role)
        if (lsf_msi_store_geometry(role, &bytes[role], &align[role])) return result;
    spin_lock_irqsave(&pool_lock, flags);
    if (lsf_stream_msi_parent_locked(dev, &state, &pci) != 1 ||
        !lsf_stream_bind_current_locked(state) || !dev->msi.data) goto out;
    context = lsf_msi_store_context_locked((const void *)((const char *)dev->msi.data +
        lsf_msi_store_offset()), &actual, &context_ticket);
    if (!context || actual != dev) goto out;
    latest = lsf_msi_store_first_locked(pci, context_ticket, &attempts);
    if (attempts >= 3u || nvec != (attempts == 2u ? 2u : 3u) ||
        (latest && latest->phase != LSF_PREPAID_RETURNED)) goto out;
    for (role = 1; role < LSF_ALLOCATION_SLOTS; ++role) {
        struct lsf_prepaid_view *prior = &factory.pool.records[role];
        if (prior->kind >= LSF_MSI_DESC_KIND && prior->kind < LSF_MSI_DESC_KIND + 3u &&
            prior->phase == LSF_PREPAID_LIVE && prior->cache_bucket == pci.slot &&
            prior->cache_anchor == pci.generation) goto out;
    }
    /* Aggregate admission is complete before the first native descriptor/node
     * is constructed. Even failed PRIVATE reservations never rewind cursor. */
    for (role = 0; role < 4; ++role) {
        if (role == 2u && nvec == 2u) continue;
        result = lsf_stream_constructor_allocate_locked(state, lsf_msi_store_kind(role), pci,
            bytes[role], align[role], &ticket, &offset);
        if (result != 1) goto discard;
        plan->slot[role] = ticket.slot; plan->generation[role] = ticket.generation;
        factory.pool.records[ticket.slot].security_cache_location =
            role ? plan->slot[0] : context_ticket.slot;
        factory.pool.records[ticket.slot].security_cache_identity =
            role ? plan->generation[0] : context_ticket.generation;
    }
    plan->nvec = nvec; result = 1; goto out;
discard:
    for (role = 0; role < 4; ++role)
        if (plan->slot[role] && !lsf_device_finish(&factory.pool, state->owner,
            (struct lsf_prepaid_ticket){plan->slot[role], plan->generation[role]},
            lsf_msi_store_kind(role))) {
            factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1);
        }
    *plan = (struct lsf_msi_store_plan){};
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void *lsf_msi_store_take(struct device *dev, unsigned int role)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_ticket pci, ctx;
    struct lsf_prepaid_view *context, *first, *record, *found = NULL;
    struct device *actual;
    unsigned int i, attempts, matches = 0;
    unsigned long flags, bytes, alignment;
    void *value = NULL;
    if (role >= 4u || lsf_msi_store_geometry(role, &bytes, &alignment)) return NULL;
    spin_lock_irqsave(&pool_lock, flags);
    if (lsf_stream_msi_parent_locked(dev, &state, &pci) != 1 ||
        !lsf_stream_bind_current_locked(state) || !dev->msi.data) goto out;
    context = lsf_msi_store_context_locked((const void *)((const char *)dev->msi.data +
        lsf_msi_store_offset()), &actual, &ctx);
    if (!context || actual != dev) goto out;
    first = lsf_msi_store_first_locked(pci, ctx, &attempts);
    if (!first || first->phase != LSF_PREPAID_LIVE || !attempts || attempts > 3u) goto out;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->kind != lsf_msi_store_kind(role) || record->phase != LSF_PREPAID_LIVE ||
            record->cache_bucket != pci.slot || record->cache_anchor != pci.generation ||
            record->owner != state->owner.slot || record->owner_generation != state->owner.generation ||
            (role ? record->security_cache_location != (unsigned int)(first - factory.pool.records) ||
                record->security_cache_identity != first->generation : record != first)) continue;
        ++matches; found = record;
    }
    if (matches != 1u || !found || found->deferred != LSF_PREPAID_PRIVATE ||
        found->bytes != ((bytes + 63u) & ~63ul) || found->offset % alignment ||
        found->bytes > LSF_BACKING_BYTES || found->offset > LSF_BACKING_BYTES - found->bytes ||
        !lsf_device_publish(&factory.pool, state->owner,
            (struct lsf_prepaid_ticket){(unsigned int)(found - factory.pool.records), found->generation},
            found->kind)) goto out;
    value = (char *)page_address(factory.pages) + found->offset;
    memset(value, 0, found->bytes);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return value;
}

int lsf_msi_store_classify(const void *value, unsigned int role, struct device **actual)
{
    struct lsf_prepaid_ticket ticket;
    unsigned long flags;
    int result = 0;
    if (!actual) return -EINVAL;
    *actual = NULL;
    if (!READ_ONCE(factory.pages)) return 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (lsf_stream_rx_address_locked(value)) {
        result = lsf_msi_store_record_locked(value, role, actual, &ticket) ? 1 : -EOPNOTSUPP;
        if (result < 0) { factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1); }
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_msi_store_xa_selected(const struct xarray *xa)
{
    struct lsf_prepaid_ticket context;
    struct device *actual;
    unsigned long flags;
    int result = 0;
    if (!READ_ONCE(factory.pages)) return 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (lsf_stream_rx_address_locked(xa)) {
        result = lsf_msi_store_context_locked(xa, &actual, &context) ? 1 : -EOPNOTSUPP;
        if (result < 0) { factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1); }
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_msi_store_radix_selected(const void *value)
{
    struct lsf_prepaid_ticket ticket;
    struct lsf_prepaid_view *record;
    struct device *actual;
    unsigned long flags, base, at = (unsigned long)value;
    unsigned int i;
    int result = 0;
    if (!READ_ONCE(factory.pages)) return 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_stream_rx_address_locked(value)) goto out;
    result = -EOPNOTSUPP;
    base = (unsigned long)page_address(factory.pages);
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->offset != at - base) continue;
        /* These are routing discriminators ONLY. All historical PID/IDR
         * guards and native cleanup remain in the untouched old callback. */
        if (record->kind == LSF_DEVICE_CLEANUP_PID_RADIX ||
            record->kind == LSF_DEVICE_IDR_NODE ||
            record->kind == LSF_DEVICE_STREAM_CLASSDIR_IDR ||
            record->kind == LSF_DEVICE_STREAM_NETDEV_DIRECTORY_IDR) result = 0;
        else if (record->kind == lsf_msi_store_kind(LSF_MSI_NODE_ROLE) &&
            lsf_msi_store_record_locked(value, LSF_MSI_NODE_ROLE, &actual, &ticket)) result = 1;
        break;
    }
    if (result < 0) { factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1); }
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

struct xa_node *lsf_msi_store_node_take(const struct xarray *xa)
{
    struct lsf_prepaid_ticket context;
    struct device *actual = NULL;
    unsigned long flags;
    spin_lock_irqsave(&pool_lock, flags);
    (void)lsf_msi_store_context_locked(xa, &actual, &context);
    spin_unlock_irqrestore(&pool_lock, flags);
    return actual ? lsf_msi_store_take(actual, LSF_MSI_NODE_ROLE) : NULL;
}

int lsf_msi_store_node_for(const void *value, const struct xarray *xa)
{
    struct lsf_prepaid_ticket context, node;
    struct device *actual = NULL, *expected = NULL;
    struct lsf_prepaid_view *record, *ctx, *first, *latest;
    unsigned int attempts;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    ctx = lsf_msi_store_context_locked(xa, &expected, &context);
    record = lsf_msi_store_record_locked(value, LSF_MSI_NODE_ROLE, &actual, &node);
    if (ctx && record && actual == expected) {
        first = &factory.pool.records[record->security_cache_location];
        latest = lsf_msi_store_first_locked(
            (struct lsf_prepaid_ticket){record->cache_bucket, record->cache_anchor},
            context, &attempts);
        /* Consumption/unused-preallocation cleanup is synchronous under the
         * native MSI descriptor mutex. It must belong to this current attempt;
         * late published-node RCU cleanup uses record_locked, NOT this gate. */
        result = first->phase == LSF_PREPAID_LIVE && latest == first &&
            latest->generation == record->security_cache_identity &&
            attempts && attempts <= 3u && first->security_cache_location == context.slot &&
            first->security_cache_identity == context.generation;
    }
    if (!result) { factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1); }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_msi_store_retire(const void *value, unsigned int role)
{
    struct lsf_prepaid_ticket ticket;
    struct device *actual;
    struct lsf_prepaid_view *record;
    unsigned long flags;
    int result = -EOPNOTSUPP;
    spin_lock_irqsave(&pool_lock, flags);
    record = lsf_msi_store_record_locked(value, role, &actual, &ticket);
    if (record && lsf_device_queue(&factory.pool, factory.device->key, ticket, record->kind) &&
        lsf_device_finish(&factory.pool, factory.device->key, ticket, record->kind)) result = 1;
    else { factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1); }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void lsf_msi_store_discard(struct device *dev, struct lsf_msi_store_plan *plan)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_ticket pci, ticket;
    struct lsf_prepaid_view *record;
    unsigned int role;
    unsigned long flags;
    if (!plan) return;
    spin_lock_irqsave(&pool_lock, flags);
    if (lsf_stream_msi_parent_locked(dev, &state, &pci) != 1 ||
        (plan->nvec != 2u && plan->nvec != 3u) || !plan->slot[0] ||
        !plan->slot[1] || !plan->slot[3] ||
        (!!plan->slot[2] != (plan->nvec == 3u))) goto poison;
    for (role = 0; role < 4; ++role) {
        if (!plan->slot[role]) continue;
        ticket = (struct lsf_prepaid_ticket){plan->slot[role], plan->generation[role]};
        if (ticket.slot >= LSF_ALLOCATION_SLOTS) goto poison;
        record = &factory.pool.records[ticket.slot];
        if (record->generation != ticket.generation || record->kind != lsf_msi_store_kind(role) ||
            record->owner != state->owner.slot || record->owner_generation != state->owner.generation ||
            record->cache_bucket != pci.slot || record->cache_anchor != pci.generation ||
            (role && (record->security_cache_location != plan->slot[0] ||
                record->security_cache_identity != plan->generation[0]))) goto poison;
        if (record->phase == LSF_PREPAID_RETURNED) continue;
        if (record->phase != LSF_PREPAID_LIVE) goto poison;
        if (record->deferred == LSF_PREPAID_PRIVATE &&
            !lsf_device_finish(&factory.pool, state->owner, ticket, record->kind)) goto poison;
        /* Published nodes remain owned until the actual native RCU callback. */
    }
    goto out;
poison:
    factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1);
out:
    *plan = (struct lsf_msi_store_plan){};
    spin_unlock_irqrestore(&pool_lock, flags);
}
