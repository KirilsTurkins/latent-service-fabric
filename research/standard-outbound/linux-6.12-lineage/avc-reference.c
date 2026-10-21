/* SPDX-License-Identifier: GPL-2.0-only */
/* Supplemental serialized type/list/cache/lock/RCU doubles. Actual selected
 * maintained destructors + private graph/factory bodies; NOT Linux execution. */
#include "reference-io.h"
#include <stdbool.h>
#define current get_current()
#include "prepaid.h"
#define LSF_STREAM_AVC_SOURCE 1
#define EOPNOTSUPP 95
#define GFP_NOWAIT 1u
#define __GFP_NOWARN 2u
#define WRITE_ONCE(value, replacement) ((value) = (replacement))
#define container_of(value, type, member) ((type *)((char *)(value) - offsetof(type, member)))
struct list_head { struct list_head *next, *prev; };
struct hlist_node { struct hlist_node *next, **pprev; };
struct hlist_head { struct hlist_node *first; };
struct rcu_head { unsigned int marker; };
/* Explicit reference layouts, not claimed maintained compiled geometry. */
struct extended_perms_data { unsigned int p[8]; };
struct extended_perms_decision {
    unsigned char driver, used;
    struct extended_perms_data *allowed, *auditallow, *dontaudit;
};
struct av_decision { unsigned int allowed, auditallow, auditdeny, seqno, flags; };
struct avc_xperms_decision_node { struct extended_perms_decision xpd; struct list_head xpd_list; };
struct avc_xperms_node { unsigned int xp; struct list_head xpd_head; };
struct avc_entry { unsigned int ssid, tsid; unsigned short tclass; struct av_decision avd; struct avc_xperms_node *xp_node; };
struct avc_node { struct avc_entry ae; struct hlist_node list; struct rcu_head rhead; };
static struct { unsigned int avc_cache_threshold; struct { struct hlist_head slots[512]; unsigned int slots_lock[512]; unsigned int active_nodes; } avc_cache; } selinux_avc;
static unsigned int pool_lock, pool_held, cache_held, normal_allocated, normal_freed, logical_frees, logical_allocations, reclaims;
static unsigned int avc_node_cachep, avc_xperms_data_cachep, avc_xperms_decision_cachep, avc_xperms_cachep;
static void (*before_cache_lock)(void);
static void lock(unsigned int *value)
{
    if (value == &pool_lock) { assert(!pool_held); pool_held = 1; }
    else {
        void (*race)(void) = before_cache_lock;
        assert(!pool_held && !cache_held); before_cache_lock = NULL;
        if (race) race();
        assert(!pool_held && !cache_held); cache_held = 1;
    }
}
static void unlock(unsigned int *value)
{
    if (value == &pool_lock) { assert(pool_held); pool_held = 0; }
    else { assert(cache_held && !pool_held); cache_held = 0; }
}
#define spin_lock_irqsave(value, flags) do { lock(value); (flags) = 0; } while (0)
#define spin_unlock_irqrestore(value, flags) do { (void)(flags); unlock(value); } while (0)
#define avc_cache_stats_incr(field) (++logical_##field)
#define atomic_dec(value) (--*(value))
#define atomic_inc_return(value) (++*(value))
#define INIT_HLIST_NODE(node) do { (node)->next = NULL; (node)->pprev = NULL; } while (0)
#define list_entry(value, type, member) container_of(value, type, member)
#define list_for_each_entry_safe(node, tmp, head, member) \
    for (struct list_head *cursor = (head)->next, *following = cursor->next; cursor != (head) && \
        ((node) = list_entry(cursor, struct avc_xperms_decision_node, member), (tmp) = NULL, (void)(tmp), true); \
        cursor = following, following = cursor->next)
