/* SPDX-License-Identifier: GPL-2.0-only */
/* Explicit model costs/scope only. No kernel allocator, ABI or authority proof. */
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
#include "admission.h"

static struct lsf_lineage state;
static const struct lsf_scope scope = {{1, 2, 3, 4, 5, 6, 7, 8}};
static const struct lsf_allocation_cost costs[2] = {
    {LSF_SKB_HEADER, 512}, {LSF_SKB_HEAD, 8192}
};
static struct lsf_key fresh(struct lsf_admission *admission)
{
    struct lsf_key key;
    memset(&state, 0, sizeof(state));
    state.next_owner = state.next_allocation = 1;
    assert(lsf_owner_admit(&state, scope, LSF_TCP_BYTES, &key));
    assert(lsf_admission_capture(&state, key, scope, admission));
    return key;
}
static void pass(const char *name)
{
    puts(name);
}

int main(void)
{
    struct lsf_key key, other;
    struct lsf_admission admission, foreign;
    struct lsf_bundle bundle, duplicate;
    struct lsf_token parent, copied;
    struct lsf_scope changed;
    struct lsf_allocation_cost bad[2];
    unsigned int i;

    key = fresh(&admission);
    assert(!lsf_bundle_prepare(&state, admission, lsf_empty_token(),
        LSF_CONSTRUCT_SKB, 0, 2, &bundle));
    assert(!state.owners[key.slot].live_bytes && !state.owners[key.slot].allocations);
    pass("ADMISSION_CONTROL unknown-layout-no-reservation PASS");

    key = fresh(&admission);
    for (i = 0; i < 8; ++i) {
        changed = scope;
        changed.identity[i]++;
        assert(!lsf_admission_capture(&state, key, changed, &foreign));
    }
    foreign = admission;
    foreign.key.generation++;
    assert(!lsf_bundle_prepare(&state, foreign, lsf_empty_token(),
        LSF_CONSTRUCT_SKB, costs, 2, &bundle));
    assert(!state.owners[key.slot].live_bytes);
    pass("ADMISSION_CONTROL full-scope-and-stale-generation-refuse PASS");

    key = fresh(&admission);
    assert(!lsf_bundle_prepare(&state, admission, lsf_empty_token(),
        LSF_CONSTRUCT_SKB, costs, 1, &bundle));
    bad[0] = costs[0]; bad[1] = costs[1]; bad[1].kind = LSF_SKB_HEADER;
    assert(!lsf_bundle_prepare(&state, admission, lsf_empty_token(),
        LSF_CONSTRUCT_SKB, bad, 2, &bundle));
    assert(!state.owners[key.slot].live_bytes);
    pass("ADMISSION_CONTROL skb-requires-two-disjoint-kinds PASS");

    key = fresh(&admission);
    bad[0] = costs[0]; bad[1] = costs[1]; bad[1].bytes = LSF_TCP_BYTES;
    assert(!lsf_bundle_prepare(&state, admission, lsf_empty_token(),
        LSF_CONSTRUCT_SKB, bad, 2, &bundle));
    assert(!state.owners[key.slot].live_bytes && state.next_allocation == 1);
    pass("ADMISSION_CONTROL aggregate-over-cap-is-atomic PASS");

    key = fresh(&admission);
    for (i = 0; i < LSF_ALLOCATION_SLOTS - 1; ++i)
        state.allocations[i].phase = LSF_RESERVED;
    assert(!lsf_bundle_prepare(&state, admission, lsf_empty_token(),
        LSF_CONSTRUCT_SKB, costs, 2, &bundle));
    assert(!state.owners[key.slot].live_bytes && state.next_allocation == 1);
    pass("ADMISSION_CONTROL two-slot-admission-before-first-allocation PASS");

    key = fresh(&admission);
    state.next_allocation = (lsf_u64)-2;
    assert(!lsf_bundle_prepare(&state, admission, lsf_empty_token(),
        LSF_CONSTRUCT_SKB, costs, 2, &bundle));
    assert(!state.owners[key.slot].live_bytes);
    pass("ADMISSION_CONTROL generation-wrap-refuses-before-reservation PASS");

    key = fresh(&admission);
    assert(lsf_bundle_prepare(&state, admission, lsf_empty_token(),
        LSF_CONSTRUCT_SKB, costs, 2, &bundle));
    assert(bundle.count == 2 && !bundle.committed);
    assert(state.owners[key.slot].live_bytes == 8704 && state.owners[key.slot].allocations == 2);
    assert(state.allocations[bundle.tokens[0].slot].phase == LSF_RESERVED);
    assert(state.allocations[bundle.tokens[1].slot].phase == LSF_RESERVED);
    assert(lsf_bundle_commit(&state, &bundle, 0, 100, 0));
    assert(lsf_bundle_commit(&state, &bundle, 1, 200, 0));
    assert(lsf_begin_drain(&state, key));
    copied = lsf_capture_free(&state, LSF_SKB_HEADER, 100, 0);
    assert(lsf_post_free(&state, copied));
    assert(!lsf_mechanism_drained(&state, key));
    copied = lsf_capture_free(&state, LSF_SKB_HEAD, 200, 0);
    assert(lsf_post_free(&state, copied));
    assert(lsf_mechanism_drained(&state, key));
    pass("ADMISSION_CONTROL two-records-stay-charged-through-real-model-free PASS");

    key = fresh(&admission);
    assert(lsf_bundle_prepare(&state, admission, lsf_empty_token(),
        LSF_CONSTRUCT_SKB, costs, 2, &bundle));
    assert(lsf_bundle_commit(&state, &bundle, 0, 100, 0));
    lsf_bundle_uncertain(&state, &bundle);
    assert(state.owners[key.slot].poisoned && state.owners[key.slot].live_bytes == 8704);
    assert(state.owners[key.slot].allocations == 2);
    pass("ADMISSION_CONTROL second-allocator-failure-retains-whole-bundle PASS");

    key = fresh(&admission);
    assert(lsf_birth_prepare(&state, key, lsf_empty_token(), LSF_SOCKET, 1024, &parent));
    assert(lsf_birth_commit(&state, &parent, 1, 42));
    assert(lsf_begin_drain(&state, key));
    assert(lsf_bundle_prepare(&state, admission, parent,
        LSF_CONSTRUCT_SKB, costs, 2, &bundle));
    assert(state.owners[key.slot].live_bytes == 9728);
    pass("ADMISSION_CONTROL live-parent-descendant-remains-allowed-during-drain PASS");

    key = fresh(&admission);
    assert(lsf_birth_prepare(&state, key, lsf_empty_token(), LSF_SOCKET, 1024, &parent));
    assert(lsf_birth_commit(&state, &parent, 1, 42));
    copied = lsf_capture_free(&state, LSF_SOCKET, 1, 42);
    assert(copied.generation);
    assert(!lsf_bundle_prepare(&state, admission, parent,
        LSF_CONSTRUCT_SKB, costs, 2, &bundle));
    assert(state.owners[key.slot].live_bytes == 1024);
    pass("ADMISSION_CONTROL sealed-parent-cannot-birth PASS");

    key = fresh(&admission);
    changed = scope; changed.identity[0] = 9;
    assert(lsf_owner_admit(&state, changed, LSF_TCP_BYTES, &other));
    assert(lsf_birth_prepare(&state, other, lsf_empty_token(), LSF_SOCKET, 1024, &parent));
    assert(lsf_birth_commit(&state, &parent, 1, 42));
    assert(!lsf_bundle_prepare(&state, admission, parent,
        LSF_CONSTRUCT_SKB, costs, 2, &bundle));
    assert(!state.owners[key.slot].live_bytes);
    pass("ADMISSION_CONTROL foreign-parent-does-not-transfer-credit PASS");

    key = fresh(&admission);
    assert(lsf_bundle_prepare(&state, admission, lsf_empty_token(),
        LSF_CONSTRUCT_SKB, costs, 2, &bundle));
    duplicate = bundle;
    assert(lsf_bundle_commit(&state, &bundle, 0, 100, 0));
    assert(!lsf_bundle_commit(&state, &duplicate, 0, 100, 0));
    assert(state.poisoned && state.owners[key.slot].live_bytes == 8704);
    pass("ADMISSION_CONTROL copied-ticket-is-not-a-second-commit PASS");

    key = fresh(&admission);
    changed = scope; changed.identity[0] = 9;
    assert(lsf_owner_admit(&state, changed, LSF_TCP_BYTES, &other));
    assert(lsf_admission_capture(&state, other, changed, &foreign));
    assert(lsf_bundle_prepare(&state, admission, lsf_empty_token(),
        LSF_CONSTRUCT_SKB, costs, 2, &bundle));
    assert(lsf_bundle_prepare(&state, foreign, lsf_empty_token(),
        LSF_CONSTRUCT_SKB, costs, 2, &duplicate));
    bundle.tokens[0] = duplicate.tokens[0];
    assert(!lsf_bundle_commit(&state, &bundle, 0, 100, 0));
    assert(state.poisoned && state.owners[key.slot].live_bytes == 8704);
    assert(state.owners[other.slot].live_bytes == 8704);
    assert(state.allocations[duplicate.tokens[0].slot].phase == LSF_RESERVED);
    pass("ADMISSION_CONTROL foreign-reservation-cannot-commit-under-another-scope PASS");

    key = fresh(&admission);
    assert(lsf_bundle_prepare(&state, admission, lsf_empty_token(),
        LSF_CONSTRUCT_SKB, costs, 2, &bundle));
    bundle.count = LSF_BUNDLE_ALLOCATIONS + 1;
    assert(!lsf_bundle_commit(&state, &bundle, LSF_BUNDLE_ALLOCATIONS, 100, 0));
    assert(state.poisoned && state.owners[key.slot].live_bytes == 8704);
    pass("ADMISSION_CONTROL malformed-bundle-never-indexes-outside-fixed-tickets PASS");
    puts("ADMISSION_SUMMARY 14 PASS; linux-executed=false; final-free-certified=false");
    return 0;
}
