/* SPDX-License-Identifier: GPL-2.0-only */
/* Native mechanism controls, not Linux execution or an installation proof. */
#ifdef LSF_FREESTANDING_REFERENCE
#include "reference-io.h"
#else
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <assert.h>
#include <stdio.h>
#include <string.h>
#endif
#include "lineage.h"

static struct lsf_lineage state;
static struct lsf_scope scope = {{1, 2, 3, 4, 5, 6, 7, 8}};

static struct lsf_key fresh(void)
{
    struct lsf_key key;
    memset(&state, 0, sizeof(state));
    state.next_owner = state.next_allocation = 1;
    assert(lsf_owner_admit(&state, scope, LSF_TCP_BYTES, &key));
    return key;
}

static struct lsf_token birth(struct lsf_key key, struct lsf_token parent,
                              unsigned int kind, lsf_u64 address, lsf_u64 cookie,
                              lsf_u64 bytes)
{
    struct lsf_token token;
    assert(lsf_birth_prepare(&state, key, parent, kind, bytes, &token));
    assert(lsf_birth_commit(&state, &token, address, cookie));
    return token;
}

static struct lsf_token capture(struct lsf_token token)
{
    struct lsf_token copied = lsf_capture_free(&state, token.kind, token.address, token.cookie);
    assert(copied.generation == token.generation);
    return copied;
}

static void drop(struct lsf_token token)
{
    assert(lsf_post_free(&state, capture(token)));
}

static void one(const char *name)
{
    printf("LINEAGE_CONTROL %s PASS\n", name);
}

