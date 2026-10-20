/* SPDX-License-Identifier: GPL-2.0-only */
/* Private affine initialization handoff, not a factory or kernel certificate. */
#ifndef LSF_STREAM_HANDOFF_H
#define LSF_STREAM_HANDOFF_H
#ifdef __KERNEL__
#include <net/lsf_stream_admission.h>
#else
#include "admission.h"
#endif

struct lsf_handoff {
    struct lsf_admission admission;
    struct lsf_token token;
};

/* The object is allocated, but no initialized cookie may be read here. The
 * original RESERVED record itself carries the address through constructor
 * return. No second table, allocation, owner, charge or LIVE transition. */
static inline int lsf_socket_bind_reserved(struct lsf_lineage *state,
                                           struct lsf_bundle *bundle,
                                           lsf_u64 address)
{
    struct lsf_allocation *allocation;
    struct lsf_token *token;
    unsigned int i;
    if (!bundle || !lsf_admission_current(state, bundle->admission) ||
        bundle->count != 1 || bundle->committed || !address)
        goto invalid;
    token = &bundle->tokens[0];
    if (token->kind != LSF_SOCKET || token->address || token->cookie ||
        token->owner != bundle->admission.key.slot ||
        token->owner_generation != bundle->admission.key.generation)
        goto invalid;
    allocation = lsf_allocation_for(state, *token);
    if (!allocation || allocation->phase != LSF_RESERVED)
        goto invalid;
    for (i = 0; i < LSF_ALLOCATION_SLOTS; ++i)
        if (&state->allocations[i] != allocation &&
            state->allocations[i].phase != LSF_EMPTY &&
            state->allocations[i].token.address == address)
            goto invalid;
    token->address = address;
    allocation->token = *token;
    return 1;
invalid:
    state->poisoned = 1;
    return 0;
}

/* Only the exact private constructor calls this while it owns the live object.
 * Copy original admission and token under the lineage lock BEFORE cookie
 * generation. An address supplied by userspace cannot invoke this interface. */
static inline int lsf_socket_capture_handoff(struct lsf_lineage *state,
                                              lsf_u64 address,
                                              struct lsf_handoff *handoff)
{
    unsigned int i;
    if (!address || !handoff || state->poisoned)
        goto invalid;
    for (i = 0; i < LSF_ALLOCATION_SLOTS; ++i) {
        struct lsf_allocation *allocation = &state->allocations[i];
        struct lsf_token token = allocation->token;
        struct lsf_key key = {token.owner, token.owner_generation};
        struct lsf_owner *owner;
        if (allocation->phase == LSF_EMPTY || token.address != address)
            continue;
        owner = lsf_owner_for(state, key);
        if (!owner || owner->poisoned || lsf_allocation_for(state, token) != allocation ||
            allocation->phase != LSF_RESERVED ||
            token.kind != LSF_SOCKET || token.cookie)
            goto invalid;
        handoff->admission.key = key;
        handoff->admission.scope = owner->scope;
        handoff->token = token;
        return 1;
    }
    /* The candidate has no trusted registrar yet. With an empty experiment an
     * unselected constructor supplies no evidence. Once an owner exists, an
     * unclassified initialization must poison, never certify its absence. */
    for (i = 0; i < LSF_OWNER_SLOTS; ++i)
        if (state->owners[i].phase != LSF_UNUSED)
            goto invalid;
    return 0;
invalid:
    state->poisoned = 1;
    return 0;
}

/* The real unchanged sock_gen_cookie implementation supplies cookie. A clone
 * may legitimately inherit a cookie. Address plus original allocation/owner
 * generations distinguish it; no cookie uniqueness or synthetic reset is used.
 * A raced/malformed/stale/foreign/duplicate handoff retains all reservations. */
static inline int lsf_socket_commit_handoff(struct lsf_lineage *state,
                                            struct lsf_handoff *handoff,
                                            lsf_u64 address, lsf_u64 cookie)
{
    struct lsf_allocation *allocation;
    if (!handoff || !lsf_admission_current(state, handoff->admission) ||
        handoff->token.owner != handoff->admission.key.slot ||
        handoff->token.owner_generation != handoff->admission.key.generation ||
        handoff->token.kind != LSF_SOCKET || !address ||
        address != handoff->token.address || !cookie || handoff->token.cookie)
        goto invalid;
    allocation = lsf_allocation_for(state, handoff->token);
    if (!allocation || allocation->phase != LSF_RESERVED ||
        !lsf_birth_commit(state, &handoff->token, address, cookie))
        goto invalid;
    return 1;
invalid:
    state->poisoned = 1;
    return 0;
}
#endif
