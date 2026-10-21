/* SPDX-License-Identifier: GPL-2.0-only */
/* Serialized type/hash-lock doubles plus exact selected maintained/factory
 * bodies. This is NOT actual Linux layout, port, TIMEWAIT or RCU execution. */
#include "reference-io.h"
#include <stdbool.h>
#include "prepaid.h"
#define LSF_STREAM_BIND_SOURCE 1
#define static_assert(expression) _Static_assert((expression), #expression)
#define EOPNOTSUPP 95
#define AF_INET 2
#define IPPROTO_TCP 6
#define GFP_ATOMIC 1u
#define IS_ENABLED(value) 0
#define WRITE_ONCE(value, replacement) ((value) = (replacement))
struct net { unsigned int marker; };
struct proto { unsigned int marker; };
struct kmem_cache { unsigned int kind; };
struct inet_hashinfo { struct kmem_cache *bind_bucket_cachep, *bind2_bucket_cachep; };
struct sock {
    struct lsf_factory_context *sk_lsf_factory;
    unsigned int sk_lsf_view_slot;
    lsf_u64 sk_lsf_view_generation;
    unsigned int sk_family, sk_protocol, sk_rcv_saddr;
    struct proto *sk_prot;
    struct net *net;
    struct inet_hashinfo *hashinfo;
};
struct hlist_node { struct hlist_node *next, **pprev; };
struct hlist_head { struct hlist_node *first; };
/* Explicit reference layouts; maintained compiled types are still untested. */
struct inet_bind_bucket {
    struct net *ib_net;
    int l3mdev;
    unsigned short port;
    signed char fastreuse, fastreuseport;
    struct hlist_node node;
    struct hlist_head bhash2;
};
struct inet_bind2_bucket {
    struct net *ib_net;
    int l3mdev;
    unsigned short port;
    unsigned int rcv_saddr;
    struct hlist_node node, bhash_node;
    struct hlist_head owners;
};
struct inet_bind_hashbucket { struct hlist_head chain; };
struct lsf_factory_context { struct lsf_prepaid_key key; };
struct lsf_factory_blob { struct lsf_factory_context *context; struct lsf_prepaid_ticket ticket; };
static struct { struct lsf_prepaid pool; struct lsf_factory_context contexts[4]; void *pages; unsigned int uncertain; } factory;
static _Alignas(64) unsigned char backing[LSF_BACKING_BYTES];
static _Alignas(64) unsigned char normal[16][256];
static unsigned int pool_lock, pool_held, cache_held, normal_allocated, normal_freed;
static struct proto tcp_prot;
static struct net selected_net, other_net;
static struct kmem_cache bind_cache = {1}, bind2_cache = {2}, wrong_cache = {3};
static struct inet_hashinfo hinfo = {&bind_cache, &bind2_cache};
static struct inet_bind_hashbucket head, head2;
static struct sock *owned_sk;
static struct sock ordinary_sk;
static void lock(unsigned int *value)
{ assert(value == &pool_lock && !pool_held); pool_held = 1; }
static void unlock(unsigned int *value)
{ assert(value == &pool_lock && pool_held); pool_held = 0; }
#define spin_lock_irqsave(value, flags) do { lock(value); (flags) = 0; } while (0)
#define spin_unlock_irqrestore(value, flags) do { (void)(flags); unlock(value); } while (0)
#define write_pnet(where, value) (*(where) = (value))
#define INIT_HLIST_HEAD(value) ((value)->first = NULL)
static bool hlist_empty(struct hlist_head *value) { return value->first == NULL; }
static void hlist_add_head(struct hlist_node *node, struct hlist_head *list)
{
    assert(cache_held && !pool_held);
    node->next = list->first;
    if (node->next) node->next->pprev = &node->next;
    list->first = node; node->pprev = &list->first;
}
static void __hlist_del(struct hlist_node *node)
{
    assert(cache_held && !pool_held && node->pprev);
    *node->pprev = node->next;
    if (node->next) node->next->pprev = node->pprev;
}
static void *page_address(void *pages) { assert(pages == backing); return pages; }
static struct net *sock_net(const struct sock *sk) { return sk->net; }
static struct inet_hashinfo *tcp_or_dccp_get_hashinfo(const struct sock *sk) { return sk->hashinfo; }
static void *kmem_cache_alloc(struct kmem_cache *cache, unsigned int flags)
{
    assert(cache && flags == GFP_ATOMIC && normal_allocated < 16);
    return normal[normal_allocated++];
}
static void kmem_cache_free(struct kmem_cache *cache, void *address)
{
    assert(cache && cache_held);
    assert((uintptr_t)address < (uintptr_t)backing || (uintptr_t)address >= (uintptr_t)(backing+sizeof(backing)));
    normal_freed++;
}
#include "bind-derived-reference.h"

