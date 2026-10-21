/* SPDX-License-Identifier: GPL-2.0-only */
/* Private backing allocator; caller holds the factory lock. Not an ABI. */
#ifndef LSF_STREAM_PREPAID_H
#define LSF_STREAM_PREPAID_H
#ifdef __KERNEL__
#include <net/lsf_stream_lineage_core.h>
#else
#include "lineage.h"
#endif

/* One whole order-7 extent on the proposed 4-KiB-page platform. The native
 * owner prepays ONE MiB including metadata/bootstrap overhead, not a larger
 * per-connection allowance. Exact compiled closure is still unavailable. */
#define LSF_BACKING_ORDER 7u
#define LSF_BACKING_BYTES 524288u
#define LSF_BOOTSTRAP_CEILING 1048576u
#define LSF_FACTORY_CONTEXTS 4u
#define LSF_FACTORY_INFRA_OFFSET (2u * LSF_TCP_BYTES + 2u * LSF_DNS_BYTES)
#define LSF_FACTORY_INFRA_BYTES (LSF_BACKING_BYTES - LSF_FACTORY_INFRA_OFFSET)

enum lsf_prepaid_phase { LSF_PREPAID_EMPTY, LSF_PREPAID_LIVE, LSF_PREPAID_RETURNED };
enum lsf_prepaid_kind {
    LSF_PREPAID_OBJECT, LSF_PREPAID_INODE_BLOB, LSF_PREPAID_SOCK_BLOB,
    LSF_PREPAID_LABEL, LSF_PREPAID_LABEL_DOMAIN, LSF_PREPAID_LABEL_CATMAP,
    LSF_PREPAID_CIPSO_BUFFER, LSF_PREPAID_IP_OPTIONS, LSF_PREPAID_NETPORT
};
enum lsf_prepaid_deferred {
    LSF_PREPAID_PRIVATE, LSF_PREPAID_QUEUED, LSF_PREPAID_PUBLISHED
};
struct lsf_prepaid_view {
    lsf_u64 generation, owner_generation, offset, bytes;
    unsigned int owner, phase, kind, deferred;
    /* Original cache bucket plus one, written BEFORE publication. This is
     * inside the SAME fixed record, never a caller-supplied pointer proof. */
    unsigned int cache_bucket;
};
struct lsf_prepaid_context {
    struct lsf_scope scope;
    lsf_u64 generation, cursor;
    unsigned int live, continuations, closed, poisoned;
};
struct lsf_prepaid_key { unsigned int slot; lsf_u64 generation; };
struct lsf_prepaid_ticket { unsigned int slot; lsf_u64 generation; };
struct lsf_prepaid {
    /* The backing itself occupies record zero. All physical backing plus all
     * logical views share the ORIGINAL 256-record ceiling. This new backend
     * must not run alongside another independent 256-record registrar. */
    struct lsf_prepaid_view records[LSF_ALLOCATION_SLOTS];
    struct lsf_prepaid_context contexts[LSF_OWNER_SLOTS];
    lsf_u64 next_generation;
    unsigned int initialized, stopped, poisoned;
};

static inline int lsf_prepaid_scope_equal(struct lsf_scope a, struct lsf_scope b)
{
    unsigned int i;
    for (i = 0; i < 8; ++i)
        if (!a.identity[i] || a.identity[i] != b.identity[i])
            return 0;
    return 1;
}

static inline lsf_u64 lsf_prepaid_limit(unsigned int slot)
{
    return slot < 2 ? LSF_TCP_BYTES : LSF_DNS_BYTES;
}

static inline lsf_u64 lsf_prepaid_start(unsigned int slot)
{
    return slot < 2 ? (lsf_u64)slot * LSF_TCP_BYTES :
        2u * LSF_TCP_BYTES + (lsf_u64)(slot - 2u) * LSF_DNS_BYTES;
}

static inline int lsf_prepaid_initialize(struct lsf_prepaid *pool)
{
    unsigned int i;
    if (!pool || pool->initialized || pool->poisoned)
        return 0;
    for (i = 0; i < LSF_ALLOCATION_SLOTS; ++i)
        if (pool->records[i].phase)
            return 0;
    for (i = 0; i < LSF_OWNER_SLOTS; ++i)
        if (pool->contexts[i].generation)
            return 0;
    pool->initialized = 1;
    pool->next_generation = 1;
    pool->records[0].phase = LSF_PREPAID_LIVE;
    pool->records[0].bytes = LSF_BACKING_BYTES;
    return 1;
}

