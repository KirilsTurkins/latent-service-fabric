/* SPDX-License-Identifier: GPL-2.0-only */
/* Serialized type/FIB/refcount/RCU doubles plus exact maintained/factory
 * bodies. Not Linux route lookup, actual XFRM, cache, layout or RCU evidence. */
#include "reference-io.h"
#include <stdbool.h>
#include "prepaid.h"
#define LSF_STREAM_ROUTE_SOURCE 1
#define CONFIG_XFRM 1
#define CONFIG_NET_DEV_REFCNT_TRACKER tracker_enabled
#define IS_ENABLED(value) (value)
#define static_assert(expression) _Static_assert((expression), #expression)
#define READ_ONCE(value) (value)
#define WRITE_ONCE(value, replacement) ((value) = (replacement))
#define rcu_access_pointer(value) (value)
#define smp_rmb() ((void)0)
#define likely(value) (value)
#define AF_INET 2u
#define AF_INET6 10u
#define IPPROTO_TCP 6u
#define EOPNOTSUPP 95
#define EPERM 1
#define GFP_ATOMIC 1u
#define IFF_LOOPBACK 1u
#define XFRM_POLICY_OUT 1u
#define XFRM_USERPOLICY_BLOCK 1u
#define DST_OBSOLETE_FORCE_CHK 1
#define DST_NOXFRM 1u
#define DST_NOCOUNT 2u
#define DST_METADATA 4u
#define ERR_PTR(value) ((void *)(intptr_t)(value))
#define PTR_ERR(value) ((int)(intptr_t)(value))
#define IS_ERR(value) ((uintptr_t)(value) >= (uintptr_t)-4095)
#define __be32 unsigned int
#define u16 unsigned short
struct net { struct { unsigned int policy_count[2], policy_default[2]; } xfrm; };
struct net_device { struct net *net; unsigned int flags; };
struct proto { unsigned int marker; };
struct flowi4 { unsigned int marker; };
struct list_head { struct list_head *next, *prev; };
struct rcu_head { unsigned int marker; };
struct dst_entry;
struct dst_ops {
    unsigned int family, kmem_cachep, gc_thresh;
    void (*gc)(struct dst_ops *);
    void (*destroy)(struct dst_entry *);
};
struct dst_entry {
    struct net_device *dev;
    unsigned int dev_tracker, metrics, expires;
    struct dst_ops *ops;
    void *xfrm;
    unsigned int input, output, error, header_len, trailer_len;
    int obsolete;
    void *lwtstate;
    unsigned int __rcuref, __use, lastuse, flags;
    struct list_head rt_uncached;
    void *rt_uncached_list;
    struct rcu_head rcu_head;
};
struct rtable {
    struct dst_entry dst;
    unsigned int rt_genid, rt_flags, rt_type, rt_is_input, rt_iif, rt_pmtu;
    unsigned int rt_mtu_locked, rt_uses_gateway, rt_gw_family, rt_gw4, rt_gw6;
};
struct xfrm_dst { struct dst_entry dst; struct dst_entry *child; };
struct metadata_dst { struct dst_entry dst; };
struct sock {
    struct lsf_factory_context *sk_lsf_factory;
    unsigned int sk_lsf_view_slot;
    lsf_u64 sk_lsf_view_generation;
    unsigned int sk_family, sk_protocol;
    struct proto *sk_prot;
    struct net *net;
    void *sk_policy[2];
};
struct lsf_factory_context { struct lsf_prepaid_key key; };
struct lsf_factory_blob { struct lsf_factory_context *context; struct lsf_prepaid_ticket ticket; };
static struct { struct lsf_prepaid pool; struct lsf_factory_context contexts[4]; void *pages; unsigned int uncertain; } factory;
static _Alignas(64) unsigned char backing[LSF_BACKING_BYTES], normal[16][512];
static unsigned int pool_lock, pool_held, normal_allocated, normal_freed, tracker_enabled;
static unsigned int dev_holds, dev_puts, cleanup_count, normal_xfrm, normal_key, owned_key;
static unsigned int entries, jiffies = 1234, cleanup_step;
static struct proto tcp_prot;
static struct net selected_net, other_net;
static struct net_device selected_dev = {&selected_net,0};
static struct sock *owned_sk;
static struct sock ordinary_sk;
static struct rtable *cache_hit;
static struct rcu_head *queued_head;
static void (*queued_callback)(struct rcu_head *);
static void dst_destroy_rcu(struct rcu_head *head);
static void dst_release_immediate(struct dst_entry *dst);
static void *lsf_prepaid_route_allocate(struct net_device *, unsigned short, const struct lsf_factory_blob *);
static struct rtable *lsf_prepaid_route_key_hash_owned(struct net *,struct flowi4 *,const void *,const struct lsf_factory_blob *);
static void lock(unsigned int *value) { assert(value==&pool_lock && !pool_held);pool_held=1; }
static void unlock(unsigned int *value) { assert(value==&pool_lock && pool_held);pool_held=0; }
#define spin_lock_irqsave(value,flags) do { lock(value);(flags)=0; } while (0)
#define spin_unlock_irqrestore(value,flags) do { (void)(flags);unlock(value); } while (0)
static void *page_address(void *pages) { assert(pages==backing);return pages; }
static struct net *sock_net(const struct sock *sk) { return sk->net; }
static const struct sock *sk_const_to_full_sk(const struct sock *sk) { return sk; }
static struct net *dev_net(struct net_device *dev) { return dev->net; }
static void netdev_hold(struct net_device *dev,unsigned int *tracker,unsigned int flags)
{ assert(dev==&selected_dev && flags==GFP_ATOMIC);*tracker=1;dev_holds++; }
static void netdev_put(struct net_device *dev,unsigned int *tracker)
{ assert(dev==&selected_dev && *tracker==1 && cleanup_step==1);cleanup_step=2;dev_puts++; }
static void lwtstate_put(void *state) { assert(!state && cleanup_step==2);cleanup_step=3; }
static void *lwtstate_get(void *state) { return state; }
#define dst_init_metrics(dst,value,readonly) do { (void)(value);assert(readonly);(dst)->metrics=91; } while (0)
static struct { unsigned int metrics[1]; } dst_default_metrics;
static void rcuref_init(unsigned int *ref,unsigned int value) { *ref=value; }
static bool rcuref_put(unsigned int *ref) { assert(*ref);return --*ref==0; }
static void dst_hold(struct dst_entry *dst) { assert(dst->__rcuref);dst->__rcuref++; }
#define INIT_LIST_HEAD(value) do { (value)->next=(value);(value)->prev=(value); } while (0)
static void dst_entries_add(struct dst_ops *ops,int delta) { assert(ops);entries=(unsigned int)((int)entries+delta); }
static unsigned int dst_entries_get_fast(struct dst_ops *ops) { (void)ops;return entries; }
enum { dst_discard=11, dst_discard_out=12, ip_output=13, ip_local_deliver=14, RTCF_LOCAL=16 };
static unsigned int rt_genid_ipv4(struct net *net) { assert(net==&selected_net);return 47; }
static void *kmem_cache_alloc(unsigned int cache,unsigned int flags)
{ assert(cache==7 && flags==GFP_ATOMIC && normal_allocated<16);return normal[normal_allocated++]; }
static void kmem_cache_free(unsigned int cache,void *address)
{
    assert(cache==7 && cleanup_step==3);
    assert((uintptr_t)address<(uintptr_t)backing || (uintptr_t)address>=(uintptr_t)(backing+sizeof(backing)));
    normal_freed++;
}
static void metrics_destroy(struct dst_entry *dst)
{ assert(dst && cleanup_step==0);cleanup_step=1;cleanup_count++; }
static struct dst_ops ipv4_dst_ops = {AF_INET,7,100,NULL,metrics_destroy};
static struct rtable *dst_rtable(struct dst_entry *dst) { return (struct rtable *)dst; }
static void *flowi4_to_flowi(struct flowi4 *flow) { return flow; }
static struct dst_entry *xfrm_lookup_route(struct net *net,struct dst_entry *dst,void *flow,const struct sock *sk,int flags)
{ assert(net==&selected_net && flow && sk==&ordinary_sk && flags==0);normal_xfrm++;return dst; }
static struct rtable *__ip_route_output_key(struct net *net,struct flowi4 *flow)
{ assert(net==&selected_net && flow);normal_key++;return ERR_PTR(-11); }
static void ip_rt_put(struct rtable *rt) { dst_release_immediate(&rt->dst); }
static void dst_count_dec(struct dst_entry *dst) { if (!(dst->flags&DST_NOCOUNT))dst_entries_add(dst->ops,-1); }
static void call_rcu_hurry(struct rcu_head *head,void (*callback)(struct rcu_head *))
{ assert(!queued_head && !queued_callback);queued_head=head;queued_callback=callback; }
static void metadata_dst_free(struct metadata_dst *dst) { (void)dst;assert(false); }
#define container_of(value,type,member) ((type *)((unsigned char *)(value)-offsetof(type,member)))
#include "route-derived-reference.h"