static struct sock *socket_birth(unsigned int index)
{
    struct lsf_factory_context *context = &factory.contexts[index];
    struct lsf_prepaid_ticket ticket;
    struct sock *sk;
    lsf_u64 offset;
    assert(lsf_prepaid_allocate(&factory.pool, context->key, sizeof(*sk), 0,
        (struct lsf_prepaid_ticket){0}, &ticket, &offset));
    sk = (struct sock *)(backing+offset);
    sk->sk_lsf_factory = context;
    sk->sk_lsf_view_slot = ticket.slot;
    sk->sk_lsf_view_generation = ticket.generation;
    sk->sk_family = AF_INET; sk->sk_protocol = IPPROTO_TCP;
    sk->sk_prot = &tcp_prot; sk->net = &selected_net; sk->hashinfo = &hinfo;
    sk->sk_rcv_saddr = 0x12345678u;
    return sk;
}
static void reset(void)
{
    struct lsf_scope scope = {{1,2,3,4,5,6,7,8}};
    memset(&factory,0,sizeof(factory));memset(backing,0,sizeof(backing));
    memset(normal,0,sizeof(normal));memset(&head,0,sizeof(head));memset(&head2,0,sizeof(head2));
    memset(&ordinary_sk,0,sizeof(ordinary_sk));
    pool_held = cache_held = normal_allocated = normal_freed = 0;
    factory.pages = backing;assert(lsf_prepaid_initialize(&factory.pool));
    assert(lsf_prepaid_context_create(&factory.pool,scope,LSF_TCP_BYTES,&factory.contexts[0].key));
    owned_sk = socket_birth(0);
    ordinary_sk.sk_family = AF_INET; ordinary_sk.sk_protocol = IPPROTO_TCP;
    ordinary_sk.sk_prot = &tcp_prot; ordinary_sk.net = &selected_net; ordinary_sk.hashinfo = &hinfo;
}
#ifndef LSF_OLD_BIND
static void observed(const char *name)
{ assert(!pool_held && !cache_held);lsf_ref_write("BIND_CONTROL ",13);lsf_ref_write(name,lsf_ref_length(name));lsf_ref_write(" PASS\n",6); }
static struct lsf_factory_blob identity(const void *address, unsigned int kind)
{ struct lsf_factory_blob value;assert(lsf_factory_blob_lookup(address,kind,&value)==1);return value; }
static struct inet_bind_bucket *bucket(void)
{
    struct inet_bind_bucket *value;
    cache_held = 1;
    value = lsf_prepaid_bind_bucket_create(&bind_cache,&selected_net,&head,49153,3,owned_sk);
    cache_held = 0;return value;
}
static void destroy(struct inet_bind_bucket *tb)
{ cache_held = 1;inet_bind_bucket_destroy(&bind_cache,tb);cache_held = 0; }
#endif