static inline struct lsf_prepaid_context *lsf_prepaid_context_for(
    struct lsf_prepaid *pool, struct lsf_prepaid_key key)
{
    if (!pool || !pool->initialized || pool->poisoned ||
        key.slot >= LSF_FACTORY_CONTEXTS || !key.generation ||
        pool->contexts[key.slot].generation != key.generation ||
        pool->contexts[key.slot].poisoned)
        return 0;
    return &pool->contexts[key.slot];
}

/* Called only by the protected factory after original native admission. Scope
 * equality is consistency, not authentication of arbitrary userspace words. */
static inline int lsf_prepaid_context_create(struct lsf_prepaid *pool,
    struct lsf_scope scope, lsf_u64 maximum, struct lsf_prepaid_key *key)
{
    unsigned int i;
    if (!pool || !key || !pool->initialized || pool->poisoned || pool->stopped ||
        !lsf_prepaid_scope_equal(scope, scope) || !pool->next_generation ||
        pool->next_generation == (lsf_u64)-1 ||
        (maximum != LSF_TCP_BYTES && maximum != LSF_DNS_BYTES))
        return 0;
    for (i = 0; i < LSF_FACTORY_CONTEXTS; ++i) {
        struct lsf_prepaid_context *context = &pool->contexts[i];
        if (lsf_prepaid_limit(i) != maximum || context->generation)
            continue;
        context->generation = pool->next_generation++;
        context->scope = scope;
        key->slot = i;
        key->generation = context->generation;
        return 1;
    }
    return 0;
}

/* No kmalloc/page/SLUB fallback, no caller address, no allocation-size proof.
 * This allocates a view INSIDE already prepaid backing, rounded to 64 bytes.
 * The future compiled consumer must prove its complete object/layout closure.
 * Return does not make space reusable within a live context generation. */
static inline int lsf_prepaid_allocate(struct lsf_prepaid *pool,
    struct lsf_prepaid_key key, lsf_u64 bytes, int descendant,
    struct lsf_prepaid_ticket parent, struct lsf_prepaid_ticket *ticket,
    lsf_u64 *offset)
{
    struct lsf_prepaid_context *context = lsf_prepaid_context_for(pool, key);
    lsf_u64 rounded, limit;
    unsigned int i;
    if (!context || !ticket || !offset || !bytes || bytes > (lsf_u64)-1 - 63u ||
        (descendant != 0 && descendant != 1) ||
        !pool->next_generation || pool->next_generation == (lsf_u64)-1)
        return 0;
    if (descendant) {
        struct lsf_prepaid_view *original;
        if (!parent.slot || parent.slot >= LSF_ALLOCATION_SLOTS)
            return 0;
        original = &pool->records[parent.slot];
        if (original->phase != LSF_PREPAID_LIVE ||
            original->generation != parent.generation || original->owner != key.slot ||
            original->owner_generation != key.generation)
            return 0;
    } else if (context->closed || pool->stopped) {
        return 0;
    }
    rounded = (bytes + 63u) & ~(lsf_u64)63u;
    limit = lsf_prepaid_limit(key.slot);
    if (rounded > limit || context->cursor > limit - rounded)
        return 0;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        struct lsf_prepaid_view *record = &pool->records[i];
        if (record->phase != LSF_PREPAID_EMPTY)
            continue;
        record->generation = pool->next_generation++;
        record->owner_generation = key.generation;
        record->owner = key.slot;
        record->offset = lsf_prepaid_start(key.slot) + context->cursor;
        record->bytes = rounded;
        record->phase = LSF_PREPAID_LIVE;
        context->cursor += rounded;
        context->live++;
        ticket->slot = i;
        ticket->generation = record->generation;
        *offset = record->offset;
        return 1;
    }
    return 0;
}

/* The kind is selected by the actual private allocator BEFORE publishing the
 * address. It is not supplied by a free callback, userspace or a later binder.
 * The factory holds the same pool lock across allocation and this write. */
static inline int lsf_prepaid_blob_allocate(struct lsf_prepaid *pool,
    struct lsf_prepaid_key key, lsf_u64 bytes, unsigned int kind,
    struct lsf_prepaid_ticket *ticket, lsf_u64 *offset)
{
    if (kind != LSF_PREPAID_INODE_BLOB && kind != LSF_PREPAID_SOCK_BLOB)
        return 0;
    if (!lsf_prepaid_allocate(pool, key, bytes, 0,
                             (struct lsf_prepaid_ticket){0}, ticket, offset))
        return 0;
    pool->records[ticket->slot].kind = kind;
    return 1;
}

