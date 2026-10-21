/* SPDX-License-Identifier: GPL-2.0-only */
/* Supplemental arithmetic/lifetime mechanism only. No kernel execution. */
#include "reference-io.h"
#include "prepaid.h"
static struct lsf_prepaid pool;
static struct lsf_scope scope = {{1, 2, 3, 4, 5, 6, 7, 8}};
static struct lsf_prepaid_ticket no_parent;
static struct lsf_prepaid_key key;

static void reset(void)
{
    memset(&pool, 0, sizeof(pool));
    assert(lsf_prepaid_initialize(&pool));
    assert(lsf_prepaid_context_create(&pool, scope, LSF_TCP_BYTES, &key));
}
static void passed(const char *label)
{
    lsf_ref_write("PREPAID_CONTROL ", 16);
    lsf_ref_write(label, lsf_ref_length(label));
    lsf_ref_write(" PASS\n", 6);
}

int main(void)
{
    struct lsf_prepaid_ticket first, second, bad;
    struct lsf_prepaid_key other, successor;
    struct lsf_scope foreign = scope;
    lsf_u64 offset;
    unsigned int i;
    reset();
    assert(pool.records[0].phase == LSF_PREPAID_LIVE);
    assert(pool.records[0].bytes == LSF_BACKING_BYTES);
    assert(!lsf_prepaid_initialize(&pool));
    passed("backing-counts-in-original-record-bound");

    reset();
    assert(lsf_prepaid_context_create(&pool, scope, LSF_TCP_BYTES, &other));
    assert(other.slot == 1);
    assert(!lsf_prepaid_context_create(&pool, scope, LSF_TCP_BYTES, &successor));
    assert(lsf_prepaid_context_create(&pool, scope, LSF_DNS_BYTES, &other));
    assert(other.slot == 2);
    assert(lsf_prepaid_context_create(&pool, scope, LSF_DNS_BYTES, &other));
    assert(other.slot == 3);
    assert(!lsf_prepaid_context_create(&pool, scope, LSF_DNS_BYTES, &other));
    passed("two-independent-tcp-and-dns-partitions");

    reset();
    assert(lsf_prepaid_start(1) + LSF_TCP_BYTES == lsf_prepaid_start(2));
    assert(lsf_prepaid_start(3) + LSF_DNS_BYTES == LSF_FACTORY_INFRA_OFFSET);
    assert(LSF_FACTORY_INFRA_OFFSET + LSF_FACTORY_INFRA_BYTES == LSF_BACKING_BYTES);
    passed("infrastructure-does-not-enlarge-occupancy");

    reset();
    assert(!lsf_prepaid_context_create(&pool, scope, 98305, &other));
    foreign.identity[7] = 0;
    assert(!lsf_prepaid_context_create(&pool, foreign, LSF_DNS_BYTES, &other));
    passed("unknown-budget-and-missing-scope-refused");

    reset();
    assert(lsf_prepaid_allocate(&pool, key, 1, 0, no_parent, &first, &offset));
    assert(offset == 0 && pool.records[first.slot].bytes == 64);
    assert(lsf_prepaid_allocate(&pool, key, 65, 0, no_parent, &second, &offset));
    assert(offset == 64 && pool.records[second.slot].bytes == 128);
    passed("disjoint-rounded-backing-views");

    reset();
    assert(!lsf_prepaid_allocate(&pool, key, 0, 0, no_parent, &first, &offset));
    assert(!lsf_prepaid_allocate(&pool, key, (lsf_u64)-1, 0, no_parent, &first, &offset));
    assert(!lsf_prepaid_allocate(&pool, key, LSF_TCP_BYTES + 1, 0, no_parent, &first, &offset));
    assert(!lsf_prepaid_allocate(&pool, key, 64, 2, no_parent, &first, &offset));
    assert(!pool.contexts[key.slot].cursor);
    passed("overflow-and-unknown-shape-before-allocation");

    reset();
    assert(lsf_prepaid_allocate(&pool, key, LSF_TCP_BYTES, 0, no_parent, &first, &offset));
    assert(!lsf_prepaid_allocate(&pool, key, 1, 0, no_parent, &second, &offset));
    passed("original-tcp-ceiling-hard-refusal");

    reset();
    assert(lsf_prepaid_context_create(&pool, scope, LSF_DNS_BYTES, &other));
    assert(lsf_prepaid_allocate(&pool, other, LSF_DNS_BYTES, 0, no_parent, &first, &offset));
    assert(!lsf_prepaid_allocate(&pool, other, 1, 0, no_parent, &second, &offset));
    assert(offset == 2u * LSF_TCP_BYTES);
    passed("original-dns-ceiling-hard-refusal");

    reset();
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i)
        assert(lsf_prepaid_allocate(&pool, key, 1, 0, no_parent, &first, &offset));
    assert(!lsf_prepaid_allocate(&pool, key, 1, 0, no_parent, &second, &offset));
    passed("backing-plus-255-views-no-second-table");

    reset();
    pool.contexts[key.slot].closed = 1;
    assert(!lsf_prepaid_allocate(&pool, key, 64, 0, no_parent, &first, &offset));
    passed("close-fences-new-roots");

    reset();
    assert(lsf_prepaid_allocate(&pool, key, 64, 0, no_parent, &first, &offset));
    pool.contexts[key.slot].closed = 1;
    assert(lsf_prepaid_allocate(&pool, key, 64, 1, first, &second, &offset));
    passed("draining-live-parent-may-create-child");

    reset();
    assert(lsf_prepaid_allocate(&pool, key, 64, 0, no_parent, &first, &offset));
    assert(lsf_prepaid_context_create(&pool, scope, LSF_TCP_BYTES, &other));
    assert(!lsf_prepaid_allocate(&pool, other, 64, 1, first, &second, &offset));
    bad = first;
    bad.generation++;
    assert(!lsf_prepaid_allocate(&pool, key, 64, 1, bad, &second, &offset));
    passed("foreign-and-stale-parent-refused");

    reset();
    assert(lsf_prepaid_allocate(&pool, key, LSF_TCP_BYTES, 0, no_parent, &first, &offset));
    assert(lsf_prepaid_return(&pool, key, first));
    assert(pool.records[0].bytes == LSF_BACKING_BYTES);
    assert(pool.records[0].phase == LSF_PREPAID_LIVE);
    assert(!lsf_prepaid_allocate(&pool, key, 1, 0, no_parent, &second, &offset));
    passed("return-never-refunds-backing-or-reuses-live-arena");

    reset();
    assert(lsf_prepaid_allocate(&pool, key, 64, 0, no_parent, &first, &offset));
    assert(lsf_prepaid_return(&pool, key, first));
    assert(!lsf_prepaid_return(&pool, key, first));
    assert(pool.contexts[key.slot].poisoned);
    passed("duplicate-return-poisons-original");

    reset();
    assert(lsf_prepaid_allocate(&pool, key, 64, 0, no_parent, &first, &offset));
    assert(lsf_prepaid_continuation(&pool, key, 1));
    pool.contexts[key.slot].closed = 1;
    assert(lsf_prepaid_return(&pool, key, first));
    assert(!lsf_prepaid_recycle(&pool, key));
    assert(lsf_prepaid_continuation(&pool, key, 0));
    assert(lsf_prepaid_recycle(&pool, key));
    passed("actual-deferred-owner-prevents-recycle");

    reset();
    assert(lsf_prepaid_allocate(&pool, key, 64, 0, no_parent, &first, &offset));
    assert(!lsf_prepaid_recycle(&pool, key));
    pool.contexts[key.slot].closed = 1;
    assert(!lsf_prepaid_recycle(&pool, key));
    assert(lsf_prepaid_return(&pool, key, first));
    assert(lsf_prepaid_recycle(&pool, key));
    assert(lsf_prepaid_context_create(&pool, scope, LSF_TCP_BYTES, &successor));
    assert(successor.slot == key.slot && successor.generation != key.generation);
    assert(!lsf_prepaid_allocate(&pool, key, 64, 0, no_parent, &second, &offset));
    passed("sealed-empty-generation-recycle-not-final-free");

    reset();
    assert(lsf_prepaid_allocate(&pool, key, 64, 0, no_parent, &first, &offset));
    for (i = 0; i < LSF_ALLOCATION_SLOTS; ++i)
        assert(lsf_prepaid_continuation(&pool, key, 1));
    assert(!lsf_prepaid_continuation(&pool, key, 1));
    assert(!lsf_prepaid_continuation(&pool, key, 2));
    passed("finite-continuation-counter-no-hidden-work");

    reset();
    pool.next_generation = (lsf_u64)-1;
    assert(!lsf_prepaid_allocate(&pool, key, 64, 0, no_parent, &first, &offset));
    assert(!lsf_prepaid_context_create(&pool, scope, LSF_TCP_BYTES, &other));
    passed("nonwrapping-allocation-and-owner-generations");

    reset();
    pool.stopped = 1;
    assert(!lsf_prepaid_allocate(&pool, key, 64, 0, no_parent, &first, &offset));
    assert(!lsf_prepaid_context_create(&pool, scope, LSF_DNS_BYTES, &other));
    assert(pool.records[0].phase == LSF_PREPAID_LIVE);
    passed("stop-retains-backing-and-fences-roots");

    memset(&pool, 0, sizeof(pool));
    pool.records[255].phase = LSF_PREPAID_RETURNED;
    assert(!lsf_prepaid_initialize(&pool));
    memset(&pool, 0, sizeof(pool));
    pool.contexts[63].generation = 1;
    assert(!lsf_prepaid_initialize(&pool));
    passed("dirty-state-cannot-bootstrap");
    return 0;
}
