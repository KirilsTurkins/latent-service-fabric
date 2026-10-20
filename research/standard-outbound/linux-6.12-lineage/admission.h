/* SPDX-License-Identifier: GPL-2.0-only */
/* Private checked credit carrier; no userspace, layout-authentication or grant ABI. */
#ifndef LSF_STREAM_ADMISSION_H
#define LSF_STREAM_ADMISSION_H
#ifdef __KERNEL__
#include <net/lsf_stream_lineage_core.h>
#else
#include "lineage.h"
#endif

#define LSF_BUNDLE_ALLOCATIONS 2u
enum lsf_constructor { LSF_CONSTRUCT_SOCKET = 1, LSF_CONSTRUCT_TIMEWAIT,
                       LSF_CONSTRUCT_SKB, LSF_CONSTRUCT_FCLONE };
struct lsf_admission {
    struct lsf_key key;
    struct lsf_scope scope;
};
struct lsf_allocation_cost {
    unsigned int kind;
    lsf_u64 bytes;
};
struct lsf_bundle {
    struct lsf_admission admission;
    struct lsf_token tokens[LSF_BUNDLE_ALLOCATIONS];
    unsigned int count, committed;
};

static inline int lsf_scope_equal(struct lsf_scope left, struct lsf_scope right)
{
    unsigned int i;
    for (i = 0; i < 8; ++i)
        if (left.identity[i] != right.identity[i])
            return 0;
    return 1;
}

/* Only the future trusted factory can supply this scope and an already prepaid
 * owner. Matching eight copied words is not authentication of userspace input. */
static inline int lsf_admission_capture(struct lsf_lineage *state, struct lsf_key key,
                                        struct lsf_scope expected,
                                        struct lsf_admission *admission)
{
    struct lsf_owner *owner = lsf_owner_for(state, key);
    if (!admission || !owner || state->poisoned || owner->poisoned ||
        owner->phase != LSF_OPEN || !lsf_scope_equal(owner->scope, expected))
        return 0;
    admission->key = key;
    admission->scope = owner->scope;
    return 1;
}

static inline int lsf_admission_current(struct lsf_lineage *state,
                                        struct lsf_admission admission)
{
    struct lsf_owner *owner = lsf_owner_for(state, admission.key);
    return owner && !state->poisoned && !owner->poisoned &&
        lsf_scope_equal(owner->scope, admission.scope);
}

/* The future source-authenticated allocator layout must supply disjoint actual
 * size-class costs. Wire length/proto->obj_size alone cannot supply this plan.
 * NULL means unknown: refuse before invoking even the first allocator. */
static inline int lsf_bundle_prepare(struct lsf_lineage *state,
                                     struct lsf_admission admission,
                                     struct lsf_token parent,
                                     unsigned int constructor,
                                     const struct lsf_allocation_cost *costs,
                                     unsigned int count, struct lsf_bundle *bundle)
{
    struct lsf_owner *owner;
    lsf_u64 total = 0;
    unsigned int i, empty = 0;
    if (!bundle || !lsf_admission_current(state, admission) || !costs ||
        !count || count > LSF_BUNDLE_ALLOCATIONS)
        return 0;
    /* No header-only SKB plan: both physical records precede either allocator.
     * These shapes do not prove that all other kernel allocations are covered. */
    if (!((constructor == LSF_CONSTRUCT_SOCKET && count == 1 &&
           costs[0].kind == LSF_SOCKET) ||
          (constructor == LSF_CONSTRUCT_TIMEWAIT && count == 1 &&
           costs[0].kind == LSF_TIMEWAIT) ||
          ((constructor == LSF_CONSTRUCT_SKB || constructor == LSF_CONSTRUCT_FCLONE) &&
           count == 2 && costs[1].kind == LSF_SKB_HEAD &&
           costs[0].kind == (constructor == LSF_CONSTRUCT_SKB ?
                            LSF_SKB_HEADER : LSF_SKB_CLONE))))
        return 0;
    owner = lsf_owner_for(state, admission.key);
    for (i = 0; i < count; ++i) {
        if (!lsf_kind_valid(costs[i].kind) || !costs[i].bytes ||
            costs[i].bytes > owner->maximum_bytes ||
            total > owner->maximum_bytes - costs[i].bytes)
            return 0;
        total += costs[i].bytes;
    }
    if (owner->live_bytes > owner->maximum_bytes - total ||
        !state->next_allocation ||
        state->next_allocation > (lsf_u64)-1 - count)
        return 0;
    for (i = 0; i < LSF_ALLOCATION_SLOTS; ++i)
        empty += state->allocations[i].phase == LSF_EMPTY;
    if (empty < count)
        return 0;
    /* Caller holds the same private serialization lock through this function.
     * No allocation, child admission or output escapes until every ticket is
     * reserved. Any unexpected internal failure poisons; it cannot refund. */
    bundle->count = bundle->committed = 0;
    bundle->admission = admission;
    for (i = 0; i < count; ++i) {
        if (!lsf_birth_prepare(state, admission.key, parent,
                               costs[i].kind, costs[i].bytes, &bundle->tokens[i])) {
            owner->poisoned = 1;
            return 0;
        }
        bundle->count++;
    }
    return 1;
}

/* Admission is rechecked after allocation without discarding an original
 * reservation. Failure stays charged/poisoned, never reusable or certified. */
static inline int lsf_bundle_commit(struct lsf_lineage *state, struct lsf_bundle *bundle,
                                    unsigned int index, lsf_u64 address, lsf_u64 cookie)
{
    if (!bundle || !lsf_admission_current(state, bundle->admission) ||
        !bundle->count || bundle->count > LSF_BUNDLE_ALLOCATIONS ||
        index >= bundle->count ||
        index != bundle->committed ||
        bundle->tokens[index].owner != bundle->admission.key.slot ||
        bundle->tokens[index].owner_generation != bundle->admission.key.generation ||
        !lsf_birth_commit(state, &bundle->tokens[index], address, cookie)) {
        state->poisoned = 1;
        return 0;
    }
    bundle->committed++;
    return 1;
}

/* Failure after any allocator entry cannot cancel unused tickets: constructors
 * may have retained allocator/cache/deferred owners not covered by this phase.
 * Complete future allocator coverage is required before a narrower abort fact. */
static inline void lsf_bundle_uncertain(struct lsf_lineage *state,
                                        struct lsf_bundle *bundle)
{
    struct lsf_owner *owner = lsf_owner_for(state, bundle->admission.key);
    if (owner)
        owner->poisoned = 1;
    else
        state->poisoned = 1;
}
#endif
