/* SPDX-License-Identifier: GPL-2.0-only */
/* Included after the exact maintained route.c definitions. Lookup, original
 * cache publication, metrics references and policy state remain authoritative. */

static_assert(offsetof(struct rtable, dst) == 0);
static_assert(__alignof__(struct rtable) <= 64);
static_assert(sizeof(struct rtable) <= LSF_TCP_BYTES);

static int lsf_prepaid_route_source(const struct sock *sk,
                                    struct lsf_factory_blob *source)
{
    int owned;
    sk = sk_const_to_full_sk(sk);
    owned = lsf_prepaid_netlabel_source((struct sock *)sk, source);
    if (owned == 1 && (sk->sk_family != AF_INET ||
                      sk->sk_protocol != IPPROTO_TCP || sk->sk_prot != &tcp_prot)) {
        lsf_factory_poison(source->context);
        return -EOPNOTSUPP;
    }
    return owned;
}

static void *lsf_prepaid_route_allocate(struct net_device *dev,
                                       unsigned short flags,
                                       const struct lsf_factory_blob *source)
{
    struct rtable *rt;
    /* The selected baseline has no allocating reference tracker. A future
     * configuration cannot silently add one beneath this private producer. */
    if (IS_ENABLED(CONFIG_NET_DEV_REFCNT_TRACKER))
        return NULL;
    rt = lsf_factory_child_allocate(*source, sizeof(*rt), LSF_PREPAID_ROUTE);
    if (rt)
        dst_init(&rt->dst, &ipv4_dst_ops, dev, DST_OBSOLETE_FORCE_CHK, flags);
    return rt;
}

static void *lsf_prepaid_route_clone_allocate(struct net_device *dev,
                                              struct rtable *original)
{
    struct lsf_factory_blob source;
    int owned = lsf_factory_blob_lookup(original, LSF_PREPAID_ROUTE, &source);
    if (owned == 0)
        return dst_alloc(&ipv4_dst_ops, dev, DST_OBSOLETE_FORCE_CHK,
                         original->dst.flags);
    if (owned < 0)
        return NULL;
    if (original->dst.ops != &ipv4_dst_ops || original->dst.lwtstate) {
        lsf_factory_poison(source.context);
        return NULL;
    }
    return lsf_prepaid_route_allocate(dev, original->dst.flags, &source);
}

struct rtable *lsf_prepaid_route_key(struct net *net, struct flowi4 *fl4,
                                     const struct sock *sk)
{
    struct lsf_factory_blob source;
    int owned = lsf_prepaid_route_source(sk, &source);
    if (owned == 0)
        return __ip_route_output_key(net, fl4);
    if (owned < 0)
        return ERR_PTR(owned);
    if (net != sock_net(sk)) {
        lsf_factory_poison(source.context);
        return ERR_PTR(-EOPNOTSUPP);
    }
    if (IS_ENABLED(CONFIG_NET_DEV_REFCNT_TRACKER))
        return ERR_PTR(-EOPNOTSUPP);
    return lsf_prepaid_route_key_hash_owned(net, fl4, NULL, &source);
}

struct rtable *lsf_prepaid_route_xfrm(struct net *net, struct rtable *rt,
                                      struct flowi4 *fl4, const struct sock *sk)
{
    struct lsf_factory_blob source;
    int owned = lsf_prepaid_route_source(sk, &source);
    if (owned == 0)
        return dst_rtable(xfrm_lookup_route(net, &rt->dst,
                            flowi4_to_flowi(fl4), sk, 0));
    if (owned < 0) {
        ip_rt_put(rt);
        return ERR_PTR(owned);
    }
    if (net != sock_net(sk)) {
        lsf_factory_poison(source.context);
        ip_rt_put(rt);
        return ERR_PTR(-EOPNOTSUPP);
    }
#ifdef CONFIG_XFRM
    /* The original lookup checks socket policy BEFORE its network fast path.
     * A matched policy, even an allow/no-transform one, can allocate a dummy
     * destination or enter mandatory LSM/key-manager work. That chain is not
     * closed here: refuse before entering it, never pretend no policy matched.
     * These are exactly the original no-policy fast-path conditions, not an
     * operator override, forced DST_NOXFRM bit or CONFIG_XFRM disable. */
    sk = sk_const_to_full_sk(sk);
    if ((sk && rcu_access_pointer(sk->sk_policy[XFRM_POLICY_OUT])) ||
        (!(rt->dst.flags & DST_NOXFRM) &&
         READ_ONCE(net->xfrm.policy_count[XFRM_POLICY_OUT]))) {
        ip_rt_put(rt);
        return ERR_PTR(-EOPNOTSUPP);
    }
    /* Retain the real default-block and loopback exception of nopol. A zero
     * policy count is not permission to bypass this independent decision. */
    if ((!rt->dst.dev || !(rt->dst.dev->flags & IFF_LOOPBACK)) &&
        READ_ONCE(net->xfrm.policy_default[XFRM_POLICY_OUT]) == XFRM_USERPOLICY_BLOCK) {
        ip_rt_put(rt);
        return ERR_PTR(-EPERM);
    }
#endif
    return rt;
}
