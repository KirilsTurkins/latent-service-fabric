/* SPDX-License-Identifier: GPL-2.0-only */
/* Included AFTER the existing MSI context factory. No new ledger or backing. */
#include <net/lsf_stream_q35_msi_private.h>
static_assert(LSF_Q35_MSI_KIND > LSF_STREAM_MSI_GROUP_DR);

static unsigned int lsf_q35_kind(unsigned int role)
{
    return role < LSF_Q35_MSI_PARTS ? LSF_Q35_MSI_KIND + role : 0;
}

static struct lsf_prepaid_view *lsf_q35_record_locked(const void *address,
    unsigned int role, struct device **actual, struct lsf_prepaid_ticket *ticket)
{
    struct lsf_stream_rx_state *state = lsf_stream_rx_current_locked();
    struct lsf_prepaid_view *record, *pci, *first;
    unsigned long base, at = (unsigned long)address, bytes, alignment;
    unsigned int i;
    lockdep_assert_held(&pool_lock);
    if (!state || !factory.pages || !factory.device || !address ||
        !lsf_q35_kind(role) || lsf_q35_msi_geometry(role, 1u, 2u, &bytes, &alignment)) return NULL;
    base = (unsigned long)page_address(factory.pages);
    if (at < base || at - base >= LSF_BACKING_BYTES) return NULL;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->offset != at - base || record->kind != lsf_q35_kind(role)) continue;
        *ticket = (struct lsf_prepaid_ticket){i, record->generation};
        if (lsf_device_record(&factory.pool, state->owner, *ticket, record->kind) != record ||
            record->deferred != LSF_PREPAID_PUBLISHED ||
            record->bytes != ((bytes + 63u) & ~63ul) || record->bytes > LSF_BACKING_BYTES ||
            record->offset % alignment ||
            record->offset > LSF_BACKING_BYTES - record->bytes ||
            !record->security_cache_location ||
            record->security_cache_location >= LSF_ALLOCATION_SLOTS) return NULL;
        pci = lsf_device_record(&factory.pool, state->owner,
            (struct lsf_prepaid_ticket){record->cache_bucket, record->cache_anchor}, LSF_DEVICE_PCI);
        first = &factory.pool.records[record->security_cache_location];
        if (!pci || pci->bytes < sizeof(struct pci_dev) ||
            pci->offset > LSF_BACKING_BYTES - sizeof(struct pci_dev) ||
            (pci->deferred != LSF_PREPAID_PUBLISHED && pci->deferred != LSF_PREPAID_QUEUED) ||
            first->kind != lsf_q35_kind(LSF_Q35_MSI_TEMPLATE) ||
            first->generation != record->security_cache_identity ||
            first->owner != record->owner || first->owner_generation != record->owner_generation ||
            first->cache_bucket != record->cache_bucket || first->cache_anchor != record->cache_anchor ||
            (first->phase != LSF_PREPAID_LIVE && first->phase != LSF_PREPAID_RETURNED)) return NULL;
        *actual = &((struct pci_dev *)(base + pci->offset))->dev;
        return record;
    }
    return NULL;
}

