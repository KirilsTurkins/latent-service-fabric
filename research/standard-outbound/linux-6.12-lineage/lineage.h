/* SPDX-License-Identifier: GPL-2.0-only */
/* Private serialized mechanism. No userspace ABI or retirement certificate. */
#ifndef LSF_STREAM_LINEAGE_H
#define LSF_STREAM_LINEAGE_H
#ifdef __KERNEL__
#include <linux/types.h>
typedef u64 lsf_u64;
#else
#include <stdint.h>
typedef uint64_t lsf_u64;
#endif

#define LSF_OWNER_SLOTS 64u
#define LSF_ALLOCATION_SLOTS 256u
#define LSF_TCP_BYTES 98304u
#define LSF_DNS_BYTES 65536u

enum lsf_kind { LSF_SOCKET = 1, LSF_TIMEWAIT, LSF_SKB_HEADER, LSF_SKB_CLONE, LSF_SKB_HEAD };
enum lsf_phase { LSF_UNUSED, LSF_OPEN, LSF_DRAINING };
enum lsf_allocation_phase { LSF_EMPTY, LSF_RESERVED, LSF_LIVE, LSF_FREE_CAPTURED };

/* The future trusted admission path must bind these to the entire sealed scope.
 * Copying caller assertions here is not a supported platform implementation. */
struct lsf_scope { lsf_u64 identity[8]; };
struct lsf_key { unsigned int slot; lsf_u64 generation; };
struct lsf_token {
    unsigned int slot, owner, kind;
    lsf_u64 generation, owner_generation, address, cookie, bytes;
};
struct lsf_owner {
    struct lsf_scope scope;
    lsf_u64 generation, live_bytes, maximum_bytes;
    unsigned int phase, poisoned, allocations;
};
struct lsf_allocation {
    struct lsf_token token;
    unsigned int phase;
};
struct lsf_lineage {
    struct lsf_owner owners[LSF_OWNER_SLOTS];
    struct lsf_allocation allocations[LSF_ALLOCATION_SLOTS];
    lsf_u64 next_owner, next_allocation;
    unsigned int poisoned;
};

static inline struct lsf_token lsf_empty_token(void)
{
    struct lsf_token value = {0};
    return value;
}

static inline int lsf_kind_valid(unsigned int kind)
{
    return kind >= LSF_SOCKET && kind <= LSF_SKB_HEAD;
}

static inline struct lsf_owner *lsf_owner_for(struct lsf_lineage *state, struct lsf_key key)
{
    struct lsf_owner *owner;
    if (key.slot >= LSF_OWNER_SLOTS || !key.generation)
        return 0;
    owner = &state->owners[key.slot];
    if (owner->phase == LSF_UNUSED || owner->generation != key.generation)
        return 0;
    return owner;
}

static inline struct lsf_allocation *lsf_allocation_for(struct lsf_lineage *state,
                                               struct lsf_token token)
{
    struct lsf_allocation *allocation;
    struct lsf_token *record;
    if (token.slot >= LSF_ALLOCATION_SLOTS || !token.generation)
        return 0;
    allocation = &state->allocations[token.slot];
    record = &allocation->token;
    if (allocation->phase == LSF_EMPTY || record->generation != token.generation ||
        record->owner != token.owner || record->owner_generation != token.owner_generation ||
        record->kind != token.kind || record->bytes != token.bytes ||
        record->address != token.address || record->cookie != token.cookie)
        return 0;
    return allocation;
}

/* Owner slots have no reuse/acknowledgement/release API in this prerequisite. */
static inline int lsf_owner_admit(struct lsf_lineage *state, struct lsf_scope scope,
                          lsf_u64 maximum_bytes, struct lsf_key *key)
{
    unsigned int i;
    if (state->poisoned || !state->next_owner ||
        (maximum_bytes != LSF_TCP_BYTES && maximum_bytes != LSF_DNS_BYTES))
        return 0;
    for (i = 0; i < 8; ++i)
        if (!scope.identity[i])
            return 0;
    for (i = 0; i < LSF_OWNER_SLOTS; ++i) {
        struct lsf_owner *owner = &state->owners[i];
        if (owner->phase != LSF_UNUSED)
            continue;
        owner->scope = scope;
        owner->generation = state->next_owner++;
        owner->maximum_bytes = maximum_bytes;
        owner->phase = LSF_OPEN;
        key->slot = i;
        key->generation = owner->generation;
        if (!state->next_owner) {
            state->poisoned = 1;
            return 0;
        }
        return 1;
    }
    state->poisoned = 1;
    return 0;
}

/* Must precede the corresponding allocator call. This covers registered
 * allocations only; it does not authenticate the missing complete kernel path. */