static struct rtable *lsf_prepaid_route_key_hash_owned(struct net *net,struct flowi4 *flow,
    const void *skb,const struct lsf_factory_blob *source)
{
    assert(net==&selected_net && flow && !skb && source->context);owned_key++;
    if (cache_hit) { dst_hold(&cache_hit->dst);return cache_hit; }
    return lsf_prepaid_route_alloc_owned(&selected_dev,RTCF_LOCAL,1,false,source);
}
static void reset(void)
{
    struct lsf_scope scope={{1,2,3,4,5,6,7,8}};
    struct lsf_prepaid_ticket ticket;
    lsf_u64 offset;
    memset(&factory,0,sizeof(factory));memset(backing,0,sizeof(backing));memset(normal,0,sizeof(normal));
    memset(&ordinary_sk,0,sizeof(ordinary_sk));memset(&selected_net,0,sizeof(selected_net));
    pool_held=normal_allocated=normal_freed=tracker_enabled=0;
    dev_holds=dev_puts=cleanup_count=normal_xfrm=normal_key=owned_key=entries=cleanup_step=0;
    queued_head=NULL;queued_callback=NULL;cache_hit=NULL;selected_dev.flags=0;
    factory.pages=backing;assert(lsf_prepaid_initialize(&factory.pool));
    assert(lsf_prepaid_context_create(&factory.pool,scope,LSF_TCP_BYTES,&factory.contexts[0].key));
    assert(lsf_prepaid_allocate(&factory.pool,factory.contexts[0].key,sizeof(*owned_sk),0,
        (struct lsf_prepaid_ticket){0},&ticket,&offset));
    owned_sk=(struct sock *)(backing+offset);
    owned_sk->sk_lsf_factory=&factory.contexts[0];owned_sk->sk_lsf_view_slot=ticket.slot;
    owned_sk->sk_lsf_view_generation=ticket.generation;owned_sk->sk_family=AF_INET;
    owned_sk->sk_protocol=IPPROTO_TCP;owned_sk->sk_prot=&tcp_prot;owned_sk->net=&selected_net;
    ordinary_sk.sk_family=AF_INET;ordinary_sk.sk_protocol=IPPROTO_TCP;
    ordinary_sk.sk_prot=&tcp_prot;ordinary_sk.net=&selected_net;
}
static struct lsf_factory_blob identity(const void *address)
{ struct lsf_factory_blob copy;assert(lsf_factory_blob_lookup(address,LSF_PREPAID_ROUTE,&copy)==1);return copy; }
static struct rtable *route_birth(void)
{ struct lsf_factory_blob source;assert(lsf_prepaid_route_source(owned_sk,&source)==1);return lsf_prepaid_route_alloc_owned(&selected_dev,RTCF_LOCAL,1,false,&source); }
static void immediate(struct rtable *rt) { cleanup_step=0;dst_release_immediate(&rt->dst); }
static void run_callback(void)
{
    struct rcu_head *head=queued_head;void (*callback)(struct rcu_head *)=queued_callback;
    assert(head && callback);queued_head=NULL;queued_callback=NULL;cleanup_step=0;callback(head);
}
static void observed(const char *name)
{ assert(!pool_held);lsf_ref_write("ROUTE_CONTROL ",14);lsf_ref_write(name,lsf_ref_length(name));lsf_ref_write(" PASS\n",6); }

