/* SPDX-License-Identifier: GPL-2.0-only */
/* Private scalar metadata in the SAME fixed birth record. References are
 * acquired by actual FIB/NH producers, never supplied through a device API. */
#ifndef LSF_STREAM_ROUTE_CACHE_OWNER_H
#define LSF_STREAM_ROUTE_CACHE_OWNER_H
enum lsf_route_parent_kind { LSF_ROUTE_PARENT_NONE, LSF_ROUTE_PARENT_FIB, LSF_ROUTE_PARENT_NH };
enum lsf_route_cache_kind {
    LSF_ROUTE_CACHE_NONE, LSF_ROUTE_CACHE_INPUT, LSF_ROUTE_CACHE_OUTPUT,
    LSF_ROUTE_CACHE_EXCEPTION_INPUT, LSF_ROUTE_CACHE_EXCEPTION_OUTPUT
};
struct lsf_route_cache_owner {
    lsf_u64 parent, nhc;
    unsigned int parent_kind, nh_index, cache_kind, cpu, daddr;
};
static inline int lsf_route_cache_empty(const struct lsf_route_cache_owner *owner)
{
    return !owner->parent && !owner->nhc && !owner->parent_kind && !owner->nh_index &&
        !owner->cache_kind && !owner->cpu && !owner->daddr;
}
#endif