/* Actual nested producers inherit a LIVE original object, including while a
 * sealed root is draining. No new root admission or late address binding. */
static inline int lsf_prepaid_child_allocate(struct lsf_prepaid *pool,
    struct lsf_prepaid_key key, lsf_u64 bytes, unsigned int kind,
    struct lsf_prepaid_ticket parent, struct lsf_prepaid_ticket *ticket,
    lsf_u64 *offset)
{
    if (((kind < LSF_PREPAID_LABEL || kind > LSF_PREPAID_IP_OPTIONS) &&
         kind != LSF_PREPAID_NETPORT) ||
        !lsf_prepaid_allocate(pool, key, bytes, 1, parent, ticket, offset))
        return 0;
    pool->records[ticket->slot].kind = kind;
    return 1;
}

/* A private return callback only has its original blob address, not an inode
 * which might already have died. Search the SAME fixed birth records; never
 * inspect a prefix before an arbitrary pointer or manufacture origin here.
 * Caller has already established that offset is inside the owned backing. */
static inline int lsf_prepaid_blob_find(struct lsf_prepaid *pool,
    lsf_u64 offset, unsigned int kind, struct lsf_prepaid_key *key,
    struct lsf_prepaid_ticket *ticket)
{
    unsigned int i;
    if (!pool || !key || !ticket || !pool->initialized || pool->poisoned ||
        offset >= LSF_BACKING_BYTES ||
        ((kind < LSF_PREPAID_INODE_BLOB || kind > LSF_PREPAID_IP_OPTIONS) &&
         kind != LSF_PREPAID_NETPORT))
        return 0;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        struct lsf_prepaid_view *record = &pool->records[i];
        struct lsf_prepaid_context *context;
        if (record->offset != offset || record->phase != LSF_PREPAID_LIVE ||
            record->kind != kind || !record->generation || !record->owner_generation)
            continue;
        *key = (struct lsf_prepaid_key){record->owner, record->owner_generation};
        context = lsf_prepaid_context_for(pool, *key);
        if (!context || !context->live)
            break;
        *ticket = (struct lsf_prepaid_ticket){i, record->generation};
        return 1;
    }
    pool->poisoned = 1;
    return 0;
}

/* Inode blobs have their OWN RCU callback, independent of inode retirement.
 * Exactly one continuation belongs to that live original birth record. It
 * must remain charged until the actual callback has finished all LSM hooks. */
static inline int lsf_prepaid_record_queue(struct lsf_prepaid *pool,
    struct lsf_prepaid_key key, struct lsf_prepaid_ticket ticket, unsigned int kind)
{
    struct lsf_prepaid_context *context = lsf_prepaid_context_for(pool, key);
    struct lsf_prepaid_view *record;
    if (!context || !ticket.slot || ticket.slot >= LSF_ALLOCATION_SLOTS)
        return 0;
    record = &pool->records[ticket.slot];
    if (record->phase != LSF_PREPAID_LIVE || record->generation != ticket.generation ||
        record->owner != key.slot || record->owner_generation != key.generation ||
        record->kind != kind ||
        (kind != LSF_PREPAID_INODE_BLOB && kind != LSF_PREPAID_IP_OPTIONS &&
         kind != LSF_PREPAID_NETPORT) ||
        (kind == LSF_PREPAID_INODE_BLOB && record->deferred != LSF_PREPAID_PRIVATE) ||
        (kind == LSF_PREPAID_IP_OPTIONS && record->deferred != LSF_PREPAID_PUBLISHED) ||
        (kind == LSF_PREPAID_NETPORT && record->deferred != LSF_PREPAID_PUBLISHED) ||
        !context->live || context->continuations == LSF_ALLOCATION_SLOTS) {
        context->poisoned = 1;
        return 0;
    }
    record->deferred = LSF_PREPAID_QUEUED;
    context->continuations++;
    return 1;
}

static inline int lsf_prepaid_blob_queue(struct lsf_prepaid *pool,
    struct lsf_prepaid_key key, struct lsf_prepaid_ticket ticket)
{
    return lsf_prepaid_record_queue(pool, key, ticket, LSF_PREPAID_INODE_BLOB);
}