int main(void)
{
    reset();
    (void)other_net; (void)wrong_cache;
#ifdef LSF_OLD_BIND
    cache_held = 1;
    assert(inet_bind_bucket_create(&bind_cache,&selected_net,&head,49153,3));
    cache_held = 0;assert(normal_allocated == 1);
    puts("BIND_OLD general-cache-allocation RED");return 2;
#else
    struct inet_bind_bucket *tb;
    struct inet_bind2_bucket *tb2;
    struct lsf_factory_blob first, second, source;
    struct hlist_node owner_a = {0}, owner_b = {0};
    struct lsf_prepaid_context *context = &factory.pool.contexts[0];
    lsf_u64 cursor;

    tb=bucket();assert(tb && !normal_allocated);
    first=identity(tb,LSF_PREPAID_BIND_BUCKET);
    assert(first.context == &factory.contexts[0]);observed("exact-socket-creator-birth");
    assert(tb->ib_net == &selected_net && tb->port == 49153 && tb->l3mdev == 3);
    assert(!tb->fastreuse && !tb->fastreuseport && hlist_empty(&tb->bhash2));
    assert(head.chain.first == &tb->node);observed("original-init-before-hash-publication");
    cache_held=1;tb2=inet_bind2_bucket_create(&bind2_cache,&selected_net,&head2,tb,owned_sk);cache_held=0;
    assert(tb2 && !normal_allocated);second=identity(tb2,LSF_PREPAID_BIND2_BUCKET);
    assert(second.context==first.context && tb2->rcv_saddr==owned_sk->sk_rcv_saddr);
    assert(tb2->port==tb->port && tb2->l3mdev==tb->l3mdev);observed("bind2-same-parent-full-init");
    destroy(tb);assert(factory.pool.records[first.ticket.slot].phase==LSF_PREPAID_LIVE);
    assert(head.chain.first==&tb->node);observed("nonempty-bind-bucket-retains");
    cache_held=1;hlist_add_head(&owner_a,&tb2->owners);hlist_add_head(&owner_b,&tb2->owners);
    inet_bind2_bucket_destroy(&bind2_cache,tb2);cache_held=0;
    assert(factory.pool.records[second.ticket.slot].phase==LSF_PREPAID_LIVE);observed("two-real-list-users-retain");
    cache_held=1;__hlist_del(&owner_a);inet_bind2_bucket_destroy(&bind2_cache,tb2);cache_held=0;
    assert(tb2->owners.first==&owner_b && factory.pool.records[second.ticket.slot].phase==LSF_PREPAID_LIVE);
    observed("remaining-socket-or-timewait-retains");
    context->closed=1;
    assert(!lsf_prepaid_recycle(&factory.pool,factory.contexts[0].key));observed("root-close-not-empty-cache-proof");
    cache_held=1;__hlist_del(&owner_b);inet_bind2_bucket_destroy(&bind2_cache,tb2);cache_held=0;
    assert(!head2.chain.first && hlist_empty(&tb->bhash2));
    assert(factory.pool.records[second.ticket.slot].phase==LSF_PREPAID_RETURNED);observed("last-user-unlinks-before-bind2-return");
    destroy(tb);assert(!head.chain.first && factory.pool.records[first.ticket.slot].phase==LSF_PREPAID_RETURNED);
    assert(!normal_freed && factory.pool.records[0].phase==LSF_PREPAID_LIVE);observed("bind-return-not-backing-refund");

    reset();context=&factory.pool.contexts[0];context->closed=1;
    tb=bucket();assert(tb && context->live==2);observed("draining-live-socket-may-create-child");
    destroy(tb);assert(context->live==1);observed("empty-bucket-retains-original-socket");

    reset();cache_held=1;tb2=lsf_prepaid_bind2_allocate(&bind2_cache,&selected_net,owned_sk);cache_held=0;
    assert(tb2);first=identity(tb2,LSF_PREPAID_BIND2_BUCKET);
    assert(lsf_prepaid_bind_return(tb2,LSF_PREPAID_BIND2_BUCKET));
    assert(factory.pool.records[first.ticket.slot].phase==LSF_PREPAID_RETURNED && !normal_freed);
    observed("unpublished-address-candidate-return");

    reset();tb=bucket();assert(tb);first=identity(tb,LSF_PREPAID_BIND_BUCKET);
    context=&factory.pool.contexts[0];context->cursor=LSF_TCP_BYTES;
    cache_held=1;tb2=inet_bind2_bucket_create(&bind2_cache,&selected_net,&head2,tb,owned_sk);cache_held=0;
    assert(!tb2 && !normal_allocated && factory.pool.records[first.ticket.slot].phase==LSF_PREPAID_LIVE);
    destroy(tb);assert(factory.pool.records[first.ticket.slot].phase==LSF_PREPAID_RETURNED);
    observed("bind2-failure-keeps-normal-first-bucket-cleanup");

    reset();source=(struct lsf_factory_blob){&factory.contexts[0],{owned_sk->sk_lsf_view_slot,owned_sk->sk_lsf_view_generation}};
    for (unsigned int i=2;i<LSF_ALLOCATION_SLOTS;i++)
        assert(lsf_factory_child_allocate(source,1,LSF_PREPAID_BIND_BUCKET));
    assert(!bucket() && !normal_allocated);observed("original-fixed-record-exhaustion-no-fallback");

    reset();factory.pool.contexts[0].cursor=LSF_TCP_BYTES;
    cache_held=1;tb2=lsf_prepaid_bind2_allocate(&bind2_cache,&selected_net,owned_sk);cache_held=0;
    assert(!tb2 && !normal_allocated);observed("original-tcp-byte-bound-no-fallback");

    reset();cache_held=1;
    tb=lsf_prepaid_bind_bucket_create(&bind_cache,&selected_net,&head,49154,0,&ordinary_sk);
    tb2=inet_bind2_bucket_create(&bind2_cache,&selected_net,&head2,tb,&ordinary_sk);
    assert(tb && tb2 && normal_allocated==2);
    inet_bind2_bucket_destroy(&bind2_cache,tb2);inet_bind_bucket_destroy(&bind_cache,tb);cache_held=0;
    assert(normal_freed==2 && !head.chain.first && !head2.chain.first);observed("ordinary-original-cache-allocate-and-free");

    reset();owned_sk->sk_lsf_view_generation++;
    assert(lsf_prepaid_bind_check(owned_sk)==-EOPNOTSUPP && !bucket() && !normal_allocated);
    observed("stale-original-generation-refused");

    reset();owned_sk->sk_family=10;
    assert(lsf_prepaid_bind_check(owned_sk)==-EOPNOTSUPP && !normal_allocated && factory.uncertain);
    observed("nonselected-owned-family-refused");

    reset();cache_held=1;
    assert(!lsf_prepaid_bind_bucket_create(&wrong_cache,&selected_net,&head,1,0,owned_sk));cache_held=0;
    assert(!normal_allocated && !head.chain.first && factory.uncertain);observed("wrong-cache-refused-before-publication");

    reset();cache_held=1;
    assert(!lsf_prepaid_bind_bucket_create(&bind_cache,&other_net,&head,1,0,owned_sk));cache_held=0;
    assert(!normal_allocated && !head.chain.first && factory.uncertain);observed("foreign-network-refused-before-publication");

    reset();tb=bucket();assert(tb);cache_held=1;
    assert(!inet_bind2_bucket_create(&bind2_cache,&other_net,&head2,tb,owned_sk));cache_held=0;
    assert(!normal_allocated && !head2.chain.first && hlist_empty(&tb->bhash2) && factory.uncertain);
    observed("foreign-bind2-network-refused-before-allocation");

    reset();tb=bucket();assert(tb);first=identity(tb,LSF_PREPAID_BIND_BUCKET);
    assert(lsf_prepaid_bind_return((char *)tb+1,LSF_PREPAID_BIND_BUCKET));
    assert(factory.pool.poisoned && !normal_freed && factory.pool.records[first.ticket.slot].phase==LSF_PREPAID_LIVE);
    observed("unknown-interior-address-quarantines");

    reset();tb=bucket();assert(tb);first=identity(tb,LSF_PREPAID_BIND_BUCKET);
    assert(lsf_prepaid_bind_return(tb,LSF_PREPAID_BIND2_BUCKET));
    assert(factory.pool.poisoned && !normal_freed && factory.pool.records[first.ticket.slot].phase==LSF_PREPAID_LIVE);
    observed("wrong-kind-quarantines-original-view");

    reset();tb=bucket();assert(tb);destroy(tb);
    assert(lsf_prepaid_bind_return(tb,LSF_PREPAID_BIND_BUCKET) && factory.pool.poisoned && !normal_freed);
    observed("duplicate-return-never-slub");

    reset();tb=bucket();assert(tb);first=identity(tb,LSF_PREPAID_BIND_BUCKET);
    cursor=factory.pool.contexts[0].cursor;lsf_factory_poison(&factory.contexts[0]);destroy(tb);
    assert(!head.chain.first && !normal_freed && factory.pool.records[first.ticket.slot].phase==LSF_PREPAID_LIVE);
    assert(factory.pool.contexts[0].cursor==cursor);observed("poison-still-unlinks-normal-hash-retains-charge");
    return 0;
#endif
}
