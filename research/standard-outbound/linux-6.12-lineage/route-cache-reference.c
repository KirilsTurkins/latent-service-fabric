/* SPDX-License-Identifier: GPL-2.0-only */
/* Exact maintained/selected bodies with SERIALIZED types, refcounts, locks and
 * RCU doubles. This programme is not Linux concurrency, RCU or layout proof. */
#include "reference-io.h"
#include <stdbool.h>
#include "route-cache-derived-prepaid.h"
#define __rcu
#define __force
#define __be32 unsigned int
#define u32 unsigned int
#define AF_INET 2u
#define EOPNOTSUPP 95
#define EAGAIN 11
#define READ_ONCE(value) (value)
#define WRITE_ONCE(value,replacement) ((value)=(replacement))
#define rcu_dereference(value) (value)
#define rcu_dereference_protected(value,condition) ((void)(condition),(value))
#define rcu_assign_pointer(target,value) ((target)=(value))
#define RCU_INIT_POINTER(target,value) ((target)=(value))
#define container_of(value,type,member) ((type *)((unsigned char *)(value)-offsetof(type,member)))
#define FNHE_RECLAIM_DEPTH 5u
#define LSF_FACTORY_CONTEXTS 4u
struct rcu_head { unsigned int unused; };
struct dst_entry { unsigned int refs, dev; };
struct rtable { struct dst_entry dst; unsigned int input, rt_gw4, rt_gw_family; };
struct fib_nh_exception {
    int fnhe_genid;
    unsigned int fnhe_daddr, fnhe_gw, fnhe_pmtu, fnhe_expires, fnhe_stamp;
    bool fnhe_mtu_locked;
    struct rtable *fnhe_rth_input,*fnhe_rth_output;
    struct fib_nh_exception *fnhe_next;
};
struct fnhe_hash_bucket { struct fib_nh_exception *chain; };
struct fib_nh_common {
    unsigned int nhc_family;
    struct rtable *nhc_rth_input, **nhc_pcpu_rth_output;
    struct fnhe_hash_bucket *nhc_exceptions;
};
struct fib_nh { struct fib_nh_common nh_common; };
struct nexthop;
struct nh_info { struct fib_nh_common fib_nhc; struct nexthop *nh_parent; unsigned int family; };
struct nexthop { unsigned int refcnt; struct rcu_head rcu; bool is_group; struct nh_info *nh_info; };
struct fib_info { unsigned int fib_clntref; struct nexthop *nh; bool fib_nh_is_v6; unsigned int fib_nhs; struct fib_nh fib_nh[2]; };
struct fib_result { struct fib_nh_common *nhc; unsigned int nh_sel; };
#define FIB_RES_NHC(value) ((value).nhc)
struct lsf_factory_context { struct lsf_prepaid_key key; };
struct lsf_factory_blob { struct lsf_factory_context *context; struct lsf_prepaid_ticket ticket; };
static struct { struct lsf_prepaid pool; struct lsf_factory_context contexts[LSF_FACTORY_CONTEXTS]; void *pages; unsigned int uncertain; } factory;
static _Alignas(64) unsigned char backing[LSF_BACKING_BYTES];
static unsigned int pool_lock,fnhe_lock,pool_held,fnhe_held,rcu_held,cpu_held;
static unsigned int releases,uncached,dev_puts,fib_freed,nh_queued,jiffies=123;
static unsigned int nr_cpu_ids=2,selected_cpu=1;
static struct rtable *competing_route;
static struct nexthop *replace_on_get;
static struct nh_info *replacement_info;
static struct rcu_head *pending_nh;
static void (*pending_nh_callback)(struct rcu_head *);
static struct fib_info fi;
static struct nexthop nh;
static struct nh_info info,other_info;
static struct rtable *percpu[2],*other_percpu[2];
static struct fnhe_hash_bucket buckets[1];
static struct fib_nh_exception exceptions[12];
static struct rtable ordinary,competitor;
static struct lsf_prepaid_ticket socket_birth;
static unsigned int refcount_inc_not_zero(unsigned int *value)
{
    if (!*value)return 0;
    ++*value;
    if (replace_on_get && value==&replace_on_get->refcnt) {
        replace_on_get->nh_info=replacement_info;replace_on_get=NULL;
    }
    return 1;
}
static bool refcount_dec_and_test(unsigned int *value) { assert(*value);return --*value==0; }
static void free_fib_info(struct fib_info *value) { assert(!pool_held && !fnhe_held && value==&fi && !value->fib_clntref);fib_freed++; }
static void nexthop_free_rcu(struct rcu_head *head) { assert(head==&nh.rcu && !nh.refcnt); }
static void call_rcu_hurry(struct rcu_head *head,void (*callback)(struct rcu_head *))
{ assert(!pool_held && !fnhe_held && !pending_nh);pending_nh=head;pending_nh_callback=callback;nh_queued++; }
static void lock(unsigned int *value)
{ if(value==&pool_lock){assert(!pool_held);pool_held=1;}else{assert(value==&fnhe_lock && !pool_held && !fnhe_held);fnhe_held=1;} }
static void unlock(unsigned int *value)
{ if(value==&pool_lock){assert(pool_held);pool_held=0;}else{assert(value==&fnhe_lock && fnhe_held && !pool_held);fnhe_held=0;} }
#define spin_lock_irqsave(value,flags) do{lock(value);(flags)=0;}while(0)
#define spin_unlock_irqrestore(value,flags) do{(void)(flags);unlock(value);}while(0)
#define spin_lock_bh(value) lock(value)
#define spin_unlock_bh(value) unlock(value)
#define lockdep_is_held(value) ((value)==&fnhe_lock && fnhe_held)
static void rcu_read_lock(void) { assert(!rcu_held && !pool_held);rcu_held=1; }
static void rcu_read_unlock(void) { assert(rcu_held && !pool_held && !fnhe_held);rcu_held=0; }
static void *page_address(void *pages) { assert(pages==backing);return pages; }
static unsigned int get_cpu(void) { assert(!cpu_held);cpu_held=1;return selected_cpu; }
static void put_cpu(void) { assert(cpu_held);cpu_held=0; }
#define per_cpu_ptr(value,cpu) ((value)+(cpu))
#define raw_cpu_ptr(value) ((value)+selected_cpu)
static bool cpu_possible(unsigned int cpu) { return cpu<nr_cpu_ids; }
static struct rtable *exchange(struct rtable **cell,struct rtable *expected,struct rtable *value)
{
    struct rtable *old;
    if(competing_route){*cell=competing_route;competing_route=NULL;}
    old=*cell;if(old==expected)*cell=value;return old;
}
#define cmpxchg(cell,expected,value) exchange(cell,expected,value)
static void dst_hold(struct dst_entry *dst) { assert(dst->refs);dst->refs++; }
static bool dst_hold_safe(struct dst_entry *dst) { return refcount_inc_not_zero(&dst->refs); }
static void dst_release(struct dst_entry *dst) { assert(!pool_held && !cpu_held && dst->refs);dst->refs--;releases++; }
static void rt_add_uncached_list(struct rtable *rt) { assert(!pool_held && !cpu_held && rt);uncached++; }
static void dst_dev_put(struct dst_entry *dst) { assert(!pool_held && dst);dev_puts++; }
static bool rt_is_input_route(const struct rtable *rt) { return rt->input!=0; }
static unsigned int fnhe_hashfun(unsigned int daddr) { (void)daddr;return 0; }
static unsigned int dev_net(unsigned int dev) { return dev; }
static unsigned int fnhe_genid(unsigned int net) { (void)net;return 9; }
static void fill_route_from_fnhe(struct rtable *rt,struct fib_nh_exception *fnhe) { assert(fnhe_held);rt->rt_gw4=fnhe->fnhe_gw; }
#include "lsf_stream_route_cache_private.h"
#include "route-cache-derived-reference.h"
static void observed(const char *name)
{ assert(!pool_held && !fnhe_held && !rcu_held && !cpu_held);lsf_ref_write("CACHE_CONTROL ",14);lsf_ref_write(name,lsf_ref_length(name));lsf_ref_write(" PASS\n",6); }
static void reset(void)
{
    struct lsf_scope scope={{1,2,3,4,5,6,7,8}};
    lsf_u64 socket_offset;
    memset(&factory,0,sizeof(factory));memset(backing,0,sizeof(backing));memset(&fi,0,sizeof(fi));
    memset(&nh,0,sizeof(nh));memset(&info,0,sizeof(info));memset(&other_info,0,sizeof(other_info));
    memset(percpu,0,sizeof(percpu));memset(other_percpu,0,sizeof(other_percpu));
    memset(exceptions,0,sizeof(exceptions));memset(buckets,0,sizeof(buckets));
    memset(&ordinary,0,sizeof(ordinary));memset(&competitor,0,sizeof(competitor));
    pool_held=fnhe_held=rcu_held=cpu_held=releases=uncached=dev_puts=fib_freed=nh_queued=0;
    competing_route=NULL;replace_on_get=NULL;replacement_info=NULL;pending_nh=NULL;pending_nh_callback=NULL;
    factory.pages=backing;assert(lsf_prepaid_initialize(&factory.pool));
    assert(lsf_prepaid_context_create(&factory.pool,scope,LSF_TCP_BYTES,&factory.contexts[0].key));
    assert(lsf_prepaid_blob_allocate(&factory.pool,factory.contexts[0].key,64,LSF_PREPAID_SOCK_BLOB,&socket_birth,&socket_offset));
    fi.fib_clntref=1;fi.fib_nhs=2;
    fi.fib_nh[0].nh_common.nhc_family=AF_INET;fi.fib_nh[0].nh_common.nhc_pcpu_rth_output=percpu;
    fi.fib_nh[0].nh_common.nhc_exceptions=buckets;
    nh.refcnt=1;nh.nh_info=&info;info.nh_parent=&nh;info.family=AF_INET;info.fib_nhc.nhc_family=AF_INET;
    info.fib_nhc.nhc_pcpu_rth_output=percpu;info.fib_nhc.nhc_exceptions=buckets;
    other_info=info;other_info.fib_nhc.nhc_pcpu_rth_output=other_percpu;
    ordinary.dst.refs=1;competitor.dst.refs=1;
}
static struct rtable *birth(bool input)
{
    struct lsf_prepaid_ticket ticket;lsf_u64 offset;struct rtable *rt;
    assert(lsf_prepaid_child_allocate(&factory.pool,factory.contexts[0].key,sizeof(*rt),LSF_PREPAID_ROUTE,socket_birth,&ticket,&offset));
    rt=(void *)(backing+offset);rt->dst.refs=1;rt->input=input;return rt;
}
static struct fib_result fib_result(void) { return (struct fib_result){&fi.fib_nh[0].nh_common,0}; }
static struct fib_result nh_result(void) { fi.nh=&nh;return (struct fib_result){&info.fib_nhc,0}; }
static void attach(struct rtable *rt) { struct fib_result res=fib_result();assert(lsf_prepaid_route_parent_attach(rt,&res,&fi,true)==0 && fi.fib_clntref==2); }
static struct lsf_prepaid_view *record(struct rtable *rt)
{ struct lsf_factory_blob b;assert(lsf_factory_blob_lookup_locked(rt,LSF_PREPAID_ROUTE,&b)==1);return &factory.pool.records[b.ticket.slot]; }
static void close_root(void) { factory.pool.contexts[0].closed=1; }
int main(void)
{
    struct rtable *rt,*found;struct lsf_route_cache_owner owner;
    struct fib_result res;struct lsf_prepaid_view *view;unsigned int live;
    reset();rt=birth(true);res=fib_result();
#ifdef LSF_OLD_CACHE
    close_root();assert(rt_cache_route(res.nhc,rt));
    assert(res.nhc->nhc_rth_input==rt && rt->dst.refs==2);
    puts("CACHE_OLD publication-after-root-close RED");
    assert(fi.fib_clntref==1);fib_info_put(&fi);assert(fib_freed==1 && res.nhc->nhc_rth_input==rt);
    puts("CACHE_OLD cached-route-outlives-unreferenced-parent RED");return 2;
#endif
    attach(rt);view=record(rt);assert(view->route_cache.parent==(lsf_u64)(uintptr_t)&fi);
    observed("actual-fib-reference-before-cache-publication");
    reset();rt=birth(true);res=fib_result();fi.fib_clntref=0;
    assert(lsf_prepaid_route_parent_attach(rt,&res,&fi,true)==-EAGAIN && !fi.fib_clntref);
    assert(lsf_route_cache_empty(&record(rt)->route_cache));observed("dead-fib-parent-is-not-revived");
    reset();rt=birth(true);res=fib_result();close_root();
    assert(lsf_prepaid_route_parent_attach(rt,&res,&fi,true)==-EOPNOTSUPP && fi.fib_clntref==1);
    assert(lsf_route_cache_empty(&record(rt)->route_cache));observed("refused-transfer-returns-only-acquired-parent-reference");
    reset();rt=birth(true);res=nh_result();replace_on_get=&nh;replacement_info=&other_info;
    assert(lsf_prepaid_route_parent_attach(rt,&res,&fi,true)==-EAGAIN && nh.refcnt==1);
    assert(lsf_route_cache_empty(&record(rt)->route_cache));observed("replacement-between-real-get-and-validation-refuses");
    reset();rt=birth(true);res=nh_result();
    assert(lsf_prepaid_route_parent_attach(rt,&res,&fi,true)==0 && nh.refcnt==2);
    assert(record(rt)->route_cache.parent_kind==LSF_ROUTE_PARENT_NH);observed("actual-referenced-leaf-nexthop-transfer");
    reset();rt=birth(true);attach(rt);res=fib_result();res.nhc->nhc_rth_input=&ordinary;
    assert(lsf_prepaid_rt_cache_route(res.nhc,rt) && rt->dst.refs==2 && !ordinary.dst.refs);
    assert(uncached==1 && releases==1);observed("original-successful-cas-replacement-cleanup-preserved");
    reset();rt=birth(true);attach(rt);res=fib_result();competing_route=&competitor;
    assert(!lsf_prepaid_rt_cache_route(res.nhc,rt) && rt->dst.refs==1);
    assert(res.nhc->nhc_rth_input==&competitor && competitor.dst.refs==1 && releases==1 && !uncached);
    observed("real-cas-loser-cleans-only-its-extra-dst-hold");
    reset();rt=birth(false);attach(rt);res=fib_result();
    assert(lsf_prepaid_rt_cache_route(res.nhc,rt) && percpu[1]==rt && !percpu[0] && !cpu_held);
    assert(record(rt)->route_cache.cpu==1);observed("actual-output-cpu-pinned-through-publication");
    reset();rt=birth(true);attach(rt);res=fib_result();close_root();
    assert(!lsf_prepaid_rt_cache_route(res.nhc,rt) && !res.nhc->nhc_rth_input && rt->dst.refs==1);
    assert(!record(rt)->route_cache.cache_kind && !releases);observed("root-close-before-publication-refuses-without-hold");
    reset();rt=birth(true);attach(rt);res=fib_result();assert(lsf_prepaid_rt_cache_route(res.nhc,rt));
    close_root();lsf_prepaid_route_cache_drain(&factory.contexts[0]);
    assert(!res.nhc->nhc_rth_input && rt->dst.refs==1 && releases==2 && uncached==1 && fi.fib_clntref==2);
    lsf_prepaid_route_cache_drain(&factory.contexts[0]);assert(rt->dst.refs==1 && releases==3 && uncached==1);
    observed("publication-before-close-drains-cache-and-temporary-holds-separately");
    reset();rt=birth(true);attach(rt);res=fib_result();assert(lsf_prepaid_rt_cache_route(res.nhc,rt));
    res.nhc->nhc_rth_input=&competitor;dst_release(&rt->dst);close_root();lsf_prepaid_route_cache_drain(&factory.contexts[0]);
    assert(res.nhc->nhc_rth_input==&competitor && competitor.dst.refs==1 && rt->dst.refs==1 && releases==2 && !uncached);
    observed("replaced-cache-cell-never-drops-competitor-reference");
    reset();rt=birth(true);attach(rt);res=fib_result();assert(lsf_prepaid_rt_cache_route(res.nhc,rt));
    rt->dst.refs=0;close_root();live=factory.pool.contexts[0].live;
    assert(!lsf_factory_route_current(&factory.contexts[0],2,&found,&owner));
    assert(!rt->dst.refs && factory.pool.contexts[0].live==live && !releases);observed("dead-dst-live-birth-is-not-revived-or-refunded");
    reset();rt=birth(false);res=nh_result();assert(lsf_prepaid_route_parent_attach(rt,&res,&fi,true)==0);
    assert(lsf_prepaid_rt_cache_route(res.nhc,rt));nh.nh_info=&other_info;close_root();
    lsf_prepaid_route_cache_drain(&factory.contexts[0]);
    assert(percpu[1]==rt && !other_percpu[1] && rt->dst.refs==2 && nh.refcnt==2 && releases==1);
    observed("replaceable-nh-info-change-never-follows-saved-cache-cell");
    reset();rt=birth(false);res=nh_result();assert(lsf_prepaid_route_parent_attach(rt,&res,&fi,true)==0);
    assert(lsf_prepaid_rt_cache_route(res.nhc,rt));info.fib_nhc.nhc_pcpu_rth_output=other_percpu;close_root();
    lsf_prepaid_route_cache_drain(&factory.contexts[0]);
    assert(percpu[1]==rt && !other_percpu[1] && rt->dst.refs==2 && releases==1);
    observed("nh-info-address-aba-recomputes-current-percpu-allocation");
    reset();rt=birth(true);attach(rt);exceptions[0].fnhe_daddr=42;exceptions[0].fnhe_genid=9;
    exceptions[0].fnhe_rth_input=&ordinary;buckets[0].chain=&exceptions[0];
    assert(lsf_prepaid_rt_bind_exception(rt,&exceptions[0],42,true));
    assert(!ordinary.dst.refs && rt->dst.refs==2 && dev_puts==1 && releases==1 && exceptions[0].fnhe_stamp==jiffies);
    close_root();lsf_prepaid_route_cache_drain(&factory.contexts[0]);
    assert(!exceptions[0].fnhe_rth_input && rt->dst.refs==1 && dev_puts==2 && releases==3);
    observed("real-exception-key-lock-publication-and-original-cleanup");
    reset();rt=birth(true);attach(rt);exceptions[0].fnhe_daddr=42;exceptions[0].fnhe_genid=8;
    exceptions[0].fnhe_rth_input=&ordinary;exceptions[0].fnhe_rth_output=&competitor;
    assert(lsf_prepaid_rt_bind_exception(rt,&exceptions[0],42,true));
    assert(!ordinary.dst.refs && !competitor.dst.refs && dev_puts==2 && releases==2 && exceptions[0].fnhe_genid==9);
    observed("maintained-exception-generation-flush-preserves-both-original-puts");
    reset();rt=birth(true);attach(rt);exceptions[0].fnhe_daddr=42;exceptions[0].fnhe_genid=9;
    buckets[0].chain=&exceptions[0];assert(lsf_prepaid_rt_bind_exception(rt,&exceptions[0],42,true));
    exceptions[1].fnhe_daddr=42;exceptions[1].fnhe_rth_input=&competitor;buckets[0].chain=&exceptions[1];
    dst_release(&rt->dst);close_root();lsf_prepaid_route_cache_drain(&factory.contexts[0]);
    assert(exceptions[1].fnhe_rth_input==&competitor && competitor.dst.refs==1 && rt->dst.refs==1 && !dev_puts);
    observed("replacement-exception-is-relooked-up-without-stale-pointer");
    reset();rt=birth(true);attach(rt);exceptions[0].fnhe_daddr=42;exceptions[0].fnhe_genid=9;
    buckets[0].chain=&exceptions[0];assert(lsf_prepaid_rt_bind_exception(rt,&exceptions[0],42,true));
    for(unsigned int i=0;i<11;i++){exceptions[i].fnhe_daddr=100+i;exceptions[i].fnhe_next=&exceptions[i+1];}
    close_root();lsf_prepaid_route_cache_drain(&factory.contexts[0]);
    assert(factory.uncertain && factory.pool.contexts[0].poisoned && rt->dst.refs==2 && fi.fib_clntref==2 && !dev_puts);
    observed("unknown-long-exception-chain-poisons-and-retains-owners");
    reset();rt=birth(true);attach(rt);view=record(rt);live=factory.pool.contexts[0].live;
    assert(lsf_factory_route_return(rt)==-1 && view->phase==LSF_PREPAID_LIVE && factory.pool.contexts[0].live==live && fi.fib_clntref==2);
    observed("view-finish-refuses-uncleared-parent-metadata");
    reset();rt=birth(true);attach(rt);view=record(rt);dst_release(&rt->dst);
    assert(lsf_prepaid_route_cache_return(rt)==1 && fi.fib_clntref==1 && view->phase==LSF_PREPAID_RETURNED);
    assert(lsf_route_cache_empty(&view->route_cache));observed("actual-parent-put-precedes-final-view-return");
    reset();rt=birth(true);res=nh_result();assert(lsf_prepaid_route_parent_attach(rt,&res,&fi,true)==0);
    nexthop_put(&nh);dst_release(&rt->dst);assert(lsf_prepaid_route_cache_return(rt)==1 && nh_queued==1 && pending_nh==&nh.rcu);
    assert(pending_nh_callback==nexthop_free_rcu);observed("actual-final-nexthop-put-queues-original-rcu-callback");
    reset();rt=birth(true);attach(rt);view=record(rt);view->owner_generation++;
    assert(lsf_prepaid_route_cache_return(rt)==-1 && fi.fib_clntref==2 && view->phase==LSF_PREPAID_LIVE);
    observed("stale-generation-retains-parent-and-route");
    reset();rt=birth(true);attach(rt);res=fib_result();assert(lsf_prepaid_rt_cache_route(res.nhc,rt));
    view=record(rt);view->deferred=LSF_PREPAID_QUEUED;close_root();
    lsf_prepaid_route_cache_drain(&factory.contexts[0]);assert(rt->dst.refs==2 && !releases);
    observed("already-queued-dst-is-not-a-new-drain-candidate");
    reset();assert(lsf_prepaid_route_cache_return(&ordinary)==0);
    assert(lsf_prepaid_route_cache_return(backing+1)==-1 && factory.pool.poisoned);
    observed("outside-normal-return-and-unknown-interior-refusal-remain-distinct");
    return 0;
}