/* Only the actual CIPSO producer calls this BEFORE rcu_assign_pointer. A
 * published option cannot take its earlier synchronous-failure free path. */
static inline int lsf_prepaid_options_publish(struct lsf_prepaid *pool,
    struct lsf_prepaid_key key, struct lsf_prepaid_ticket ticket)
{
    struct lsf_prepaid_context *context = lsf_prepaid_context_for(pool, key);
    struct lsf_prepaid_view *record;
    if (!context || !ticket.slot || ticket.slot >= LSF_ALLOCATION_SLOTS)
        return 0;
    record = &pool->records[ticket.slot];
    if (record->phase != LSF_PREPAID_LIVE || record->generation != ticket.generation ||
        record->owner != key.slot || record->owner_generation != key.generation ||
        record->kind != LSF_PREPAID_IP_OPTIONS || record->deferred) {
        context->poisoned = 1;
        return 0;
    }
    record->deferred = LSF_PREPAID_PUBLISHED;
    return 1;
}

/* Called with the original Netport cache lock held, before list_add_rcu.
 * Ordinary cache hits do not transfer ownership between contexts. */
static inline int lsf_prepaid_netport_publish(struct lsf_prepaid *pool,
    struct lsf_prepaid_key key, struct lsf_prepaid_ticket ticket, unsigned int bucket)
{
    struct lsf_prepaid_context *context = lsf_prepaid_context_for(pool, key);
    struct lsf_prepaid_view *record;
    if (!context || !ticket.slot || ticket.slot >= LSF_ALLOCATION_SLOTS)
        return 0;
    record = &pool->records[ticket.slot];
    if (bucket >= 256u || record->phase != LSF_PREPAID_LIVE ||
        record->generation != ticket.generation || record->owner != key.slot ||
        record->owner_generation != key.generation || record->kind != LSF_PREPAID_NETPORT ||
        record->deferred != LSF_PREPAID_PRIVATE || record->cache_bucket) {
        context->poisoned = 1;
        return 0;
    }
    record->cache_bucket = bucket + 1u;
    record->deferred = LSF_PREPAID_PUBLISHED;
    return 1;
}

/* Copy only existing fixed-record identity while holding the pool lock. The
 * caller releases it BEFORE acquiring the cache lock, then revalidates with
 * netport_current while holding cache->pool locks. No pool->cache nesting. */
static inline int lsf_prepaid_netport_candidate(struct lsf_prepaid *pool,
    struct lsf_prepaid_key key, unsigned int slot,
    struct lsf_prepaid_ticket *ticket, unsigned int *bucket)
{
    struct lsf_prepaid_context *context = lsf_prepaid_context_for(pool, key);
    struct lsf_prepaid_view *record;
    if (!context || !ticket || !bucket || !slot || slot >= LSF_ALLOCATION_SLOTS)
        return 0;
    record = &pool->records[slot];
    if (record->phase != LSF_PREPAID_LIVE || record->owner != key.slot ||
        record->owner_generation != key.generation || record->kind != LSF_PREPAID_NETPORT ||
        record->deferred != LSF_PREPAID_PUBLISHED)
        return 0;
    if (!record->generation || !record->cache_bucket || record->cache_bucket > 256u) {
        context->poisoned = 1;
        return -1;
    }
    *ticket = (struct lsf_prepaid_ticket){slot, record->generation};
    *bucket = record->cache_bucket - 1u;
    return 1;
}

static inline int lsf_prepaid_netport_current(struct lsf_prepaid *pool,
    struct lsf_prepaid_key key, struct lsf_prepaid_ticket ticket,
    unsigned int bucket, lsf_u64 *offset)
{
    struct lsf_prepaid_ticket observed_ticket;
    unsigned int actual;
    if (!offset || lsf_prepaid_netport_candidate(pool, key, ticket.slot,
                                                 &observed_ticket, &actual) != 1 ||
        observed_ticket.generation != ticket.generation || actual != bucket)
        return 0;
    *offset = pool->records[ticket.slot].offset;
    return 1;
}

/* Runs AFTER the original LSM free/free_rcu hooks, under the pool lock. Both
 * view and callback ownership retire atomically. No arena reuse or backing
 * refund occurs; recycle still requires the complete closed consumer. */
