/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in the exact maintained inet_hashtables.c after its definitions.
 * Hash locks, real port selection, reuse policy and empty-bucket destruction
 * remain authoritative. This never adopts an ordinary shared-cache object. */

static_assert(__alignof__(struct inet_bind_bucket) <= 64);
static_assert(__alignof__(struct inet_bind2_bucket) <= 64);
static_assert(sizeof(struct inet_bind_bucket) <= LSF_TCP_BYTES);
static_assert(sizeof(struct inet_bind2_bucket) <= LSF_TCP_BYTES);

static int lsf_prepaid_bind_source(const struct sock *sk,
                                   struct lsf_factory_blob *source)
{
    /* The existing classifier reads, but never modifies, the socket's private
     * allocator-born fields. Its original exact-address/generation check stays
     * the only source of authority; const does not confer or register origin. */
    int owned = lsf_prepaid_netlabel_source((struct sock *)sk, source);
    if (owned == 1 && (sk->sk_family != AF_INET ||
                      sk->sk_protocol != IPPROTO_TCP || sk->sk_prot != &tcp_prot)) {
        lsf_factory_poison(source->context);
        return -EOPNOTSUPP;
    }
    return owned;
}

int lsf_prepaid_bind_owned(const struct sock *sk)
{
    struct lsf_factory_blob source;
    return lsf_prepaid_bind_source(sk, &source);
}

int lsf_prepaid_bind_check(const struct sock *sk)
{
    int owned = lsf_prepaid_bind_owned(sk);
    return owned < 0 ? owned : 0;
}

struct inet_bind_bucket *lsf_prepaid_bind_bucket_create(struct kmem_cache *cachep,
    struct net *net, struct inet_bind_hashbucket *head, unsigned short snum,
    int l3mdev, const struct sock *sk)
{
    struct lsf_factory_blob source;
    int owned = lsf_prepaid_bind_source(sk, &source);
    if (owned == 0)
        return inet_bind_bucket_create(cachep, net, head, snum, l3mdev);
    if (owned < 0)
        return NULL;
    if (cachep != tcp_or_dccp_get_hashinfo(sk)->bind_bucket_cachep ||
        net != sock_net(sk)) {
        lsf_factory_poison(source.context);
        return NULL;
    }
    /* The clone allocates from this actual socket birth BEFORE the original
     * initialization/hlist_add_head publication while the original lock holds. */
    return lsf_prepaid_bind_bucket_create_owned(cachep, net, head, snum, l3mdev, &source);
}

void *lsf_prepaid_bind2_allocate(struct kmem_cache *cachep, const struct sock *sk)
{
    struct lsf_factory_blob source;
    int owned = lsf_prepaid_bind_source(sk, &source);
    if (owned == 0)
        return kmem_cache_alloc(cachep, GFP_ATOMIC);
    if (owned < 0)
        return NULL;
    if (cachep != tcp_or_dccp_get_hashinfo(sk)->bind2_bucket_cachep) {
        lsf_factory_poison(source.context);
        return NULL;
    }
    /* Also serves the original preallocation-before-address-change path. Its
     * unused candidate is returned only at the original loser cleanup point. */
    return lsf_factory_child_allocate(source, sizeof(struct inet_bind2_bucket),
                                       LSF_PREPAID_BIND2_BUCKET);
}

bool lsf_prepaid_bind_return(const void *address, unsigned int kind)
{
    struct lsf_factory_blob copy;
    int owned;
    if (!lsf_prepaid_bind_kind(kind)) {
        lsf_factory_poison(NULL);
        return true;
    }
    /* Called only at the original allocator-return sites: after both original
     * unlinks under their hash locks, or for the unpublished unused candidate.
     * No bucket, socket or parent is read after returning the fixed view. */
    owned = lsf_factory_blob_lookup(address, kind, &copy);
    if (owned == 0)
        return false;
    if (owned == 1 && !lsf_factory_blob_finish(copy, kind))
        lsf_factory_poison(copy.context);
    /* Unknown, duplicate or poisoned in-arena pointers never reach SLUB.
     * Ordinary logical unlinks already happened, even when retention fails. */
    return true;
}
