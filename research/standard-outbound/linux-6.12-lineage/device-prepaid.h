/* SPDX-License-Identifier: GPL-2.0-only */
/* Uninstalled source for the actual device producer. Caller holds the SAME pool lock.
 * This uses the existing records/owners and unused infrastructure extent; it is
 * not another registrar, operator certificate or proof of native admission.
 * No device/factory selection is installed by this header. */
#ifndef LSF_STREAM_DEVICE_PREPAID_H
#define LSF_STREAM_DEVICE_PREPAID_H
#include "prepaid.h"

#define LSF_DEVICE_OWNER_SLOT (LSF_OWNER_SLOTS - 1u)
#if LSF_DEVICE_OWNER_SLOT < LSF_FACTORY_CONTEXTS
#error "The fixed device owner must not alias an application owner"
#endif

/* Disjoint from every application kind. Only actual allocating call sites can
 * select one of these private kinds, BEFORE the address is published. */
enum lsf_device_kind {
    LSF_DEVICE_ROOT = 0x100,
    LSF_DEVICE_PCI,
    LSF_DEVICE_VIRTIO,
    LSF_DEVICE_RING,
    LSF_DEVICE_QUEUE,
    LSF_DEVICE_DESCRIPTOR_STATE,
    LSF_DEVICE_DESCRIPTOR_EXTRA,
    LSF_DEVICE_RX_HEADER,
    LSF_DEVICE_RX_HEAD
};

static inline int lsf_device_kind(unsigned int kind)
{
    return kind == LSF_DEVICE_ROOT || kind == LSF_DEVICE_PCI ||
        kind == LSF_DEVICE_VIRTIO || kind == LSF_DEVICE_RING ||
        kind == LSF_DEVICE_QUEUE || kind == LSF_DEVICE_DESCRIPTOR_STATE ||
        kind == LSF_DEVICE_DESCRIPTOR_EXTRA || kind == LSF_DEVICE_RX_HEADER ||
        kind == LSF_DEVICE_RX_HEAD;
}

/* This internal domain is deliberately NOT recognized by the ordinary
 * application context lookup/create APIs. Four application contexts, their
 * 96/64 KiB arenas and their original source bodies stay unchanged. */
static inline struct lsf_prepaid_context *lsf_device_context(
    struct lsf_prepaid *pool, struct lsf_prepaid_key key)
{
    struct lsf_prepaid_context *context;
    if (!pool || !pool->initialized || pool->poisoned ||
        key.slot != LSF_DEVICE_OWNER_SLOT || !key.generation)
        return 0;
    context = &pool->contexts[LSF_DEVICE_OWNER_SLOT];
    if (context->generation != key.generation || context->poisoned)
        return 0;
    return context;
}

/* Called by the private kernel factory only AFTER its original native backing
 * carrier and physical backing exist. There are no caller-supplied scope words:
 * this cannot create a factory or assert that native carrier. Its real caller
 * must derive this shared domain from the original held factory,
 * never from a guest request or an already allocated device address. */
static inline int lsf_device_context_create(struct lsf_prepaid *pool,
    struct lsf_prepaid_key *key)
{
    struct lsf_prepaid_context *context;
    unsigned int i;
    if (!pool || !key || !pool->initialized || pool->poisoned || pool->stopped ||
        !pool->next_generation ||
        pool->next_generation == (lsf_u64)-1)
        return 0;
    context = &pool->contexts[LSF_DEVICE_OWNER_SLOT];
    if (context->generation || context->cursor || context->live ||
        context->continuations || context->closed || context->poisoned)
        return 0;
    for (i = 0; i < 8; ++i)
        if (context->scope.identity[i])
            return 0;
    /* A shared NodeFixed domain is not an activation/tenant scope. The zero
     * scope is NEVER accepted by the original application APIs, which also
     * reject this slot. Its actual factory/backing owner supplies authority. */
    context->generation = pool->next_generation++;
    key->slot = LSF_DEVICE_OWNER_SLOT;
    key->generation = context->generation;
    return 1;
}

static inline struct lsf_prepaid_view *lsf_device_record(
    struct lsf_prepaid *pool, struct lsf_prepaid_key key,
    struct lsf_prepaid_ticket ticket, unsigned int kind)
{
    struct lsf_prepaid_context *context = lsf_device_context(pool, key);
    struct lsf_prepaid_view *record;
    if (!context || !ticket.slot || ticket.slot >= LSF_ALLOCATION_SLOTS ||
        !ticket.generation || !lsf_device_kind(kind))
        return 0;
    record = &pool->records[ticket.slot];
    if (record->phase != LSF_PREPAID_LIVE || record->kind != kind ||
        record->generation != ticket.generation || record->owner != key.slot ||
        record->owner_generation != key.generation ||
        record->offset < LSF_FACTORY_INFRA_OFFSET ||
        record->offset - LSF_FACTORY_INFRA_OFFSET > LSF_FACTORY_INFRA_BYTES ||
        record->bytes > LSF_FACTORY_INFRA_BYTES -
            (record->offset - LSF_FACTORY_INFRA_OFFSET))
        return 0;
    return record;
}