static inline int lsf_prepaid_blob_finish(struct lsf_prepaid *pool,
    struct lsf_prepaid_key key, struct lsf_prepaid_ticket ticket, unsigned int kind)
{
    struct lsf_prepaid_context *context = lsf_prepaid_context_for(pool, key);
    struct lsf_prepaid_view *record;
    if (!context || !ticket.slot || ticket.slot >= LSF_ALLOCATION_SLOTS)
        return 0;
    record = &pool->records[ticket.slot];
    if (record->phase != LSF_PREPAID_LIVE || record->generation != ticket.generation ||
        record->owner != key.slot || record->owner_generation != key.generation ||
        record->kind != kind || !context->live ||
        ((kind < LSF_PREPAID_INODE_BLOB || kind > LSF_PREPAID_IP_OPTIONS) &&
         kind != LSF_PREPAID_NETPORT) ||
        record->deferred > LSF_PREPAID_PUBLISHED ||
        (kind == LSF_PREPAID_INODE_BLOB && record->deferred != LSF_PREPAID_QUEUED) ||
        (kind == LSF_PREPAID_IP_OPTIONS && record->deferred == LSF_PREPAID_PUBLISHED) ||
        (kind == LSF_PREPAID_NETPORT && record->deferred == LSF_PREPAID_PUBLISHED) ||
        (kind != LSF_PREPAID_INODE_BLOB && kind != LSF_PREPAID_IP_OPTIONS &&
         kind != LSF_PREPAID_NETPORT && record->deferred) ||
        (record->deferred == LSF_PREPAID_QUEUED && !context->continuations)) {
        context->poisoned = 1;
        return 0;
    }
    if (record->deferred)
        context->continuations--;
    record->phase = LSF_PREPAID_RETURNED;
    context->live--;
    return 1;
}

/* Internal allocator return only. There is deliberately no device operation
 * accepting this ticket or a claimed free. Actual backing remains LIVE. */
static inline int lsf_prepaid_return(struct lsf_prepaid *pool,
    struct lsf_prepaid_key key, struct lsf_prepaid_ticket ticket)
{
    struct lsf_prepaid_context *context = lsf_prepaid_context_for(pool, key);
    struct lsf_prepaid_view *record;
    if (!context || !ticket.slot || ticket.slot >= LSF_ALLOCATION_SLOTS)
        return 0;
    record = &pool->records[ticket.slot];
    if (record->generation != ticket.generation || record->phase != LSF_PREPAID_LIVE ||
        record->kind != LSF_PREPAID_OBJECT || record->deferred ||
        record->owner != key.slot || record->owner_generation != key.generation ||
        !context->live) {
        context->poisoned = 1;
        return 0;
    }
    record->phase = LSF_PREPAID_RETURNED;
    context->live--;
    return 1;
}

static inline int lsf_prepaid_continuation(struct lsf_prepaid *pool,
    struct lsf_prepaid_key key, int acquire)
{
    struct lsf_prepaid_context *context = lsf_prepaid_context_for(pool, key);
    if (!context || (acquire != 0 && acquire != 1))
        return 0;
    if (acquire) {
        /* Deferred work must derive from an actual live original object. A
         * closed empty owner cannot manufacture future descendants. */
        if (!context->live || context->continuations == LSF_ALLOCATION_SLOTS)
            return 0;
        context->continuations++;
    } else {
        if (!context->continuations) {
            context->poisoned = 1;
            return 0;
        }
        context->continuations--;
    }
    return 1;
}

/* Only a complete private consumer can call this after sealing root admission
 * and observing ALL real returns/continuations. It is NOT installed today.
 * Reuse advances generation; neither the backing record nor its charge retires. */
static inline int lsf_prepaid_recycle(struct lsf_prepaid *pool, struct lsf_prepaid_key key)
{
    struct lsf_prepaid_context *context = lsf_prepaid_context_for(pool, key);
    unsigned int i;
    if (!context || !context->closed || context->live || context->continuations)
        return 0;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        struct lsf_prepaid_view *record = &pool->records[i];
        if (record->owner == key.slot && record->owner_generation == key.generation) {
            if (record->phase != LSF_PREPAID_RETURNED)
                return 0;
        }
    }
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i)
        if (pool->records[i].owner == key.slot &&
            pool->records[i].owner_generation == key.generation)
            pool->records[i] = (struct lsf_prepaid_view){0};
    *context = (struct lsf_prepaid_context){0};
    return 1;
}
#endif
