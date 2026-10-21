/* SPDX-License-Identifier: GPL-2.0-only */
/* Included AFTER the exact maintained route.c definitions. All parent pointers
 * below denote actual references acquired before private cache publication. */

static void lsf_prepaid_route_parent_put(struct lsf_route_cache_owner owner)
{
    if (owner.parent_kind == LSF_ROUTE_PARENT_FIB)
        fib_info_put((struct fib_info *)(unsigned long)owner.parent);
    else if (owner.parent_kind == LSF_ROUTE_PARENT_NH)
        nexthop_put((struct nexthop *)(unsigned long)owner.parent);
}

static int lsf_prepaid_route_parent_attach(struct rtable *rt,
    const struct fib_result *res, struct fib_info *fi, bool do_cache)
{
    struct lsf_route_cache_owner owner = {0};
    struct fib_nh_common *nhc;
    if (!fi || !do_cache)
        return 0;
    nhc = FIB_RES_NHC(*res);
    if (fi->nh) {
        struct nh_info *info;
        struct nexthop *nh;
        if (nhc->nhc_family != AF_INET)
            return -EOPNOTSUPP;
        info = container_of(nhc, struct nh_info, fib_nhc);
        nh = READ_ONCE(info->nh_parent);
        if (!nh || !nexthop_get(nh))
            return -EAGAIN;
        /* A referenced nexthop does NOT pin its replaceable nh_info. Verify
         * its current identity under the original lookup's RCU read section. */
        if (READ_ONCE(nh->is_group) || rcu_dereference(nh->nh_info) != info) {
            nexthop_put(nh);
            return -EAGAIN;
        }
        owner.parent_kind = LSF_ROUTE_PARENT_NH;
        owner.parent = (lsf_u64)(unsigned long)nh;
    } else {
        if (fi->fib_nh_is_v6 || res->nh_sel >= fi->fib_nhs ||
            nhc != &fi->fib_nh[res->nh_sel].nh_common)
            return -EOPNOTSUPP;
        if (!fib_info_hold_safe(fi))
            return -EAGAIN;
        owner.parent_kind = LSF_ROUTE_PARENT_FIB;
        owner.parent = (lsf_u64)(unsigned long)fi;
        owner.nh_index = res->nh_sel;
    }
    owner.nhc = (lsf_u64)(unsigned long)nhc;
    if (!lsf_factory_route_parent_attach(rt, &owner)) {
        lsf_prepaid_route_parent_put(owner);
        return -EOPNOTSUPP;
    }
    return 0;
}

/* The parent reference is still held by this real dst until its final return.
 * Under RCU, derive the CURRENT cache allocation instead of following saved
 * nh_info, per-CPU-cell or exception addresses. Even an nh_info address ABA
 * cannot turn a freed per-CPU allocation into a dereference. */
static struct fib_nh_common *lsf_prepaid_route_parent_current(
    struct lsf_factory_context *context, const struct lsf_route_cache_owner *owner)
{
    struct fib_nh_common *nhc;
    if (owner->parent_kind == LSF_ROUTE_PARENT_FIB) {
        struct fib_info *fi = (void *)(unsigned long)owner->parent;
        if (fi->nh || fi->fib_nh_is_v6 || owner->nh_index >= fi->fib_nhs)
            goto invalid;
        nhc = &fi->fib_nh[owner->nh_index].nh_common;
    } else if (owner->parent_kind == LSF_ROUTE_PARENT_NH) {
        struct nexthop *nh = (void *)(unsigned long)owner->parent;
        struct nh_info *info;
        if (READ_ONCE(nh->is_group))
            goto invalid;
        info = rcu_dereference(nh->nh_info);
        if (!info || info->family != AF_INET)
            return NULL;
        nhc = &info->fib_nhc;
    } else
        goto invalid;
    if ((lsf_u64)(unsigned long)nhc != owner->nhc)
        return NULL;
    return nhc;
invalid:
    lsf_factory_poison(context);
    return NULL;
}

