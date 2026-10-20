/* SPDX-License-Identifier: GPL-2.0-only */
/* Private consistency mechanism, not a layout/factory authentication API. */
#ifndef LSF_STREAM_PHYSICAL_PLAN_H
#define LSF_STREAM_PHYSICAL_PLAN_H
#ifdef __KERNEL__
#include <net/lsf_stream_admission.h>
#else
#include "admission.h"
#endif

#define LSF_HEAD_CLASSES 16u
/* Additive terminal quarantine state; old core phases and input files stay exact.
 * Old free/parent/slot-reuse predicates all refuse this nonempty, nonlive state. */
enum { LSF_PHYSICAL_HELD = LSF_FREE_CAPTURED + 1 };
enum lsf_plan_origin { LSF_PLAN_UNKNOWN, LSF_PLAN_FACTORY, LSF_PLAN_PARENT,
                       LSF_PLAN_PRELOOKUP_RX, LSF_PLAN_SHARED_CACHE };
enum lsf_extent_ownership { LSF_EXTENT_UNKNOWN, LSF_EXTENT_EXCLUSIVE,
                            LSF_EXTENT_SHARED };
struct lsf_extent_size {
    lsf_u64 object_bytes, backing_bytes;
};
struct lsf_extent_geometry {
    /* A future compiled, source-authenticated layout must supply these facts.
     * This struct is never populated from a caller certificate or operator
     * input. The current actual adapter has NO such layout and refuses.
     * Exclusive means one whole backing extent, not one slot in a shared slab. */
    unsigned int ownership, head_classes;
    lsf_u64 alignment, shared_info;
    struct lsf_extent_size socket, timewait, header, fclone;
    struct lsf_extent_size head[LSF_HEAD_CLASSES];
};
struct lsf_physical_plan {
    struct lsf_allocation_cost costs[LSF_BUNDLE_ALLOCATIONS];
    unsigned int count;
    lsf_u64 total;
};

static inline int lsf_plan_add(lsf_u64 left, lsf_u64 right, lsf_u64 *out)
{
    if (left > (lsf_u64)-1 - right)
        return 0;
    *out = left + right;
    return 1;
}

static inline int lsf_plan_align(lsf_u64 value, lsf_u64 alignment, lsf_u64 *out)
{
    lsf_u64 expanded;
    if (!alignment || (alignment & (alignment - 1)) || alignment > 4096 ||
        !lsf_plan_add(value, alignment - 1, &expanded))
        return 0;
    *out = expanded & ~(alignment - 1);
    return 1;
}

static inline int lsf_extent_size_valid(struct lsf_extent_size size)
{
    return size.object_bytes && size.backing_bytes >= size.object_bytes &&
        size.backing_bytes <= LSF_TCP_BYTES;
}

static inline int lsf_geometry_consistent(const struct lsf_extent_geometry *geometry)
{
    unsigned int i;
    lsf_u64 ignored;
    if (!geometry || geometry->ownership != LSF_EXTENT_EXCLUSIVE ||
        !lsf_plan_align(geometry->shared_info, geometry->alignment, &ignored) ||
        !geometry->shared_info || !geometry->head_classes ||
        geometry->head_classes > LSF_HEAD_CLASSES ||
        !lsf_extent_size_valid(geometry->socket) ||
        !lsf_extent_size_valid(geometry->timewait) ||
        !lsf_extent_size_valid(geometry->header) ||
        !lsf_extent_size_valid(geometry->fclone) ||
        geometry->fclone.object_bytes < geometry->header.object_bytes ||
        geometry->fclone.backing_bytes < geometry->header.backing_bytes)
        return 0;
    for (i = 0; i < geometry->head_classes; ++i) {
        if (!lsf_extent_size_valid(geometry->head[i]) ||
            (i && (geometry->head[i - 1].object_bytes >= geometry->head[i].object_bytes ||
                   geometry->head[i - 1].backing_bytes > geometry->head[i].backing_bytes)))
            return 0;
    }
    return 1;
}

/* A closed disjoint plan for the three existing constructor shapes only.
 * shared_info is INSIDE the data-head extent; fclone's two logical SKBs are
 * INSIDE one physical header block. Neither is an extra charge/refund owner.
 * This checks arithmetic and shape, not authenticity/completeness of geometry.
 * NAPI/page/cache/RX/route/auxiliary origins have no supported plan here. */
