/* SPDX-License-Identifier: GPL-2.0-only */
/* Supplemental actual selected bodies with explicit serialized list, policy,
 * lock and RCU doubles. Not Linux layout, concurrency, LSM or final-free proof. */
#include "reference-io.h"
#include <stdbool.h>
#include "prepaid.h"
#define CONFIG_LSF_STREAM_FACTORY 1
#define EOPNOTSUPP 95
#define ENOMEM 12
#define GFP_ATOMIC 4u
#define SEL_NETPORT_HASH_SIZE 256u
#define SEL_NETPORT_HASH_BKT_LIMIT 16
#define unlikely(value) (value)
#define READ_ONCE(value) (value)
#define WRITE_ONCE(value, new_value) ((value) = (new_value))
#define pr_warn(...) ((void)0)
#define container_of(value, type, member) ((type *)((char *)(value) - offsetof(type, member)))
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
struct list_head { struct list_head *next, *prev; };
struct rcu_head { unsigned int marker; };
struct netport_security_struct { u16 port; u8 protocol; u32 sid; };
struct sel_netport { struct netport_security_struct psec; struct list_head list; struct rcu_head rcu; };
struct sel_netport_bkt { int size; struct list_head list; };
static struct sel_netport_bkt sel_netport_hash[SEL_NETPORT_HASH_SIZE];
static unsigned int sel_netport_lock, pool_lock, cache_held, pool_held, read_held;
static void (*before_cache_lock)(void);
static void take_cache(unsigned int *lock)
{
    void (*race)(void) = before_cache_lock;
    assert(lock == &sel_netport_lock && !cache_held && !pool_held);
    before_cache_lock = NULL;
    if (race) race();
    assert(!cache_held && !pool_held);
    cache_held = 1;
}
static void drop_cache(unsigned int *lock)
{
    assert(lock == &sel_netport_lock && cache_held && !pool_held);
    cache_held = 0;
}
#define spin_lock_bh(lock) take_cache(lock)
#define spin_unlock_bh(lock) drop_cache(lock)
#define spin_lock_irqsave(lock, flags) do { assert((lock) == &pool_lock && !pool_held); pool_held = 1; (flags) = 0; } while (0)
#define spin_unlock_irqrestore(lock, flags) do { assert((lock) == &pool_lock && pool_held); (void)(flags); pool_held = 0; } while (0)
#define lockdep_is_held(lock) ((lock) == &sel_netport_lock && cache_held)
#define rcu_read_lock() (++read_held)
#define rcu_read_unlock() do { assert(read_held); --read_held; } while (0)
#define rcu_dereference_protected(value, condition) (assert(condition), (value))
#define list_entry(value, type, member) container_of(value, type, member)
#define list_tail_rcu(head) ((head)->prev)
#define list_for_each_entry_rcu(port, head, member) \
    for (struct list_head *cursor = (head)->next; cursor != (head) && \
         ((port) = list_entry(cursor, struct sel_netport, member), true); cursor = cursor->next)
#define list_for_each_entry_safe(port, tmp, head, member) \
    for (struct list_head *cursor = (head)->next, *next = cursor->next; cursor != (head) && \
         ((port) = list_entry(cursor, struct sel_netport, member), (tmp) = NULL, (void)(tmp), true); \
         cursor = next, next = cursor->next)