static void lsf_prepaid_route_cache_detach(struct lsf_factory_context *context,
    struct rtable *rt, const struct lsf_route_cache_owner *owner)
{
    struct fib_nh_common *nhc = lsf_prepaid_route_parent_current(context, owner);
    struct rtable __rcu **cell;
    if (!nhc)
        return;
    if (owner->cache_kind == LSF_ROUTE_CACHE_INPUT || owner->cache_kind == LSF_ROUTE_CACHE_OUTPUT) {
        if (owner->cache_kind == LSF_ROUTE_CACHE_INPUT) {
            cell = &nhc->nhc_rth_input;
        } else {
            if (owner->cpu >= nr_cpu_ids || !cpu_possible(owner->cpu) ||
                !nhc->nhc_pcpu_rth_output) {
                lsf_factory_poison(context);
                return;
            }
            cell = per_cpu_ptr(nhc->nhc_pcpu_rth_output, owner->cpu);
        }
        if (cmpxchg((struct rtable **)cell, rt, NULL) == rt) {
            /* The exact original cache replacement cleanup, after winning
             * the actual cell. The independent drain reference stays live. */
            rt_add_uncached_list(rt);
            dst_release(&rt->dst);
        }
    } else if (owner->cache_kind == LSF_ROUTE_CACHE_EXCEPTION_INPUT ||
               owner->cache_kind == LSF_ROUTE_CACHE_EXCEPTION_OUTPUT) {
        struct fnhe_hash_bucket *hash;
        struct fib_nh_exception *fnhe;
        unsigned int depth = 0;
        spin_lock_bh(&fnhe_lock);
        hash = rcu_dereference_protected(nhc->nhc_exceptions, lockdep_is_held(&fnhe_lock));
        if (hash) {
            fnhe = rcu_dereference_protected(hash[fnhe_hashfun((__be32)owner->daddr)].chain,
                lockdep_is_held(&fnhe_lock));
            /* Original insertion retains at most 2*FNHE_RECLAIM_DEPTH. An
             * unproved/corrupt longer chain is retained, never walked forever. */
            while (fnhe && depth++ < 2u * FNHE_RECLAIM_DEPTH) {
                if (fnhe->fnhe_daddr == (__be32)owner->daddr) {
                    cell = owner->cache_kind == LSF_ROUTE_CACHE_EXCEPTION_INPUT ?
                        &fnhe->fnhe_rth_input : &fnhe->fnhe_rth_output;
                    if (rcu_dereference_protected(*cell, lockdep_is_held(&fnhe_lock)) == rt) {
                        rcu_assign_pointer(*cell, NULL);
                        dst_dev_put(&rt->dst);
                        dst_release(&rt->dst);
                    }
                    break;
                }
                fnhe = rcu_dereference_protected(fnhe->fnhe_next, lockdep_is_held(&fnhe_lock));
            }
            if (fnhe && depth > 2u * FNHE_RECLAIM_DEPTH)
                lsf_factory_poison(context);
        }
        spin_unlock_bh(&fnhe_lock);
    } else
        lsf_factory_poison(context);
}

void lsf_prepaid_route_cache_drain(struct lsf_factory_context *context)
{
    struct lsf_route_cache_owner owner;
    struct rtable *rt;
    unsigned int slot;
    for (slot = 1; slot < LSF_ALLOCATION_SLOTS; ++slot) {
        /* Pool validation and real dst_hold_safe are ONE operation. A queued
         * dead dst cannot be revived by a still-LIVE allocator record. */
        if (!lsf_factory_route_current(context, slot, &rt, &owner))
            continue;
        rcu_read_lock();
        lsf_prepaid_route_cache_detach(context, rt, &owner);
        rcu_read_unlock();
        dst_release(&rt->dst);
    }
}

int lsf_prepaid_route_cache_return(const void *address)
{
    struct lsf_route_cache_owner owner;
    int owned = lsf_factory_route_parent_take(address, &owner);
    if (owned != 1)
        return owned;
    /* Runs only at the real dst destructor's original allocator-return site,
     * AFTER ops/metrics/netdev/LWT cleanup, BEFORE returning its prepaid view. */
    lsf_prepaid_route_parent_put(owner);
    return lsf_factory_route_return(address);
}
