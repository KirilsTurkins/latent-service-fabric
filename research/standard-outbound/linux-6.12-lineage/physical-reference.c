/* SPDX-License-Identifier: GPL-2.0-only */
/* Supplementary consistency controls. All geometry/origin/cookie/allocator/
 * spinlock inputs are explicit model doubles, never a trusted Linux profile. */
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
#include <stdint.h>
static unsigned int lock_depth;
static void model_lock(int *lock, unsigned long *flags)
{
    (void)lock; *flags = 0; assert(!lock_depth); ++lock_depth;
}
static void model_unlock(int *lock, unsigned long flags)
{
    (void)lock; (void)flags; assert(lock_depth == 1); --lock_depth;
}
#define CONFIG_LSF_STREAM_LINEAGE 1
#include "kernel-hooks.c"
#include "constructor-hooks.c"
#include "physical-hooks.c"

static struct lsf_key key;
static struct lsf_admission admission;
static struct lsf_token parent;
static const struct lsf_scope scope = {{1, 2, 3, 4, 5, 6, 7, 8}};
static const struct lsf_extent_geometry model_geometry = {
    .ownership = LSF_EXTENT_EXCLUSIVE, .head_classes = 4,
    .alignment = 64, .shared_info = 320,
    .socket = {512, 8192}, .timewait = {256, 4096},
    .header = {256, 4096}, .fclone = {1024, 8192},
    .head = {{512, 4096}, {2048, 4096}, {8192, 8192}, {32768, 32768}}
};

static void reset(lsf_u64 ceiling)
{
    memset(&lsf_stream_state, 0, sizeof(lsf_stream_state));
    lsf_stream_state.next_owner = lsf_stream_state.next_allocation = 1;
    lock_depth = 0;
    assert(lsf_owner_admit(&lsf_stream_state, scope, ceiling, &key));
    assert(lsf_admission_capture(&lsf_stream_state, key, scope, &admission));
    parent = lsf_empty_token();
}
static void parent_socket(void)
{
    struct lsf_bundle bundle;
    assert(lsf_physical_prepare(&lsf_stream_state, admission, parent, LSF_PLAN_FACTORY,
        &model_geometry, LSF_CONSTRUCT_SOCKET, 512, &bundle));
    assert(bundle.count == 1);
    assert(lsf_bundle_commit(&lsf_stream_state, &bundle, 0, 0x1000, 101));
    parent = bundle.tokens[0];
}
#if !defined(LSF_OLD_SIZE_REFERENCE) && !defined(LSF_OLD_RETURN_REFERENCE)
static void passed(const char *label)
{
    lsf_ref_write("PHYSICAL_CONTROL ", 17);
    lsf_ref_write(label, lsf_ref_length(label));
    lsf_ref_write(" PASS\n", 6);
}
#endif