int main(void)
{
    struct lsf_key key, foreign;
    struct lsf_token parent, child, data, pending, copied, replacement;
    unsigned int i;

    key = fresh();
    parent = birth(key, lsf_empty_token(), LSF_SOCKET, 1, 42, 4096);
    assert(lsf_begin_drain(&state, key));
    copied = capture(parent);
    assert(!lsf_mechanism_drained(&state, key));
    assert(state.owners[key.slot].live_bytes == 4096);
    assert(lsf_post_free(&state, copied));
    assert(lsf_mechanism_drained(&state, key));
    one("pre-free-does-not-refund");

    key = fresh();
    parent = birth(key, lsf_empty_token(), LSF_SOCKET, 1, 42, 4096);
    assert(lsf_begin_drain(&state, key));
    child = birth(key, parent, LSF_TIMEWAIT, 2, 42, 256);
    drop(parent);
    assert(!lsf_mechanism_drained(&state, key));
    data = birth(key, child, LSF_SKB_HEAD, 3, 42, 8192);
    drop(child);
    assert(!lsf_mechanism_drained(&state, key));
    drop(data);
    assert(lsf_mechanism_drained(&state, key));
    one("deferred-descendants-after-close");

    key = fresh();
    assert(lsf_birth_prepare(&state, key, lsf_empty_token(), LSF_SOCKET, 512, &pending));
    assert(lsf_begin_drain(&state, key));
    assert(!lsf_mechanism_drained(&state, key));
    assert(lsf_birth_commit(&state, &pending, 1, 42));
    drop(pending);
    assert(lsf_mechanism_drained(&state, key));
    one("pending-preallocation-survives-drain");

    key = fresh();
    parent = birth(key, lsf_empty_token(), LSF_SOCKET, 1, 42, 4096);
    assert(lsf_begin_drain(&state, key));
    assert(!lsf_capture_free(&state, LSF_SOCKET, 1, 43).generation);
    assert(!lsf_mechanism_drained(&state, key));
    assert(state.owners[key.slot].live_bytes == 4096);
    one("wrong-cookie-retains-owner");

    key = fresh();
    parent = birth(key, lsf_empty_token(), LSF_SOCKET, 1, 42, 4096);
    copied = capture(parent);
    assert(lsf_post_free(&state, copied));
    replacement = birth(key, lsf_empty_token(), LSF_SOCKET, 1, 43, 4096);
    assert(replacement.generation != copied.generation);
    assert(!lsf_post_free(&state, copied));
    assert(state.owners[key.slot].live_bytes == 4096);
    one("stale-free-cannot-retire-reused-address");

    key = fresh();
    parent = birth(key, lsf_empty_token(), LSF_SOCKET, 1, 42, 4096);
    copied = capture(parent);
    assert(lsf_birth_prepare(&state, key, lsf_empty_token(), LSF_SOCKET, 4096, &pending));
    assert(!lsf_birth_commit(&state, &pending, 1, 43));
    assert(!lsf_mechanism_drained(&state, key));
    assert(state.poisoned && copied.generation);
    one("reuse-before-post-free-is-unknown");

    key = fresh();
    parent = birth(key, lsf_empty_token(), LSF_SOCKET, 1, 42, LSF_TCP_BYTES);
    assert(!lsf_birth_prepare(&state, key, parent, LSF_SKB_HEADER, 1, &pending));
    assert(state.owners[key.slot].live_bytes == LSF_TCP_BYTES);
    assert(state.owners[key.slot].allocations == 1);
    one("original-96k-refuses-before-next-allocation");

    key = fresh();
    for (i = 1; i < LSF_OWNER_SLOTS; ++i)
        assert(lsf_owner_admit(&state, scope, LSF_DNS_BYTES, &foreign));
    assert(!lsf_owner_admit(&state, scope, LSF_DNS_BYTES, &foreign));
    assert(state.poisoned);
    one("owner-table-never-grows-or-evicts");

    key = fresh();
    for (i = 0; i < LSF_ALLOCATION_SLOTS; ++i)
        (void)birth(key, lsf_empty_token(), LSF_SKB_HEADER, i + 1, 0, 1);
    assert(!lsf_birth_prepare(&state, key, lsf_empty_token(), LSF_SKB_HEADER, 1, &pending));
    assert(state.owners[key.slot].allocations == LSF_ALLOCATION_SLOTS);
    assert(state.owners[key.slot].live_bytes == LSF_ALLOCATION_SLOTS);
    one("allocation-table-exhaustion-is-sticky");

    key = fresh();
    parent = birth(key, lsf_empty_token(), LSF_SOCKET, 1, 42, 4096);
    assert(lsf_begin_drain(&state, key));
    drop(parent);
    assert(lsf_mechanism_drained(&state, key));
    lsf_observation_lost(&state);
    assert(!lsf_mechanism_drained(&state, key));
    one("loss-poisons-even-empty-owner");

    key = fresh();
    parent = birth(key, lsf_empty_token(), LSF_SOCKET, 1, 42, 4096);
    copied = capture(parent);
    assert(!lsf_birth_prepare(&state, key, parent, LSF_TIMEWAIT, 128, &pending));
    assert(!lsf_mechanism_drained(&state, key));
    assert(copied.generation);
    one("per-allocation-seal-refuses-unaccountable-late-child");

    key = fresh();
    parent = birth(key, lsf_empty_token(), LSF_SOCKET, 1, 42, 4096);
    assert(lsf_owner_admit(&state, scope, LSF_TCP_BYTES, &foreign));
    assert(!lsf_birth_prepare(&state, foreign, parent, LSF_TIMEWAIT, 128, &pending));
    assert(state.owners[foreign.slot].poisoned && state.owners[key.slot].live_bytes == 4096);
    one("foreign-lineage-is-not-adopted");

    key = fresh();
    state.next_allocation = (lsf_u64)-1;
    assert(!lsf_birth_prepare(&state, key, lsf_empty_token(), LSF_SOCKET, 128, &pending));
    assert(state.owners[key.slot].poisoned);
    one("generation-wrap-never-reuses-token");

    key = fresh();
    parent = birth(key, lsf_empty_token(), LSF_SKB_HEAD, 1, 0, 4096);
    assert(lsf_begin_drain(&state, key));
    lsf_unproved_allocation(&state, 1);
    drop(parent);
    assert(!lsf_mechanism_drained(&state, key));
    one("fragment-recycle-is-not-final-free");

    key = fresh();
    parent = birth(key, lsf_empty_token(), LSF_SOCKET, 1, 42, 4096);
    copied = capture(parent);
    assert(!lsf_capture_free(&state, LSF_SOCKET, 1, 42).generation);
    assert(state.owners[key.slot].poisoned && copied.generation);
    one("duplicate-capture-keeps-poisoned-charge");

    key = fresh();
    parent = birth(key, lsf_empty_token(), LSF_SOCKET, 1, 42, 4096);
    assert(lsf_begin_drain(&state, key));
    drop(parent);
    assert(lsf_mechanism_drained(&state, key));
    assert(!lsf_capture_free(&state, LSF_SKB_HEAD, 999, 0).generation);
    assert(state.poisoned && !lsf_mechanism_drained(&state, key));
    one("unclassified-event-never-proves-absence");

    printf("LINEAGE_SIZE %zu\n", sizeof(state));
    puts("LINEAGE_SUMMARY 16 PASS; kernel-built=false; final-free-certified=false");
    return 0;
}