static inline int lsf_birth_prepare(struct lsf_lineage *state, struct lsf_key key,
                             struct lsf_token parent, unsigned int kind,
                             lsf_u64 bytes, struct lsf_token *token)
{
    struct lsf_owner *owner = lsf_owner_for(state, key);
    unsigned int i;
    if (!owner || state->poisoned || owner->poisoned)
        return 0;
    if (!lsf_kind_valid(kind) || !bytes || bytes > owner->maximum_bytes ||
        owner->live_bytes > owner->maximum_bytes - bytes || !state->next_allocation) {
        owner->poisoned = 1;
        return 0;
    }
    if (parent.generation) {
        struct lsf_allocation *source = lsf_allocation_for(state, parent);
        if (!source || source->phase != LSF_LIVE || parent.owner != key.slot ||
            parent.owner_generation != key.generation) {
            owner->poisoned = 1;
            return 0;
        }
    } else if (owner->phase != LSF_OPEN) {
        owner->poisoned = 1;
        return 0;
    }
    for (i = 0; i < LSF_ALLOCATION_SLOTS; ++i) {
        struct lsf_allocation *allocation = &state->allocations[i];
        if (allocation->phase != LSF_EMPTY)
            continue;
        *token = lsf_empty_token();
        token->slot = i;
        token->owner = key.slot;
        token->owner_generation = key.generation;
        token->generation = state->next_allocation++;
        token->kind = kind;
        token->bytes = bytes;
        allocation->token = *token;
        allocation->phase = LSF_RESERVED;
        owner->live_bytes += bytes;
        owner->allocations++;
        if (!state->next_allocation) {
            owner->poisoned = 1;
            return 0;
        }
        return 1;
    }
    owner->poisoned = 1;
    return 0;
}

static inline int lsf_birth_commit(struct lsf_lineage *state, struct lsf_token *token,
                           lsf_u64 address, lsf_u64 cookie)
{
    struct lsf_allocation *allocation = lsf_allocation_for(state, *token);
    unsigned int i;
    if (state->poisoned || !allocation || allocation->phase != LSF_RESERVED || !address ||
        state->owners[token->owner].poisoned ||
        ((token->kind == LSF_SOCKET || token->kind == LSF_TIMEWAIT) && !cookie)) {
        state->poisoned = 1;
        return 0;
    }
    for (i = 0; i < LSF_ALLOCATION_SLOTS; ++i) {
        struct lsf_allocation *other = &state->allocations[i];
        if (other != allocation && other->phase != LSF_EMPTY &&
            other->token.address == address) {
            state->poisoned = 1;
            return 0;
        }
    }
    token->address = address;
    token->cookie = cookie;
    allocation->token = *token;
    allocation->phase = LSF_LIVE;
    return 1;
}

/* Called only while the allocation is live. All identity is copied now.
 * SKB shells may already have lost skb->sk, so their stored lineage is used. */
static inline struct lsf_token lsf_capture_free(struct lsf_lineage *state, unsigned int kind,
                                         lsf_u64 address, lsf_u64 cookie)
{
    unsigned int i;
    for (i = 0; i < LSF_ALLOCATION_SLOTS; ++i) {
        struct lsf_allocation *allocation = &state->allocations[i];
        struct lsf_token token = allocation->token;
        if (allocation->phase == LSF_EMPTY || token.address != address)
            continue;
        if (allocation->phase != LSF_LIVE || token.kind != kind ||
            ((kind == LSF_SOCKET || kind == LSF_TIMEWAIT || cookie) && cookie != token.cookie)) {
            state->owners[token.owner].poisoned = 1;
            return lsf_empty_token();
        }
        allocation->phase = LSF_FREE_CAPTURED;
        return token;
    }
    /* An unclassified event cannot establish absence of owned descendants.
     * A future complete trusted path must classify genuinely unowned traffic
     * before this private observer. Until then an active experiment fails shut. */
    for (i = 0; i < LSF_OWNER_SLOTS; ++i)
        if (state->owners[i].phase != LSF_UNUSED)
            state->poisoned = 1;
    return lsf_empty_token();
}

/* No pointer is dereferenced here. Only the pre-free copied token is accepted. */
static inline int lsf_post_free(struct lsf_lineage *state, struct lsf_token token)
{
    struct lsf_allocation *allocation;
    struct lsf_owner *owner;
    struct lsf_key key = {token.owner, token.owner_generation};
    if (!token.generation)
        return 1;
    allocation = lsf_allocation_for(state, token);
    owner = lsf_owner_for(state, key);
    if (!allocation || !owner || allocation->phase != LSF_FREE_CAPTURED ||
        !owner->allocations || owner->live_bytes < token.bytes) {
        state->poisoned = 1;
        return 0;
    }
    owner->live_bytes -= token.bytes;
    owner->allocations--;
    allocation->phase = LSF_EMPTY;
    return 1;
}

static inline int lsf_begin_drain(struct lsf_lineage *state, struct lsf_key key)
{
    struct lsf_owner *owner = lsf_owner_for(state, key);
    if (!owner || state->poisoned || owner->poisoned)
        return 0;
    owner->phase = LSF_DRAINING;
    return 1;
}

/* This is only a mechanism observation, never a kernel certificate or refund.
 * Drain permits descendants from any remaining live allocation. A close flag
 * does not seal deferred TCP/TIME_WAIT/SKB work. */
static inline int lsf_mechanism_drained(struct lsf_lineage *state, struct lsf_key key)
{
    struct lsf_owner *owner = lsf_owner_for(state, key);
    return owner && !state->poisoned && !owner->poisoned &&
        owner->phase == LSF_DRAINING && !owner->allocations && !owner->live_bytes;
}

static inline void lsf_unproved_allocation(struct lsf_lineage *state, lsf_u64 address)
{
    unsigned int i;
    for (i = 0; i < LSF_ALLOCATION_SLOTS; ++i) {
        struct lsf_allocation *allocation = &state->allocations[i];
        if (allocation->phase != LSF_EMPTY && allocation->token.address == address)
            state->owners[allocation->token.owner].poisoned = 1;
    }
}

static inline void lsf_observation_lost(struct lsf_lineage *state)
{
    state->poisoned = 1;
}
#endif