int main(void)
{
    struct lsf_bundle bundle;
    struct lsf_token token;
    (void)bundle;
#ifdef LSF_OLD_SIZE_REFERENCE
    struct lsf_allocation_cost old[2] = {{LSF_SKB_HEADER, 256}, {LSF_SKB_HEAD, 16384}};
    reset(LSF_DNS_BYTES);
    parent_socket();
    assert(lsf_birth_prepare(&lsf_stream_state, key, parent, LSF_SKB_HEAD, 40000, &token));
    assert(lsf_bundle_prepare(&lsf_stream_state, admission, parent, LSF_CONSTRUCT_SKB,
        old, 2, &bundle));
    fputs("PHYSICAL_OLD_REQUESTED_BYTES_UNDERSTATE_EXTENTS\n", stderr);
    return 2;
#elif defined(LSF_OLD_RETURN_REFERENCE)
    reset(LSF_TCP_BYTES);
    parent_socket();
    token = lsf_stream_before_free(LSF_SOCKET, (void *)(uintptr_t)0x1000, 101);
    lsf_stream_after_free(token);
    assert(!lsf_stream_state.owners[key.slot].live_bytes);
    fputs("PHYSICAL_OLD_SLOT_RETURN_REFUNDS_LIVE_BACKING\n", stderr);
    return 2;
#else
    struct lsf_physical_plan plan;
    struct lsf_extent_geometry geometry;
    struct lsf_admission changed;
    struct lsf_key foreign;
    struct lsf_scope other = {{11, 12, 13, 14, 15, 16, 17, 18}};
    lsf_u64 before, generation;
    unsigned int i, kind;
    reset(LSF_TCP_BYTES);
    parent_socket();
    assert(parent.bytes == 8192 && lsf_stream_state.owners[key.slot].live_bytes == 8192);
    passed("whole-socket-backing-not-object-size");

    assert(lsf_physical_plan(&model_geometry, LSF_CONSTRUCT_SKB, 1000, &plan));
    assert(plan.count == 2 && plan.costs[0].kind == LSF_SKB_HEADER &&
        plan.costs[0].bytes == 4096 && plan.costs[1].kind == LSF_SKB_HEAD &&
        plan.costs[1].bytes == 4096 && plan.total == 8192);
    passed("shared-info-and-rounding-inside-one-data-extent");
    assert(lsf_physical_plan(&model_geometry, LSF_CONSTRUCT_FCLONE, 1000, &plan));
    assert(plan.count == 2 && plan.costs[0].kind == LSF_SKB_CLONE &&
        plan.costs[0].bytes == 8192 && plan.total == 12288);
    passed("two-fclone-views-one-physical-header");

    reset(LSF_DNS_BYTES);
    parent_socket();
    assert(lsf_birth_prepare(&lsf_stream_state, key, parent, LSF_SKB_HEAD, 40000, &token));
    before = lsf_stream_state.owners[key.slot].live_bytes;
    generation = lsf_stream_state.next_allocation;
    assert(!lsf_physical_prepare(&lsf_stream_state, admission, parent, LSF_PLAN_PARENT,
        &model_geometry, LSF_CONSTRUCT_SKB, 16384, &bundle));
    assert(lsf_stream_state.owners[key.slot].live_bytes == before &&
        lsf_stream_state.next_allocation == generation);
    passed("old-request-only-plan-refused-before-any-reservation");

    geometry = model_geometry; geometry.alignment = 3;
    assert(!lsf_physical_plan(&geometry, LSF_CONSTRUCT_SKB, 1, &plan));
    geometry = model_geometry; geometry.shared_info = (lsf_u64)-1;
    assert(!lsf_physical_plan(&geometry, LSF_CONSTRUCT_SKB, 1, &plan));
    assert(!lsf_physical_plan(&model_geometry, LSF_CONSTRUCT_SKB, (lsf_u64)-1, &plan));
    assert(!lsf_physical_plan(&model_geometry, LSF_CONSTRUCT_SKB, 0, &plan));
    passed("alignment-addition-and-zero-size-fail-closed");
    geometry = model_geometry; geometry.head[1].object_bytes = 512;
    assert(!lsf_physical_plan(&geometry, LSF_CONSTRUCT_SKB, 1, &plan));
    geometry = model_geometry; geometry.head[1].backing_bytes = 1;
    assert(!lsf_physical_plan(&geometry, LSF_CONSTRUCT_SKB, 1, &plan));
    assert(!lsf_physical_plan(&model_geometry, LSF_CONSTRUCT_SKB, 32768, &plan));
    geometry = model_geometry; geometry.head_classes = LSF_HEAD_CLASSES + 1;
    assert(!lsf_physical_plan(&geometry, LSF_CONSTRUCT_SKB, 1, &plan));
    passed("unknown-undersized-unsorted-and-uncovered-classes-refused");

    assert(!lsf_physical_plan(0, LSF_CONSTRUCT_SOCKET, 512, &plan));
    geometry = model_geometry; geometry.ownership = LSF_EXTENT_SHARED;
    assert(!lsf_physical_plan(&geometry, LSF_CONSTRUCT_SOCKET, 512, &plan));
    geometry.ownership = LSF_EXTENT_UNKNOWN;
    assert(!lsf_physical_plan(&geometry, LSF_CONSTRUCT_SOCKET, 512, &plan));
    passed("shared-slab-and-unknown-geometry-not-certified-by-object-size");
    reset(LSF_TCP_BYTES);
    for (i = LSF_PLAN_PRELOOKUP_RX; i <= LSF_PLAN_SHARED_CACHE; ++i)
        assert(!lsf_physical_prepare(&lsf_stream_state, admission, parent, i,
            &model_geometry, LSF_CONSTRUCT_SOCKET, 512, &bundle));
    assert(!lsf_physical_prepare(&lsf_stream_state, admission, parent, LSF_PLAN_UNKNOWN,
        &model_geometry, LSF_CONSTRUCT_SOCKET, 512, &bundle));
    assert(!lsf_stream_state.owners[key.slot].live_bytes && lsf_stream_state.next_allocation == 1);
    passed("before-socket-lookup-and-cache-origin-cannot-borrow-later-authority");

    for (i = 0; i < 8; ++i) {
        reset(LSF_TCP_BYTES); parent_socket();
        before = lsf_stream_state.owners[key.slot].live_bytes;
        changed = admission; changed.scope.identity[i]++;
        assert(!lsf_physical_prepare(&lsf_stream_state, changed, parent, LSF_PLAN_PARENT,
            &model_geometry, LSF_CONSTRUCT_SKB, 1, &bundle));
        assert(lsf_stream_state.owners[key.slot].live_bytes == before);
    }
    passed("all-eight-original-scope-words-required");
    reset(LSF_TCP_BYTES); parent_socket();
    assert(lsf_owner_admit(&lsf_stream_state, other, LSF_TCP_BYTES, &foreign));
    changed = admission; changed.key = foreign; changed.scope = other;
    assert(!lsf_physical_prepare(&lsf_stream_state, changed, parent, LSF_PLAN_PARENT,
        &model_geometry, LSF_CONSTRUCT_SKB, 1, &bundle));
    assert(!lsf_stream_state.owners[foreign.slot].live_bytes);
    passed("foreign-owner-cannot-adopt-parent-extent");

    reset(LSF_TCP_BYTES); parent_socket();
    assert(lsf_begin_drain(&lsf_stream_state, key));
    assert(lsf_physical_prepare(&lsf_stream_state, admission, parent, LSF_PLAN_PARENT,
        &model_geometry, LSF_CONSTRUCT_TIMEWAIT, 256, &bundle));
    assert(bundle.count == 1 && bundle.tokens[0].bytes == 4096);
    passed("draining-live-parent-still-prepays-timewait-descendant");
    reset(LSF_TCP_BYTES); parent_socket();
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i)
        assert(lsf_birth_prepare(&lsf_stream_state, key, parent, LSF_SKB_HEAD, 1, &token));
    generation = lsf_stream_state.next_allocation;
    before = lsf_stream_state.owners[key.slot].live_bytes;
    assert(!lsf_physical_prepare(&lsf_stream_state, admission, parent, LSF_PLAN_PARENT,
        &model_geometry, LSF_CONSTRUCT_SKB, 1, &bundle));
    assert(lsf_stream_state.next_allocation == generation &&
        lsf_stream_state.owners[key.slot].live_bytes == before);
    passed("fixed-slot-exhaustion-precedes-first-bundle-reservation");

    for (kind = LSF_SOCKET; kind <= LSF_SKB_HEAD; ++kind) {
        reset(LSF_TCP_BYTES);
        assert(lsf_birth_prepare(&lsf_stream_state, key, parent, kind, 4096, &token));
        assert(lsf_birth_commit(&lsf_stream_state, &token, 0x2000, 202));
        token = lsf_stream_before_free(kind, (void *)(uintptr_t)0x2000, 202);
        lsf_stream_allocator_returned(token);
        assert(lsf_stream_state.allocations[token.slot].phase == LSF_PHYSICAL_HELD);
        assert(lsf_stream_state.owners[key.slot].live_bytes == 4096 &&
            lsf_stream_state.owners[key.slot].allocations == 1);
        assert(!lsf_mechanism_drained(&lsf_stream_state, key));
    }
    passed("all-five-object-returns-retain-original-backing-charge");
    lsf_stream_allocator_returned(token);
    assert(lsf_stream_state.poisoned && lsf_stream_state.owners[key.slot].live_bytes == 4096);
    passed("duplicate-slot-return-poisons-without-refund");
    reset(LSF_TCP_BYTES); parent_socket();
    token = lsf_stream_before_free(LSF_SOCKET, (void *)(uintptr_t)0x1000, 101);
    lsf_stream_allocator_returned(token);
    assert(!lsf_post_free(&lsf_stream_state, token));
    assert(lsf_stream_state.owners[key.slot].live_bytes == 8192);
    passed("historical-object-free-model-cannot-release-held-extent");
    reset(LSF_TCP_BYTES); parent_socket();
    token = lsf_stream_before_free(LSF_SOCKET, (void *)(uintptr_t)0x1000, 101);
    lsf_stream_allocator_returned(token);
    token.generation++;
    lsf_stream_allocator_returned(token);
    assert(lsf_stream_state.poisoned && lsf_stream_state.owners[key.slot].live_bytes == 8192);
    passed("stale-generation-cannot-release-held-original");
    reset(LSF_TCP_BYTES); parent_socket();
    before = lsf_stream_state.owners[key.slot].live_bytes;
    lsf_stream_unproved_fragment((void *)(uintptr_t)0x1000);
    assert(lsf_stream_state.owners[key.slot].poisoned &&
        lsf_stream_state.owners[key.slot].live_bytes == before);
    passed("unproved-fragment-retains-original-no-page-return-certificate");
    reset(LSF_TCP_BYTES);
    assert(!lsf_stream_constructor_prepare(LSF_CONSTRUCT_SOCKET, 0, 512, 0, 0, 0, &bundle));
    assert(!lsf_stream_state.owners[key.slot].live_bytes && lsf_stream_state.next_allocation == 1);
    passed("actual-constructor-still-refuses-missing-trusted-layout-and-factory");
    puts("PHYSICAL_SCOPE linux-executed=false; layout-authenticated=false; factory=false; final-free-certified=false");
    return 0;
#endif
}