static inline int lsf_physical_plan(const struct lsf_extent_geometry *geometry,
                                    unsigned int constructor, lsf_u64 requested,
                                    struct lsf_physical_plan *plan)
{
    struct lsf_extent_size selected;
    lsf_u64 aligned, shared, required;
    unsigned int i;
    if (!plan || !lsf_geometry_consistent(geometry))
        return 0;
    plan->count = 0;
    plan->total = 0;
    if (constructor == LSF_CONSTRUCT_SOCKET || constructor == LSF_CONSTRUCT_TIMEWAIT) {
        selected = constructor == LSF_CONSTRUCT_SOCKET ? geometry->socket : geometry->timewait;
        if (requested != selected.object_bytes)
            return 0;
        plan->costs[0].kind = constructor == LSF_CONSTRUCT_SOCKET ? LSF_SOCKET : LSF_TIMEWAIT;
        plan->costs[0].bytes = selected.backing_bytes;
        plan->count = 1;
        plan->total = selected.backing_bytes;
        return 1;
    }
    if ((constructor != LSF_CONSTRUCT_SKB && constructor != LSF_CONSTRUCT_FCLONE) ||
        !requested || !lsf_plan_align(requested, geometry->alignment, &aligned) ||
        !lsf_plan_align(geometry->shared_info, geometry->alignment, &shared) ||
        !lsf_plan_add(aligned, shared, &required))
        return 0;
    for (i = 0; i < geometry->head_classes; ++i)
        if (geometry->head[i].object_bytes >= required)
            break;
    if (i == geometry->head_classes)
        return 0;
    selected = constructor == LSF_CONSTRUCT_SKB ? geometry->header : geometry->fclone;
    plan->costs[0].kind = constructor == LSF_CONSTRUCT_SKB ? LSF_SKB_HEADER : LSF_SKB_CLONE;
    plan->costs[0].bytes = selected.backing_bytes;
    plan->costs[1].kind = LSF_SKB_HEAD;
    plan->costs[1].bytes = geometry->head[i].backing_bytes;
    if (!lsf_plan_add(plan->costs[0].bytes, plan->costs[1].bytes, &plan->total) ||
        plan->total > LSF_TCP_BYTES)
        return 0;
    plan->count = 2;
    return 1;
}

/* No new table/ledger: reserve the original entire bundle atomically. A
 * factory root is socket-only. Descendants need the original live parent;
 * before-lookup RX/shared caches cannot acquire authority from a later socket. */
static inline int lsf_physical_prepare(struct lsf_lineage *state,
                                       struct lsf_admission admission,
                                       struct lsf_token parent, unsigned int origin,
                                       const struct lsf_extent_geometry *geometry,
                                       unsigned int constructor, lsf_u64 requested,
                                       struct lsf_bundle *bundle)
{
    struct lsf_physical_plan plan;
    if (!((origin == LSF_PLAN_FACTORY && constructor == LSF_CONSTRUCT_SOCKET &&
           !parent.generation) ||
          (origin == LSF_PLAN_PARENT && parent.generation &&
           constructor != LSF_CONSTRUCT_SOCKET)) ||
        !lsf_physical_plan(geometry, constructor, requested, &plan))
        return 0;
    return lsf_bundle_prepare(state, admission, parent, constructor,
                              plan.costs, plan.count, bundle);
}

/* Returning an object to SLUB/kmalloc/NAPI is not backing-page final free.
 * Keep the exact original record charged in a nonreusable PHYSICAL_HELD state.
 * Duplicate return, old model post-free, parent birth and slot reuse all refuse.
 * No later arbitrary
 * notification can release it: a complete private backing producer is absent.
 * The previous lsf_post_free model remains separate/historical, never called
 * by the additive physical-retention recipe at an object-return boundary. */
static inline int lsf_physical_slot_return(struct lsf_lineage *state, struct lsf_token token)
{
    struct lsf_allocation *allocation = lsf_allocation_for(state, token);
    if (state->poisoned || !allocation || allocation->phase != LSF_FREE_CAPTURED ||
        !lsf_owner_for(state, (struct lsf_key){token.owner, token.owner_generation})) {
        state->poisoned = 1;
        return 0;
    }
    allocation->phase = LSF_PHYSICAL_HELD;
    return 1;
}
#endif