static void list_init(struct list_head *head) { head->next = head->prev = head; }
static void list_add(struct list_head *node, struct list_head *head)
{ node->next = head->next; node->prev = head; head->next->prev = node; head->next = node; }
static void list_del(struct list_head *node)
{ node->prev->next = node->next; node->next->prev = node->prev; }
static void hlist_add(struct hlist_node *node, struct hlist_head *head)
{ assert(cache_held); node->next = head->first; if (node->next) node->next->pprev = &node->next; head->first = node; node->pprev = &head->first; }
static void hlist_del_rcu(struct hlist_node *node)
{ assert(cache_held && node->pprev); *node->pprev = node->next; if (node->next) node->next->pprev = node->pprev; }
static void hlist_replace_rcu(struct hlist_node *old, struct hlist_node *node)
{ assert(cache_held && old->pprev); node->next = old->next; node->pprev = old->pprev; *node->pprev = node; if (node->next) node->next->pprev = &node->next; }
struct lsf_factory_context { struct lsf_prepaid_key key; };
struct lsf_factory_blob { struct lsf_factory_context *context; struct lsf_prepaid_ticket ticket; };
static struct { struct lsf_prepaid pool; struct lsf_factory_context contexts[4]; void *pages; unsigned int uncertain; } factory;
static _Alignas(64) unsigned char backing[LSF_BACKING_BYTES];
static struct avc_node normal[8];
static struct lsf_factory_blob source;
static struct { struct rcu_head *head; void (*done)(struct rcu_head *); } pending[LSF_ALLOCATION_SLOTS];
static unsigned int pending_count;
static void *page_address(void *pages) { assert(pages == backing); return pages; }
static void call_rcu(struct rcu_head *head, void (*done)(struct rcu_head *))
{ assert(cache_held && !pool_held && pending_count < LSF_ALLOCATION_SLOTS); pending[pending_count].head = head; pending[pending_count++].done = done; }
static void kmem_cache_free(unsigned int cache, void *address)
{ (void)cache; assert((uintptr_t)address < (uintptr_t)backing || (uintptr_t)address >= (uintptr_t)(backing + sizeof(backing))); normal_freed++; }
static void *kmem_cache_zalloc(unsigned int cache, unsigned int flags)
{ assert(cache == avc_node_cachep && flags == (GFP_NOWAIT | __GFP_NOWARN) && normal_allocated < 8); return &normal[normal_allocated++]; }
static int avc_reclaim_node(void) { reclaims++; return 0; }
#include "avc-derived-reference.h"

static void reset(void)
{
    struct lsf_scope scope = {{1,2,3,4,5,6,7,8}};
    lsf_u64 offset;
    memset(&factory, 0, sizeof(factory)); memset(backing, 0, sizeof(backing));
    memset(normal, 0, sizeof(normal)); memset(&selinux_avc, 0, sizeof(selinux_avc));
    pool_held = cache_held = normal_allocated = normal_freed = logical_frees = logical_allocations = reclaims = pending_count = 0;
    before_cache_lock = NULL; selinux_avc.avc_cache_threshold = 512;
    factory.pages = backing;
    assert(lsf_prepaid_initialize(&factory.pool));
    assert(lsf_prepaid_context_create(&factory.pool, scope, LSF_TCP_BYTES, &factory.contexts[0].key));
    source.context = &factory.contexts[0];
    assert(lsf_prepaid_allocate(&factory.pool, source.context->key, 64, 0,
        (struct lsf_prepaid_ticket){0}, &source.ticket, &offset));
}
#ifndef LSF_OLD_AVC
static void observed(const char *name)
{ assert(!pool_held && !cache_held); lsf_ref_write("AVC_CONTROL ",12); lsf_ref_write(name,lsf_ref_length(name)); lsf_ref_write(" PASS\n",6); }
static struct avc_node *node(void) { return lsf_prepaid_avc_alloc_node(&source); }
static void publish(struct avc_node *value, unsigned int bucket)
{ cache_held = 1; assert(!lsf_prepaid_avc_node_publish(value,bucket,&source)); hlist_add(&value->list,&selinux_avc.avc_cache.slots[bucket]); cache_held = 0; }
static void callbacks(void)
{ unsigned int count = pending_count; pending_count = 0; for (unsigned int i = 0; i < count; ++i) pending[i].done(pending[i].head); }
static struct lsf_factory_blob identity(const void *address, unsigned int kind)
{ struct lsf_factory_blob copy; assert(lsf_factory_blob_lookup(address,kind,&copy)==1); return copy; }
static struct avc_xperms_decision_node *decision(void)
{
    struct avc_xperms_decision_node *value = lsf_factory_child_allocate(source,sizeof(*value),LSF_PREPAID_AVC_DECISION);
    assert(value); value->xpd.allowed = lsf_factory_child_allocate(source,sizeof(*value->xpd.allowed),LSF_PREPAID_AVC_DATA);
    assert(value->xpd.allowed); return value;
}
static struct avc_xperms_node *xperms(struct avc_node *value)
{
    struct avc_xperms_node *xp = lsf_factory_child_allocate(source,sizeof(*xp),LSF_PREPAID_AVC_XPERMS);
    assert(xp); list_init(&xp->xpd_head); value->ae.xp_node = xp; return xp;
}
static void evict_race(void)
{ cache_held = 1; avc_node_delete(container_of(selinux_avc.avc_cache.slots[6].first,struct avc_node,list)); cache_held = 0; callbacks(); }
#endif