static void init_list(struct list_head *head) { head->next = head->prev = head; }
static void list_add_rcu(struct list_head *node, struct list_head *head)
{
    assert(cache_held);
    node->next = head->next; node->prev = head;
    head->next->prev = node; head->next = node;
}
static void list_del_rcu(struct list_head *node)
{
    assert(cache_held);
    node->prev->next = node->next; node->next->prev = node->prev;
}
struct lsf_factory_context { struct lsf_prepaid_key key; };
struct lsf_factory_blob { struct lsf_factory_context *context; struct lsf_prepaid_ticket ticket; };
static struct {
    struct lsf_prepaid pool;
    struct lsf_factory_context contexts[LSF_FACTORY_CONTEXTS];
    void *pages;
    unsigned int uncertain;
} factory;
static _Alignas(64) unsigned char backing[LSF_BACKING_BYTES];
static struct sel_netport normal[32];
static unsigned int normal_allocated, normal_freed, policy_calls, pending_count;
static int policy_error;
static struct lsf_factory_blob parent;
static struct { struct rcu_head *head; void (*done)(struct rcu_head *); } pending[LSF_ALLOCATION_SLOTS];
static void *page_address(void *pages) { assert(pages == backing); return pages; }
static void call_rcu(struct rcu_head *head, void (*done)(struct rcu_head *))
{
    assert(cache_held && !pool_held && pending_count < LSF_ALLOCATION_SLOTS);
    pending[pending_count].head = head; pending[pending_count++].done = done;
}
static void normal_callback(struct rcu_head *head)
{
    struct sel_netport *port = container_of(head, struct sel_netport, rcu);
    assert(port >= normal && port < normal + 32);
    normal_freed++;
}
#define kfree_rcu(port, member) call_rcu(&(port)->member, normal_callback)
static void *kzalloc(size_t bytes, unsigned int priority)
{
    assert(cache_held && priority == GFP_ATOMIC && bytes == sizeof(struct sel_netport));
    assert(normal_allocated < 32);
    return &normal[normal_allocated++];
}
static int security_port_sid(u8 protocol, u16 port, u32 *sid)
{
    assert(cache_held && protocol == 6);
    policy_calls++;
    if (policy_error) return policy_error;
    *sid = 9000u + port;
    return 0;
}
#include "netport-derived-reference.h"

static void reset(void)
{
    struct lsf_scope scope = {{1,2,3,4,5,6,7,8}};
    struct lsf_factory_context *context = &factory.contexts[0];
    lsf_u64 offset;
    unsigned int i;
    memset(&factory, 0, sizeof(factory)); memset(backing, 0, sizeof(backing));
    memset(normal, 0, sizeof(normal)); memset(pending, 0, sizeof(pending));
    normal_allocated = normal_freed = policy_calls = pending_count = 0;
    cache_held = pool_held = read_held = 0; before_cache_lock = NULL; policy_error = 0;
    for (i = 0; i < SEL_NETPORT_HASH_SIZE; ++i) {
        init_list(&sel_netport_hash[i].list); sel_netport_hash[i].size = 0;
    }
    factory.pages = backing;
    assert(lsf_prepaid_initialize(&factory.pool));
    assert(lsf_prepaid_context_create(&factory.pool, scope, LSF_TCP_BYTES, &context->key));
    parent.context = context;
    assert(lsf_prepaid_allocate(&factory.pool, context->key, 64, 0,
        (struct lsf_prepaid_ticket){0}, &parent.ticket, &offset));
}
#ifndef LSF_OLD_NETPORT
static void observed(const char *label)
{
    assert(!cache_held && !pool_held && !read_held);
    lsf_ref_write("NETPORT_CONTROL ", 16);
    lsf_ref_write(label, lsf_ref_length(label)); lsf_ref_write(" PASS\n", 6);
}
static void callbacks(void)
{
    unsigned int i, count = pending_count;
    assert(!cache_held && !pool_held && !read_held);
    pending_count = 0;
    for (i = 0; i < count; ++i) pending[i].done(pending[i].head);
}
static void flush_race(void) { sel_netport_flush(); callbacks(); }
#endif