/* Allocate only inside the original 192 KiB tail, BEFORE a real constructor
 * publishes anything. The root can be born once; all later births require an
 * actual LIVE same-domain parent, including legitimate late drain work. */
static inline int lsf_device_allocate(struct lsf_prepaid *pool,
    struct lsf_prepaid_key key, lsf_u64 bytes, unsigned int kind,
    struct lsf_prepaid_ticket parent, struct lsf_prepaid_ticket *ticket,
    lsf_u64 *offset)
{
    struct lsf_prepaid_context *context = lsf_device_context(pool, key);
    struct lsf_prepaid_view *original;
    lsf_u64 rounded;
    unsigned int i;
    if (!context || !ticket || !offset || !lsf_device_kind(kind) || !bytes ||
        bytes > (lsf_u64)-1 - 63u || !pool->next_generation ||
        pool->next_generation == (lsf_u64)-1)
        return 0;
    if (kind == LSF_DEVICE_ROOT) {
        if (parent.slot || parent.generation || context->cursor ||
            context->live || context->closed || pool->stopped)
            return 0;
    } else {
        if (!parent.slot || parent.slot >= LSF_ALLOCATION_SLOTS)
            return 0;
        original = &pool->records[parent.slot];
        if (original->phase != LSF_PREPAID_LIVE ||
            original->generation != parent.generation ||
            original->owner != key.slot ||
            original->owner_generation != key.generation ||
            !lsf_device_kind(original->kind))
            return 0;
    }
    rounded = (bytes + 63u) & ~(lsf_u64)63u;
    if (rounded > LSF_FACTORY_INFRA_BYTES ||
        context->cursor > LSF_FACTORY_INFRA_BYTES - rounded)
        return 0;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        struct lsf_prepaid_view *record = &pool->records[i];
        if (record->phase != LSF_PREPAID_EMPTY)
            continue;
        *record = (struct lsf_prepaid_view){
            .generation = pool->next_generation++,
            .owner_generation = key.generation,
            .offset = LSF_FACTORY_INFRA_OFFSET + context->cursor,
            .bytes = rounded,
            .owner = key.slot,
            .phase = LSF_PREPAID_LIVE,
            .kind = kind,
            .deferred = LSF_PREPAID_PRIVATE,
            .cache_bucket = parent.slot,
            .cache_anchor = parent.generation,
        };
        context->cursor += rounded;
        context->live++;
        ticket->slot = i;
        ticket->generation = record->generation;
        *offset = record->offset;
        return 1;
    }
    return 0;
}

/* Separate selected normal-stream allocator. Caller holds SAME pool_lock;
 * all original context/parent/record/generation guards remain. Entire extent
 * and start-address padding are charged to original192KiB before publication.
 * Padding is continuously owned backing, not an untracked allocation/view.
 * No record/address reuse or physical backing return is introduced here. */