int main(void)
{
    reset();
    (void)kmem_cache_zalloc;
#ifdef LSF_OLD_AVC
    (void)avc_node_kill; (void)avc_node_replace;
    (void)lsf_prepaid_avc_node_publish; (void)lsf_prepaid_avc_node_replace;
    (void)list_init; (void)list_add; (void)hlist_add;
    assert(avc_alloc_node()); assert(normal_allocated == 1);
    puts("AVC_OLD general-cache-allocation RED"); return 2;
#else
    struct avc_node *a, *b;
    struct lsf_factory_blob original, child;
    struct avc_xperms_node *xp;
    struct avc_xperms_decision_node *part;
    struct lsf_prepaid_ticket ticket;
    unsigned int bucket;
    void *address = NULL;

    a = node(); assert(a && !normal_allocated); original = identity(a,LSF_PREPAID_AVC_NODE);
    assert(factory.pool.records[original.ticket.slot].bytes >= sizeof(*a)); observed("typed-original-birth");
    publish(a,511); assert(lsf_factory_avc_candidate(source.context,original.ticket.slot,&ticket,&bucket)==1 && bucket==511);
    observed("real-bucket-before-publication");
    cache_held = 1; avc_node_delete(a); cache_held = 0;
    assert(pending_count==1 && factory.pool.contexts[0].continuations==1 && factory.pool.records[original.ticket.slot].phase==LSF_PREPAID_LIVE);
    observed("unlink-retains-through-rcu");
    callbacks(); assert(factory.pool.records[original.ticket.slot].phase==LSF_PREPAID_RETURNED && !factory.pool.contexts[0].continuations);
    assert(factory.pool.records[0].phase==LSF_PREPAID_LIVE); observed("callback-not-backing-refund");

    reset(); part=decision(); original=identity(part,LSF_PREPAID_AVC_DECISION); child=identity(part->xpd.allowed,LSF_PREPAID_AVC_DATA);
    assert(!part->xpd.used); avc_xperms_decision_free(part);
    assert(factory.pool.records[original.ticket.slot].phase==LSF_PREPAID_RETURNED && factory.pool.records[child.ticket.slot].phase==LSF_PREPAID_RETURNED);
    observed("partial-allocation-pointers-before-used");

    reset(); a=node(); xp=xperms(a); part=decision(); list_add(&part->xpd_list,&xp->xpd_head); part->xpd.auditallow=part->xpd.allowed;
    original=identity(a,LSF_PREPAID_AVC_NODE); child=identity(part->xpd.allowed,LSF_PREPAID_AVC_DATA);
    avc_node_kill(a); assert(factory.pool.records[original.ticket.slot].phase==LSF_PREPAID_LIVE && factory.pool.records[child.ticket.slot].phase==LSF_PREPAID_LIVE && !normal_freed);
    observed("alias-graph-retains-before-any-return");

    reset(); a=node(); xp=xperms(a); part=decision(); list_add(&part->xpd_list,&xp->xpd_head); part->xpd_list.next=&part->xpd_list;
    original=identity(a,LSF_PREPAID_AVC_NODE); avc_node_kill(a);
    assert(factory.pool.records[original.ticket.slot].phase==LSF_PREPAID_LIVE && !normal_freed); observed("nonhead-cycle-refuses");

    reset(); a=node(); xp=xperms(a); part=decision(); list_add(&part->xpd_list,&xp->xpd_head);
    original=identity(a,LSF_PREPAID_AVC_NODE); child=identity(part->xpd.allowed,LSF_PREPAID_AVC_DATA);
    publish(a,9); cache_held=1; avc_node_delete(a); cache_held=0; callbacks();
    assert(factory.pool.records[original.ticket.slot].phase==LSF_PREPAID_RETURNED && factory.pool.records[child.ticket.slot].phase==LSF_PREPAID_RETURNED);
    observed("complete-nested-graph-final-return");

    reset(); a=node(); b=node(); publish(a,7); original=identity(a,LSF_PREPAID_AVC_NODE); child=identity(b,LSF_PREPAID_AVC_NODE);
    cache_held=1; assert(!lsf_prepaid_avc_node_replace(b,a,7,&source)); cache_held=0;
    assert(factory.pool.records[original.ticket.slot].deferred==LSF_PREPAID_QUEUED && factory.pool.records[child.ticket.slot].deferred==LSF_PREPAID_PUBLISHED);
    callbacks(); assert(factory.pool.records[original.ticket.slot].phase==LSF_PREPAID_RETURNED); observed("atomic-cache-replacement");

    reset(); a=node(); b=node(); publish(a,8); original=identity(a,LSF_PREPAID_AVC_NODE); child=identity(b,LSF_PREPAID_AVC_NODE);
    assert(!lsf_prepaid_avc_replace(&factory.pool,source.context->key,child.ticket,source.context->key,original.ticket,1,7));
    assert(factory.pool.records[child.ticket.slot].deferred==LSF_PREPAID_PRIVATE && factory.pool.records[original.ticket.slot].deferred==LSF_PREPAID_PUBLISHED);
    observed("wrong-bucket-preflight-is-atomic");
    factory.pool.contexts[0].continuations=LSF_ALLOCATION_SLOTS;
    assert(!lsf_prepaid_avc_replace(&factory.pool,source.context->key,child.ticket,source.context->key,original.ticket,1,8));
    assert(factory.pool.records[child.ticket.slot].deferred==LSF_PREPAID_PRIVATE); observed("continuation-ceiling-no-orphan");

    reset(); a=node(); publish(a,3); original=identity(a,LSF_PREPAID_AVC_NODE); factory.pool.contexts[0].poisoned=1;
    cache_held=1; avc_node_delete(a); cache_held=0;
    assert(!selinux_avc.avc_cache.slots[3].first && !pending_count && !normal_freed && factory.pool.records[original.ticket.slot].phase==LSF_PREPAID_LIVE);
    observed("revocation-unlinks-poisoned-private-victim");

    reset(); a=node(); publish(a,4); original=identity(a,LSF_PREPAID_AVC_NODE); factory.pool.contexts[0].poisoned=1;
    cache_held=1; avc_node_replace(&normal[0],a); cache_held=0;
    assert(selinux_avc.avc_cache.slots[4].first==&normal[0].list && !pending_count && !normal_freed && factory.pool.records[original.ticket.slot].phase==LSF_PREPAID_LIVE);
    observed("normal-update-proceeds-with-private-quarantine");

    reset(); selinux_avc.avc_cache.active_nodes=1; avc_node_kill(&normal[0]); assert(normal_freed==1);
    observed("normal-allocator-free-unchanged");

    reset(); a=node(); publish(a,5); original=identity(a,LSF_PREPAID_AVC_NODE); ticket=original.ticket; ticket.generation++;
    assert(!lsf_factory_avc_current(source.context,ticket,5,&address) && !address); observed("stale-generation-no-address");
    cache_held=1; avc_node_delete(a); cache_held=0;
    assert(!lsf_factory_avc_current(source.context,original.ticket,5,&address) && !address); observed("queued-candidate-no-address");

    reset(); a=node(); publish(a,6); original=identity(a,LSF_PREPAID_AVC_NODE); before_cache_lock=evict_race;
    lsf_prepaid_avc_drain(source.context); assert(factory.pool.records[original.ticket.slot].phase==LSF_PREPAID_RETURNED && !normal_freed);
    observed("retired-between-snapshot-and-cache-lock");

    reset(); factory.pool.contexts[0].closed=1; a=node(); assert(a && factory.pool.contexts[0].live==2);
    publish(a,10); observed("late-original-descendant-stays-charged");

    reset(); factory.pool.contexts[0].cursor=LSF_TCP_BYTES-64;
    assert(!lsf_factory_child_allocate(source,65,LSF_PREPAID_AVC_DATA));
    assert(factory.pool.contexts[0].cursor==LSF_TCP_BYTES-64); observed("original-ninetysix-kib-refusal");

    reset(); a=node(); original=identity(a,LSF_PREPAID_AVC_NODE);
    assert(lsf_factory_avc_member((char *)a+8,LSF_PREPAID_AVC_NODE,sizeof(*a),&child)<0);
    assert(factory.pool.records[original.ticket.slot].phase==LSF_PREPAID_LIVE && !normal_freed); observed("unknown-interior-retains-no-fallback");

    reset(); a=node(); original=identity(a,LSF_PREPAID_AVC_NODE);
    {
        struct lsf_scope foreign_scope = {{9,2,3,4,5,6,7,8}};
        struct lsf_factory_blob foreign;
        lsf_u64 foreign_offset;
        foreign.context=&factory.contexts[1];
        assert(lsf_prepaid_context_create(&factory.pool,foreign_scope,LSF_TCP_BYTES,&foreign.context->key));
        assert(lsf_prepaid_allocate(&factory.pool,foreign.context->key,64,0,
            (struct lsf_prepaid_ticket){0},&foreign.ticket,&foreign_offset));
        xp=lsf_factory_child_allocate(foreign,sizeof(*xp),LSF_PREPAID_AVC_XPERMS);
        assert(xp); list_init(&xp->xpd_head); a->ae.xp_node=xp;
        child=identity(xp,LSF_PREPAID_AVC_XPERMS);
        avc_node_kill(a);
        assert(factory.pool.records[original.ticket.slot].phase==LSF_PREPAID_LIVE && factory.pool.records[child.ticket.slot].phase==LSF_PREPAID_LIVE);
        assert(factory.pool.contexts[0].live==2 && factory.pool.contexts[1].live==2 && !normal_freed);
    }
    observed("foreign-graph-never-transfers-original-owner");

    reset(); a=node(); publish(a,11); original=identity(a,LSF_PREPAID_AVC_NODE);
    avc_node_kill(a);
    assert(factory.pool.records[original.ticket.slot].phase==LSF_PREPAID_LIVE && factory.pool.records[original.ticket.slot].deferred==LSF_PREPAID_PUBLISHED && !normal_freed);
    observed("published-node-cannot-take-private-failure-free");

    reset(); a=node(); publish(a,12); original=identity(a,LSF_PREPAID_AVC_NODE);
    assert(lsf_factory_avc_queue(a)==1); assert(lsf_factory_avc_queue(a)<0);
    assert(factory.pool.records[original.ticket.slot].phase==LSF_PREPAID_LIVE && factory.pool.contexts[0].continuations==1);
    observed("duplicate-queue-retains-original-continuation");

    reset();
    {
        unsigned int admitted=0;
        while (lsf_factory_child_allocate(source,64,LSF_PREPAID_AVC_DATA)) {
            admitted++;
            assert(admitted<LSF_ALLOCATION_SLOTS);
        }
        assert(admitted==LSF_ALLOCATION_SLOTS-2 && factory.pool.contexts[0].live==LSF_ALLOCATION_SLOTS-1);
        assert(factory.pool.contexts[0].cursor<LSF_TCP_BYTES && !normal_allocated);
    }
    observed("original-fixed-birth-record-ceiling");
    return 0;
#endif
}