int lsf_q35_msi_prepare(struct device *dev, unsigned long name_bytes,
    unsigned long token_bytes, struct lsf_q35_msi_plan *plan)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_ticket parent, ticket;
    unsigned long bytes[LSF_Q35_MSI_PARTS], align[LSF_Q35_MSI_PARTS], flags;
    u64 offset;
    unsigned int i, j;
    int result = -EOPNOTSUPP;
    if (!plan) return -EINVAL;
    *plan = (struct lsf_q35_msi_plan){};
    for (i = 0; i < LSF_Q35_MSI_PARTS; ++i)
        if (lsf_q35_msi_geometry(i, name_bytes, token_bytes, &bytes[i], &align[i])) return result;
    spin_lock_irqsave(&pool_lock, flags);
    if (lsf_stream_msi_parent_locked(dev, &state, &parent) != 1 ||
        !lsf_stream_bind_current_locked(state) || !dev->msi.data) goto out;
    for (i = 0; i < LSF_Q35_MSI_PARTS; ++i) {
        result = lsf_stream_constructor_allocate_locked(state, lsf_q35_kind(i), parent,
            bytes[i], align[i], &ticket, &offset);
        if (result != 1) {
            for (j = 0; j < i; ++j)
                if (!lsf_device_finish(&factory.pool, state->owner,
                    (struct lsf_prepaid_ticket){plan->slot[j], plan->generation[j]}, lsf_q35_kind(j))) {
                    factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1);
                }
            *plan = (struct lsf_q35_msi_plan){};
            goto out;
        }
        plan->slot[i] = ticket.slot; plan->generation[i] = ticket.generation;
    }
    for (i = 0; i < LSF_Q35_MSI_PARTS; ++i) {
        factory.pool.records[plan->slot[i]].security_cache_location = plan->slot[0];
        factory.pool.records[plan->slot[i]].security_cache_identity = plan->generation[0];
    }
    result = 1;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void *lsf_q35_msi_take(struct device *dev, const struct lsf_q35_msi_plan *plan, unsigned int role)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_ticket parent, ticket;
    struct lsf_prepaid_view *record;
    unsigned long flags;
    void *value = NULL;
    if (!plan || role >= LSF_Q35_MSI_PARTS || !plan->slot[0] ||
        !plan->slot[role] || plan->slot[role] >= LSF_ALLOCATION_SLOTS) return NULL;
    spin_lock_irqsave(&pool_lock, flags);
    if (lsf_stream_msi_parent_locked(dev, &state, &parent) != 1 ||
        !lsf_stream_bind_current_locked(state)) goto out;
    ticket = (struct lsf_prepaid_ticket){plan->slot[role], plan->generation[role]};
    record = lsf_device_record(&factory.pool, state->owner, ticket, lsf_q35_kind(role));
    if (!record || record->deferred != LSF_PREPAID_PRIVATE ||
        record->cache_bucket != parent.slot || record->cache_anchor != parent.generation ||
        record->security_cache_location != plan->slot[0] ||
        record->security_cache_identity != plan->generation[0]) goto out;
    if (!lsf_device_publish(&factory.pool, state->owner, ticket, record->kind)) goto out;
    value = (char *)page_address(factory.pages) + record->offset;
    memset(value, 0, record->bytes);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return value;
}

int lsf_q35_msi_classify(const void *value, unsigned int role, struct device **actual)
{
    struct lsf_prepaid_ticket ticket;
    unsigned long flags;
    int result = 0;
    if (!actual) return -EINVAL;
    *actual = NULL;
    if (!READ_ONCE(factory.pages)) return 0; /* Normal early x86 IRQ-domain boot. */
    spin_lock_irqsave(&pool_lock, flags);
    if (lsf_stream_rx_address_locked(value))
        result = lsf_q35_record_locked(value, role, actual, &ticket) ? 1 : -EOPNOTSUPP;
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void *lsf_q35_msi_sibling(const void *origin, unsigned int from, unsigned int role, int take)
{
    struct lsf_prepaid_view *record, *candidate, *selected = NULL;
    struct lsf_prepaid_ticket ticket;
    struct device *dev;
    unsigned long flags, bytes, alignment;
    unsigned int i, found = 0;
    void *value = NULL;
    if (role >= LSF_Q35_MSI_PARTS || (take != 0 && take != 1) ||
        lsf_q35_msi_geometry(role, 1u, 2u, &bytes, &alignment)) return NULL;
    spin_lock_irqsave(&pool_lock, flags);
    record = lsf_q35_record_locked(origin, from, &dev, &ticket);
    if (!record) goto out;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        candidate = &factory.pool.records[i];
        if (candidate->kind != lsf_q35_kind(role) || candidate->phase != LSF_PREPAID_LIVE ||
            candidate->owner != record->owner || candidate->owner_generation != record->owner_generation ||
            candidate->cache_bucket != record->cache_bucket || candidate->cache_anchor != record->cache_anchor ||
            candidate->security_cache_location != record->security_cache_location ||
            candidate->security_cache_identity != record->security_cache_identity) continue;
        ++found;
        selected = candidate;
        if (candidate->bytes != ((bytes + 63u) & ~63ul) || candidate->bytes > LSF_BACKING_BYTES ||
            candidate->offset > LSF_BACKING_BYTES - candidate->bytes || candidate->offset % alignment) {
            found = 2; selected = NULL; break;
        }
    }
    if (found != 1 || !selected) goto out;
    if (take) {
        if (selected->deferred != LSF_PREPAID_PRIVATE ||
            !lsf_device_publish(&factory.pool, factory.device->key,
                (struct lsf_prepaid_ticket){(unsigned int)(selected - factory.pool.records), selected->generation},
                selected->kind)) goto out;
    } else if (selected->deferred != LSF_PREPAID_PUBLISHED) goto out;
    value = (char *)page_address(factory.pages) + selected->offset;
    if (take) memset(value, 0, selected->bytes);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return value;
}

