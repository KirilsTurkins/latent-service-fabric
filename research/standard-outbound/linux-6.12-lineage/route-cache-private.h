/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef LSF_STREAM_ROUTE_CACHE_PRIVATE_H
#define LSF_STREAM_ROUTE_CACHE_PRIVATE_H
struct rtable;
struct lsf_factory_context;
struct lsf_route_cache_owner;
int lsf_factory_route_parent_attach(const void *, const struct lsf_route_cache_owner *);
int lsf_factory_route_cache_publish(struct rtable *, struct rtable __rcu **,
    struct rtable *, unsigned int, unsigned int, unsigned int, struct rtable **);
int lsf_factory_route_current(struct lsf_factory_context *, unsigned int,
    struct rtable **, struct lsf_route_cache_owner *);
int lsf_factory_route_parent_take(const void *, struct lsf_route_cache_owner *);
int lsf_prepaid_route_cache_return(const void *);
void lsf_prepaid_route_cache_drain(struct lsf_factory_context *);
#endif