int main(void)
{
    u32 sid;
    reset();
#ifdef LSF_OLD_NETPORT
    assert(sel_netport_sid_slow(6, 80, &sid) == 0);
    assert(normal_allocated == 1 && policy_calls == 1 && sid == 9080);
    puts("NETPORT_OLD general-cache-allocation RED");
    return 2;
#else
    struct lsf_prepaid_context *owner;
    struct lsf_factory_blob birth;
    struct lsf_factory_blob other_parent;
    struct lsf_prepaid_ticket candidate, bad;
    struct lsf_factory_context *other;
    struct lsf_scope scope = {{1,2,3,4,5,6,7,9}};
    unsigned int bucket, i;
    void *port, *address;
    lsf_u64 other_offset;
    owner = &factory.pool.contexts[parent.context->key.slot];
    assert(lsf_prepaid_netport_sid(6, 80, &sid, &parent) == 0 && sid == 9080);
    assert(!normal_allocated && policy_calls == 1 && owner->live == 2);
    port = sel_netport_find(6, 80);
    assert(lsf_factory_blob_lookup(port, LSF_PREPAID_NETPORT, &birth) == 1);
    assert(factory.pool.records[birth.ticket.slot].deferred == LSF_PREPAID_PUBLISHED);
    observed("actual-miss-uses-original-child-before-publication");
    assert(lsf_prepaid_netport_sid(6, 80, &sid, &parent) == 0 && policy_calls == 1);
    assert(owner->live == 2 && !normal_allocated);
    observed("actual-cache-hit-does-not-allocate");
    other = &factory.contexts[1];
    assert(lsf_prepaid_context_create(&factory.pool, scope, LSF_TCP_BYTES, &other->key));
    other_parent.context = other;
    assert(lsf_prepaid_allocate(&factory.pool, other->key, 64, 0,
        (struct lsf_prepaid_ticket){0}, &other_parent.ticket, &other_offset));
    assert(lsf_prepaid_netport_sid(6, 80, &sid, &other_parent) == 0);
    assert(owner->live == 2 && factory.pool.contexts[1].live == 1);
    observed("shared-hit-does-not-transfer-original-cache-owner");
    assert(lsf_prepaid_netport_sid(6, 80, &sid, NULL) == -EOPNOTSUPP);
    observed("missing-private-source-refused-even-on-hit");
    for (i = 1; i <= 16; ++i)
        assert(lsf_prepaid_netport_sid(6, (u16)(80 + 256*i), &sid, &parent) == 0);
    assert(sel_netport_hash[80].size == 16 && pending_count == 1 && owner->live == 18 && owner->continuations == 1);
    assert(!normal_allocated && !normal_freed);
    observed("original-sixteen-entry-bucket-evicts-with-retained-callback");
    lsf_prepaid_netport_drain(parent.context);
    assert(sel_netport_hash[80].size == 0 && pending_count == 17 && owner->live == 18 && owner->continuations == 17);
    observed("bounded-drain-detaches-but-does-not-refund");
    callbacks();
    assert(owner->live == 1 && !owner->continuations && !normal_freed);
    observed("actual-selected-callback-retires-each-original-view");
    owner->closed = 1; factory.pool.stopped = 1;
    assert(lsf_prepaid_netport_sid(6, 81, &sid, &parent) == 0 && owner->live == 2);
    assert(!lsf_prepaid_recycle(&factory.pool, parent.context->key));
    lsf_prepaid_netport_drain(parent.context); callbacks();
    assert(owner->live == 1 && !owner->continuations);
    observed("genuine-late-child-after-seal-remains-owned-through-next-drain");
    reset(); policy_error = -7;
    assert(lsf_prepaid_netport_sid(6, 80, &sid, &parent) == -7 && !normal_allocated);
    assert(factory.pool.contexts[0].live == 1 && !sel_netport_hash[80].size);
    observed("original-policy-error-precedes-cache-allocation");
    reset(); factory.pool.contexts[0].cursor = LSF_TCP_BYTES;
    assert(lsf_prepaid_netport_sid(6, 80, &sid, &parent) == -ENOMEM);
    assert(!normal_allocated && !sel_netport_hash[80].size && factory.pool.contexts[0].live == 1);
    observed("original-96k-bound-fails-without-heap-fallback");
    reset();
    assert(lsf_prepaid_netport_sid(6, 80, &sid, &parent) == 0);
    before_cache_lock = flush_race;
    lsf_prepaid_netport_drain(parent.context);
    assert(!pending_count && !sel_netport_hash[80].size && factory.pool.contexts[0].live == 1);
    observed("flush-plus-callback-between-snapshot-and-lock-revalidates-without-dereference");
    reset();
    assert(lsf_prepaid_netport_sid(6, 80, &sid, &parent) == 0);
    port = sel_netport_find(6, 80);
    assert(lsf_factory_blob_lookup(port, LSF_PREPAID_NETPORT, &birth) == 1);
    assert(lsf_factory_netport_candidate(parent.context, birth.ticket.slot, &candidate, &bucket) == 1);
    bad = candidate; bad.generation++;
    assert(!lsf_factory_netport_current(parent.context, bad, bucket, &address));
    assert(!lsf_factory_netport_current(parent.context, candidate, bucket+1, &address));
    other = &factory.contexts[1];
    assert(lsf_prepaid_context_create(&factory.pool, scope, LSF_TCP_BYTES, &other->key));
    assert(!lsf_factory_netport_current(other, candidate, bucket, &address));
    assert(factory.pool.contexts[0].live == 2);
    observed("stale-generation-wrong-bucket-and-foreign-context-cannot-derive-address");
    assert(!lsf_factory_blob_finish(birth, LSF_PREPAID_NETPORT));
    assert(factory.pool.contexts[0].poisoned && factory.pool.contexts[0].live == 2);
    observed("published-cache-entry-cannot-use-synchronous-return");
    reset();
    port = lsf_factory_child_allocate(parent, sizeof(struct sel_netport), LSF_PREPAID_NETPORT);
    assert(port && lsf_factory_netport_publish(port, 256) == -1);
    assert(factory.pool.contexts[0].poisoned && factory.pool.contexts[0].live == 2);
    observed("invalid-bucket-poisons-without-refund");
    reset();
    assert(lsf_prepaid_netport_retire((void *)(backing + 1)));
    assert(factory.pool.poisoned && !normal_freed && !pending_count);
    observed("unknown-interior-cache-pointer-never-reaches-normal-free");
    reset();
    assert(lsf_prepaid_netport_retire((void *)(backing + factory.pool.records[parent.ticket.slot].offset)));
    assert(factory.pool.poisoned && factory.pool.contexts[0].live == 1 && !pending_count);
    observed("wrong-kind-original-object-is-retained");
    reset();
    spin_lock_bh(&sel_netport_lock);
    port = kzalloc(sizeof(struct sel_netport), GFP_ATOMIC);
    ((struct sel_netport *)port)->psec = (struct netport_security_struct){80,6,9};
    sel_netport_insert(port);
    spin_unlock_bh(&sel_netport_lock);
    sel_netport_flush(); callbacks();
    assert(normal_allocated == 1 && normal_freed == 1 && factory.pool.contexts[0].live == 1);
    observed("ordinary-cache-insert-and-free-preserve-original-allocator");
    reset();
    assert(!lsf_prepaid_blob_allocate(&factory.pool, parent.context->key, 64, LSF_PREPAID_NETPORT, &bad, &(lsf_u64){0}));
    assert(lsf_prepaid_return(&factory.pool, parent.context->key, parent.ticket));
    assert(!lsf_factory_child_allocate(parent, 64, LSF_PREPAID_NETPORT));
    observed("root-blob-and-retired-parent-cannot-manufacture-cache-birth");
    assert(sizeof(factory) + LSF_BACKING_BYTES < LSF_BOOTSTRAP_CEILING);
    assert(LSF_ALLOCATION_SLOTS == 256 && LSF_OWNER_SLOTS == 64 && LSF_TCP_BYTES == 98304 && LSF_DNS_BYTES == 65536);
    observed("same-fixed-record-and-original-backing-profile");
    return 0;
#endif
}