static inline int lsf_device_allocate_stream_aligned(struct lsf_prepaid *pool,
    struct lsf_prepaid_key key, lsf_u64 bytes, unsigned int kind,
    struct lsf_prepaid_ticket parent, struct lsf_prepaid_ticket *ticket,
    lsf_u64 alignment, lsf_u64 *offset)
{
    struct lsf_prepaid_context *context = lsf_device_context(pool, key);
    struct lsf_prepaid_view *original;
    lsf_u64 rounded, start;
    unsigned int i;
    if (!context || !ticket || !offset || !lsf_device_kind(kind) || !bytes ||
        bytes > (lsf_u64)-1 - 63u ||
        (alignment != 64u && alignment != 4096u) ||
        LSF_FACTORY_INFRA_OFFSET % alignment ||
        context->cursor > (lsf_u64)-1 - (alignment - 1u) ||
        !pool->next_generation ||
        pool->next_generation == (lsf_u64)-1)
        return 0;
    if (kind == LSF_DEVICE_ROOT) {
        if (parent.slot || parent.generation || context->cursor ||
            context->live || context->closed || pool->stopped)
            return 0;
    } else {
        if (!parent.slot || parent.slot >= LSF_ALLOCATION_SLOTS)
            return 0;
        original = &pool->records[parent.slot];
        if (original->phase != LSF_PREPAID_LIVE ||
            original->generation != parent.generation ||
            original->owner != key.slot ||
            original->owner_generation != key.generation ||
            !lsf_device_kind(original->kind))
            return 0;
    }
    rounded = (bytes + 63u) & ~(lsf_u64)63u;
    start = (context->cursor + alignment - 1u) & ~(alignment - 1u);
    if (rounded > LSF_FACTORY_INFRA_BYTES ||
        start > LSF_FACTORY_INFRA_BYTES - rounded)
        return 0;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        struct lsf_prepaid_view *record = &pool->records[i];
        if (record->phase != LSF_PREPAID_EMPTY)
            continue;
        *record = (struct lsf_prepaid_view){
            .generation = pool->next_generation++,
            .owner_generation = key.generation,
            .offset = LSF_FACTORY_INFRA_OFFSET + start,
            .bytes = rounded,
            .owner = key.slot,
            .phase = LSF_PREPAID_LIVE,
            .kind = kind,
            .deferred = LSF_PREPAID_PRIVATE,
            .cache_bucket = parent.slot,
            .cache_anchor = parent.generation,
        };
        context->cursor = start + rounded;
        context->live++;
        ticket->slot = i;
        ticket->generation = record->generation;
        *offset = record->offset;
        return 1;
    }
    return 0;
}

/* These transitions are used at the actual publication/unlink/callback sites.
 * A changed flag alone does not prove a DMA or callback has retired. */
static inline int lsf_device_publish(struct lsf_prepaid *pool,
    struct lsf_prepaid_key key, struct lsf_prepaid_ticket ticket,
    unsigned int kind)
{
    struct lsf_prepaid_context *context = lsf_device_context(pool, key);
    struct lsf_prepaid_view *record = lsf_device_record(pool, key, ticket, kind);
    if (!context || context->closed || !record || record->deferred != LSF_PREPAID_PRIVATE)
        return 0;
    record->deferred = LSF_PREPAID_PUBLISHED;
    return 1;
}

static inline int lsf_device_queue(struct lsf_prepaid *pool,
    struct lsf_prepaid_key key, struct lsf_prepaid_ticket ticket,
    unsigned int kind)
{
    struct lsf_prepaid_context *context = lsf_device_context(pool, key);
    struct lsf_prepaid_view *record = lsf_device_record(pool, key, ticket, kind);
    if (!context || !record || record->deferred != LSF_PREPAID_PUBLISHED ||
        context->continuations == LSF_ALLOCATION_SLOTS)
        return 0;
    record->deferred = LSF_PREPAID_QUEUED;
    context->continuations++;
    return 1;
}

static inline int lsf_device_finish(struct lsf_prepaid *pool,
    struct lsf_prepaid_key key, struct lsf_prepaid_ticket ticket,
    unsigned int kind)
{
    struct lsf_prepaid_context *context = lsf_device_context(pool, key);
    struct lsf_prepaid_view *record = lsf_device_record(pool, key, ticket, kind);
    unsigned int queued, i;
    if (!context || !record || !context->live ||
        (record->deferred != LSF_PREPAID_PRIVATE &&
         record->deferred != LSF_PREPAID_QUEUED))
        return 0;
    queued = record->deferred == LSF_PREPAID_QUEUED;
    if ((queued && !context->continuations) ||
        (kind == LSF_DEVICE_ROOT && (!context->closed || context->live != 1 ||
         context->continuations != queued)))
        return 0;
    /* A constructor/final callback cannot retire an ancestor while a real
     * descendant still owns it. Parent identity is in the SAME fixed record;
     * no second table, address-based adoption or refundable model charge. */
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        struct lsf_prepaid_view *child = &pool->records[i];
        if (child->phase == LSF_PREPAID_LIVE && child->owner == key.slot &&
            child->owner_generation == key.generation &&
            child->cache_bucket == ticket.slot && child->cache_anchor == ticket.generation)
            return 0;
    }
    if (queued)
        context->continuations--;
    record->phase = LSF_PREPAID_RETURNED;
    context->live--;
    /* No live-generation address/record reuse and no backing return. Node
     * occupancy and its original native carrier remain separate lifetimes. */
    return 1;
}

static inline int lsf_device_close(struct lsf_prepaid *pool,
    struct lsf_prepaid_key key)
{
    struct lsf_prepaid_context *context = lsf_device_context(pool, key);
    if (!context)
        return 0;
    context->closed = 1;
    return 1;
}
#endif