int main(void)
{
    struct rtable *rt,*clone;
    struct lsf_factory_blob birth;
    struct lsf_prepaid_context *context;
    struct flowi4 flow={1};
    lsf_u64 cursor;
    reset();
#ifdef LSF_OLD_ROUTE
    rt=dst_alloc(&ipv4_dst_ops,&selected_dev,DST_OBSOLETE_FORCE_CHK,0);
    assert(rt && normal_allocated==1);
    puts("ROUTE_OLD general-cache-allocation RED");return 2;
#endif
    rt=route_birth();assert(rt && !normal_allocated);birth=identity(rt);
    assert(birth.context==&factory.contexts[0]);observed("exact-original-socket-descendant");
    assert(rt->rt_genid==47 && rt->rt_flags==RTCF_LOCAL && rt->rt_type==1 && !rt->rt_iif);
    assert(rt->dst.input==ip_local_deliver && rt->dst.output==ip_output && rt->dst.metrics==91);
    assert(rt->dst.__rcuref==1 && entries==1 && dev_holds==1);observed("actual-maintained-rtable-and-dst-init");
    context=&factory.pool.contexts[0];context->closed=1;
    assert(!lsf_prepaid_recycle(&factory.pool,factory.contexts[0].key));observed("root-close-not-route-cache-retirement");
    dst_hold(&rt->dst);dst_release(&rt->dst);
    assert(!queued_head && context->live==2 && !context->continuations);observed("nonfinal-reference-does-not-queue");
    dst_release(&rt->dst);
    assert(queued_head && context->live==2 && context->continuations==1 && !cleanup_count);
    assert(factory.pool.records[birth.ticket.slot].deferred==LSF_PREPAID_QUEUED);observed("actual-final-rcuref-queues-one-continuation");
    assert(!lsf_prepaid_recycle(&factory.pool,factory.contexts[0].key));observed("queued-original-rcu-retains-owner");
    run_callback();assert(cleanup_step==3 && cleanup_count==1 && dev_puts==1);
    assert(context->live==1 && !context->continuations && !normal_freed);
    assert(factory.pool.records[birth.ticket.slot].phase==LSF_PREPAID_RETURNED);observed("callback-cleanup-before-final-view-return");
    assert(factory.pool.records[0].phase==LSF_PREPAID_LIVE);observed("view-return-is-not-backing-refund");

    reset();rt=route_birth();birth=identity(rt);cursor=factory.pool.contexts[0].cursor;
    immediate(rt);assert(!queued_head && !factory.pool.contexts[0].continuations);
    assert(factory.pool.records[birth.ticket.slot].phase==LSF_PREPAID_RETURNED);observed("original-immediate-last-reference-return");
    assert(factory.pool.contexts[0].cursor==cursor);observed("returned-view-does-not-reuse-cursor");

    reset();rt=route_birth();rt->dst.input=71;rt->dst.output=72;rt->dst.error=73;rt->rt_pmtu=1492;
    factory.pool.contexts[0].closed=1;clone=rt_dst_clone(&selected_dev,rt);
    assert(clone && !normal_allocated && identity(clone).context==identity(rt).context);
    assert(clone->dst.input==71 && clone->dst.output==72 && clone->dst.error==73 && clone->rt_pmtu==1492);
    observed("actual-clone-inherits-original-route-and-fields");
    immediate(rt);assert(factory.pool.contexts[0].live==2);observed("clone-retains-after-original-route-dies");
    immediate(clone);assert(factory.pool.contexts[0].live==1);observed("draining-parent-child-returns-independently");

    reset();factory.pool.contexts[0].cursor=LSF_TCP_BYTES;
    assert(!route_birth() && !normal_allocated && !dev_holds);observed("original-tcp-byte-exhaustion-no-fallback");
    reset();birth=(struct lsf_factory_blob){&factory.contexts[0],{owned_sk->sk_lsf_view_slot,owned_sk->sk_lsf_view_generation}};
    for (unsigned int i=2;i<LSF_ALLOCATION_SLOTS;i++)assert(lsf_factory_child_allocate(birth,1,LSF_PREPAID_ROUTE));
    assert(!route_birth() && !normal_allocated);observed("original-record-ceiling-no-fallback");

    reset();factory.pool.contexts[0].closed=1;rt=route_birth();assert(rt && factory.pool.contexts[0].live==2);
    observed("closed-root-with-live-real-socket-may-create-route");
    reset();assert(PTR_ERR(lsf_prepaid_route_key(&other_net,&flow,owned_sk))==-EOPNOTSUPP && !owned_key);
    observed("foreign-network-refuses-before-lookup");
    reset();owned_sk->sk_lsf_view_generation++;
    assert(PTR_ERR(lsf_prepaid_route_key(&selected_net,&flow,owned_sk))==-EOPNOTSUPP && !owned_key);
    observed("stale-socket-generation-refuses-before-lookup");
    reset();tracker_enabled=1;
    assert(PTR_ERR(lsf_prepaid_route_key(&selected_net,&flow,owned_sk))==-EOPNOTSUPP && !owned_key && !normal_allocated);
    assert(!route_birth() && !dev_holds);observed("allocating-device-tracker-profile-refused");
    reset();rt=lsf_prepaid_route_key(&selected_net,&flow,owned_sk);
    assert(rt && !IS_ERR(rt) && owned_key==1 && !normal_key && identity(rt).context==&factory.contexts[0]);
    observed("exact-owned-source-crosses-key-boundary");
    cache_hit=rt;cursor=factory.pool.contexts[0].cursor;
    assert(lsf_prepaid_route_key(&selected_net,&flow,owned_sk)==rt && rt->dst.__rcuref==2);
    assert(factory.pool.contexts[0].cursor==cursor);observed("cache-hit-borrows-reference-without-new-birth");
    reset();assert(PTR_ERR(lsf_prepaid_route_key(&selected_net,&flow,&ordinary_sk))==-11 && normal_key==1 && !owned_key);
    observed("ordinary-key-original-path-preserved");

    reset();rt=route_birth();assert(lsf_prepaid_route_xfrm(&selected_net,rt,&flow,owned_sk)==rt);
    assert(!normal_xfrm && rt->dst.__rcuref==1);observed("original-no-policy-fast-path-returns-route");
    rt->dst.flags|=DST_NOXFRM;selected_net.xfrm.policy_count[XFRM_POLICY_OUT]=1;owned_sk->sk_policy[XFRM_POLICY_OUT]=rt;
    assert(PTR_ERR(lsf_prepaid_route_xfrm(&selected_net,rt,&flow,owned_sk))==-EOPNOTSUPP && !normal_xfrm);
    observed("socket-policy-precedes-network-noxfrm");
    reset();rt=route_birth();selected_net.xfrm.policy_count[XFRM_POLICY_OUT]=1;
    assert(PTR_ERR(lsf_prepaid_route_xfrm(&selected_net,rt,&flow,owned_sk))==-EOPNOTSUPP && !normal_xfrm);
    observed("unclosed-global-policy-refused-before-matching");
    reset();rt=route_birth();selected_net.xfrm.policy_default[XFRM_POLICY_OUT]=XFRM_USERPOLICY_BLOCK;
    assert(PTR_ERR(lsf_prepaid_route_xfrm(&selected_net,rt,&flow,owned_sk))==-EPERM);observed("real-default-policy-block-preserved");
    reset();rt=route_birth();selected_net.xfrm.policy_default[XFRM_POLICY_OUT]=XFRM_USERPOLICY_BLOCK;selected_dev.flags=IFF_LOOPBACK;
    assert(lsf_prepaid_route_xfrm(&selected_net,rt,&flow,owned_sk)==rt);observed("real-default-block-loopback-exception-preserved");
    reset();rt=route_birth();rt->dst.flags|=DST_NOXFRM;selected_net.xfrm.policy_count[XFRM_POLICY_OUT]=1;
    assert(lsf_prepaid_route_xfrm(&selected_net,rt,&flow,owned_sk)==rt);observed("actual-noxfrm-fast-path-not-forced");
    reset();rt=route_birth();assert(lsf_prepaid_route_xfrm(&selected_net,rt,&flow,&ordinary_sk)==rt && normal_xfrm==1);
    observed("ordinary-xfrm-original-call-preserved");

    reset();rt=route_birth();rt->dst.lwtstate=rt;cursor=factory.pool.contexts[0].cursor;
    assert(!rt_dst_clone(&selected_dev,rt) && factory.pool.contexts[0].cursor==cursor && !normal_allocated);
    observed("unclosed-lightweight-tunnel-clone-refused");
    reset();assert(lsf_factory_route_return(backing+1)==-1 && !normal_freed && factory.pool.poisoned);
    observed("unknown-interior-return-is-quarantined");
    reset();rt=route_birth();birth=identity(rt);immediate(rt);
    assert(lsf_factory_route_return(rt)==-1 && !normal_freed);observed("duplicate-final-return-never-enters-slub");
    reset();rt=route_birth();birth=identity(rt);birth.ticket.generation++;
    assert(!lsf_prepaid_route_queue(&factory.pool,birth.context->key,birth.ticket));
    assert(factory.pool.contexts[0].live==2 && !factory.pool.contexts[0].continuations);observed("stale-queue-generation-retains-live-owner");
    reset();rt=dst_alloc(&ipv4_dst_ops,&selected_dev,DST_OBSOLETE_FORCE_CHK,0);
    assert(rt && normal_allocated==1);clone=rt_dst_clone(&selected_dev,rt);
    assert(clone && normal_allocated==2 && factory.pool.contexts[0].live==1);
    immediate(rt);immediate(clone);assert(normal_freed==2);observed("normal-clone-and-final-slub-return-unchanged");
    return 0;
}