int lsf_q35_msi_retire(const void *value, unsigned int role)
{
    struct lsf_prepaid_view *record;
    struct lsf_prepaid_ticket ticket;
    struct device *actual;
    unsigned long flags;
    unsigned int i;
    int result = -EOPNOTSUPP;
    spin_lock_irqsave(&pool_lock, flags);
    record = lsf_q35_record_locked(value, role, &actual, &ticket);
    if (record && role == LSF_Q35_MSI_TEMPLATE)
        for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
            struct lsf_prepaid_view *child = &factory.pool.records[i];
            if (child != record && child->phase == LSF_PREPAID_LIVE &&
                child->deferred == LSF_PREPAID_PUBLISHED &&
                child->security_cache_location == ticket.slot &&
                child->security_cache_identity == ticket.generation) { record = NULL; break; }
        }
    if (record && lsf_device_queue(&factory.pool, factory.device->key, ticket, record->kind) &&
        lsf_device_finish(&factory.pool, factory.device->key, ticket, record->kind)) result = 1;
    else { factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1); }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void lsf_q35_msi_discard(struct device *dev, struct lsf_q35_msi_plan *plan)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_ticket parent, ticket;
    struct lsf_prepaid_view *record;
    struct lsf_q35_msi_plan saved;
    unsigned long flags;
    unsigned int i;
    if (!plan) return;
    saved = *plan; *plan = (struct lsf_q35_msi_plan){};
    spin_lock_irqsave(&pool_lock, flags);
    if (lsf_stream_msi_parent_locked(dev, &state, &parent) != 1) goto retain;
    for (i = 0; i < LSF_Q35_MSI_PARTS; ++i) {
        if (!saved.slot[i]) continue;
        if (saved.slot[i] >= LSF_ALLOCATION_SLOTS) goto retain;
        record = &factory.pool.records[saved.slot[i]];
        ticket = (struct lsf_prepaid_ticket){saved.slot[i], saved.generation[i]};
        if (record->generation != ticket.generation || record->kind != lsf_q35_kind(i) ||
            record->owner != state->owner.slot || record->owner_generation != state->owner.generation ||
            record->cache_bucket != parent.slot || record->cache_anchor != parent.generation) goto retain;
        if (record->phase == LSF_PREPAID_RETURNED) continue;
        if (record->phase != LSF_PREPAID_LIVE) goto retain;
        if (record->deferred == LSF_PREPAID_PRIVATE &&
            !lsf_device_finish(&factory.pool, state->owner, ticket, record->kind)) goto retain;
        /* Published storage belongs to actual native free points, never this plan. */
    }
    goto out;
retain:
    factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
}
