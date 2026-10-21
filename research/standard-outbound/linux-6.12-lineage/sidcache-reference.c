/* SPDX-License-Identifier: GPL-2.0-only */
/* Supplemental serialized type/policy/list/RCU doubles. Actual selected
 * maintained functions and owned factory bodies are injected unchanged by
 * the source deriver. No Linux geometry, concurrency or LSM execution proof. */
#include "reference-io.h"
#undef main
#define current get_current()
#define main netport_reference_main
#include "netport-reference.c"
#undef main
void *memcpy(void *target, const void *source, size_t bytes)
{
    volatile unsigned char *out = target;
    const volatile unsigned char *in = source;
    for (size_t i = 0; i < bytes; ++i) out[i] = in[i];
    return target;
}
static int sid_bytes_equal(const void *a, const void *b, size_t bytes)
{
    const unsigned char *left = a, *right = b;
    for (size_t i = 0; i < bytes; ++i) if (left[i] != right[i]) return 0;
    return 1;
}
#define CONFIG_SECURITY_SELINUX_SID2STR_CACHE_SIZE 2u
#define ENOENT 2
#define rcu_dereference(value) (value)
#define rcu_dereference_raw(value) (value)
#define rcu_assign_pointer(target, value) ((target) = (value))
struct sidtab_entry;
struct sidtab_str_cache {
    struct rcu_head rcu_member;
    struct list_head lru_member;
    struct sidtab_entry *parent;
    u32 len;
    char str[];
};
struct sidtab_entry { struct { u32 len; } context; struct sidtab_str_cache *cache; };
struct sidtab { unsigned int cache_lock, cache_free_slots; struct list_head cache_lru_list; };
static struct sidtab sid_table;
static unsigned int sid_held, sid_normal_allocated, sid_normal_freed, contexts_destroyed;
static _Alignas(64) unsigned char sid_normal[16][256];
static void (*before_sid_lock)(void);
static void sid_lock(unsigned int *lock)
{
    if (lock == &pool_lock) { assert(!pool_held); pool_held = 1; return; }
    void (*race)(void) = before_sid_lock;
    assert(lock == &sid_table.cache_lock && !sid_held && !pool_held);
    before_sid_lock = NULL;
    if (race) race();
    assert(!sid_held && !pool_held);
    sid_held = 1;
}
static void sid_unlock(unsigned int *lock)
{
    if (lock == &pool_lock) { assert(pool_held); pool_held = 0; return; }
    assert(lock == &sid_table.cache_lock && sid_held && !pool_held); sid_held = 0;
}
#undef spin_lock_irqsave
#undef spin_unlock_irqrestore
#undef lockdep_is_held
#define spin_lock_irqsave(lock, flags) do { sid_lock(lock); (flags) = 0; } while (0)
#define spin_unlock_irqrestore(lock, flags) do { (void)(flags); sid_unlock(lock); } while (0)
#define lockdep_is_held(lock) ((lock) == &sid_table.cache_lock && sid_held)
static void sid_list_add(struct list_head *node, struct list_head *head)
{
    assert(sid_held); node->next = head->next; node->prev = head;
    head->next->prev = node; head->next = node;
}
static void sid_list_del(struct list_head *node)
{
    assert(sid_held); node->prev->next = node->next; node->next->prev = node->prev;
}
#define list_add(node, head) sid_list_add(node, head)
#define list_del(node) sid_list_del(node)
#define list_move(node, head) do { sid_list_del(node); sid_list_add(node, head); } while (0)
#define struct_size(pointer, member, length) (sizeof(*(pointer)) + (length))
static void *sid_kmalloc(size_t bytes, unsigned int priority)
{
    assert(priority == GFP_ATOMIC && sid_held && bytes <= 256 && sid_normal_allocated < 16);
    return sid_normal[sid_normal_allocated++];
}
#define kmalloc(bytes, priority) sid_kmalloc(bytes, priority)
static void sid_free(void *value)
{
    if (!value) return;
    bool normal_value = false;
    for (unsigned int i = 0; i < sid_normal_allocated; ++i)
        if (value == sid_normal[i]) normal_value = true;
    assert(normal_value); sid_normal_freed++;
}
#define kfree(value) sid_free(value)
static void sid_call_rcu(struct rcu_head *head, void (*done)(struct rcu_head *))
{
    assert(!sid_held && !pool_held && pending_count < LSF_ALLOCATION_SLOTS);
    pending[pending_count].head = head; pending[pending_count++].done = done;
}
static void sid_normal_callback(struct rcu_head *head)
{
    sid_free(container_of(head, struct sidtab_str_cache, rcu_member));
}
#undef call_rcu
#undef kfree_rcu
#define call_rcu(head, done) sid_call_rcu(head, done)
#define kfree_rcu(value, member) do { if (value) sid_call_rcu(&(value)->member, sid_normal_callback); } while (0)
#define context_destroy(value) do { (void)(value); contexts_destroyed++; } while (0)
int lsf_prepaid_sid2str_put(struct sidtab *, struct sidtab_entry *, const char *, u32,
                           const struct lsf_factory_blob *);
#include "sidcache-derived-reference.h"

static void sid_reset(void)
{
    reset(); memset(&sid_table, 0, sizeof(sid_table)); init_list(&sid_table.cache_lru_list);
    sid_table.cache_free_slots = CONFIG_SECURITY_SELINUX_SID2STR_CACHE_SIZE;
    sid_held = sid_normal_allocated = sid_normal_freed = contexts_destroyed = 0;
    before_sid_lock = NULL;
}
static void sid_observed(const char *label)
{
    assert(!sid_held && !pool_held && !read_held);
    lsf_ref_write("SIDCACHE_CONTROL ", 17); lsf_ref_write(label, lsf_ref_length(label));
    lsf_ref_write(" PASS\n", 6);
}
static struct sidtab_entry race_entry;
static void destroy_snapshot_race(void)
{
    sidtab_destroy_entry(&race_entry);
    race_entry.cache = NULL;
}
#ifdef LSF_OLD_SIDCACHE
int main(void)
{
    struct sidtab_entry entry = {0};
    (void)netport_reference_main;
    (void)sid_bytes_equal;
    (void)sid_observed;
    (void)destroy_snapshot_race;
    sid_reset();
    sidtab_sid2str_put(&sid_table, &entry, "a:b:c", 6);
    assert(entry.cache && sid_normal_allocated == 1 && factory.pool.contexts[0].live == 1);
    puts("SIDCACHE_OLD general-cache-allocation RED");
    return 2;
}
#else
int main(void)
{
    struct sidtab_entry entries[4] = {0};
    struct lsf_factory_blob birth;
    struct lsf_prepaid_ticket ticket, bad;
    struct lsf_prepaid_context *owner;
    lsf_u64 anchor;
    void *address = NULL;
    char *copy = NULL;
    u32 length = 0;
    assert(netport_reference_main() == 0);
    sid_reset(); owner = &factory.pool.contexts[0];
    assert(lsf_prepaid_sid2str_put(&sid_table, &entries[0], "a:b:c", 6, &parent) == 0);
    assert(entries[0].cache && !sid_normal_allocated && owner->live == 2);
    assert(lsf_factory_blob_lookup(entries[0].cache, LSF_PREPAID_SIDCACHE, &birth) == 1);
    assert(factory.pool.records[birth.ticket.slot].cache_anchor == (lsf_u64)(unsigned long)&sid_table);
    sid_observed("actual-private-miss-publishes-original-parent-and-sid_table-before-lru");
    assert(lsf_prepaid_sid2str_get(&sid_table, &entries[0], &copy, &length, &parent) == 0);
    assert(length == 6 && sid_bytes_equal(copy, "a:b:c", 6) && owner->live == 3);
    assert(lsf_prepaid_audit_string_return(copy) == 1 && owner->live == 2);
    sid_observed("actual-cache-hit-copies-through-callers-original-audit-string-birth");
    assert(lsf_factory_sidcache_candidate(parent.context, birth.ticket.slot, &ticket, &anchor) == 1);
    bad = ticket; bad.generation++;
    assert(!lsf_factory_sidcache_current(parent.context, bad, anchor, &address));
    assert(!lsf_factory_sidcache_current(parent.context, ticket, anchor+1, &address));
    sid_observed("wrong-generation-and-sid_table-anchor-cannot-derive-address");
    assert(lsf_prepaid_sid2str_put(&sid_table, &entries[1], "d:e:f", 6, &parent) == 0);
    assert(lsf_prepaid_sid2str_put(&sid_table, &entries[2], "g:h:i", 6, &parent) == 0);
    assert(!entries[0].cache && pending_count == 1 && owner->continuations == 1 && owner->live == 4);
    sid_observed("original-two-entry-lru-eviction-retains-real-callback-before-refund");
    callbacks(); assert(owner->live == 3 && !owner->continuations && !sid_normal_freed);
    sid_observed("actual-callback-returns-original-cache-birth-once");
    lsf_prepaid_sidcache_detach(&sid_table, parent.context, ticket);
    assert(!pending_count);
    sid_observed("already-retired-snapshot-cannot-dereference-reused-storage");
    assert(lsf_factory_blob_lookup(entries[1].cache, LSF_PREPAID_SIDCACHE, &birth) == 1);
    assert(lsf_factory_sidcache_candidate(parent.context, birth.ticket.slot, &ticket, &anchor) == 1);
    lsf_prepaid_sidcache_detach(&sid_table, parent.context, ticket);
    assert(!entries[1].cache && pending_count == 1 && owner->live == 3);
    assert(!lsf_factory_sidcache_current(parent.context, ticket, anchor, &address));
    callbacks(); assert(owner->live == 2 && sid_table.cache_free_slots == 1);
    sid_observed("bounded-detach-revalidates-under-original-sid_table-lock-and-queues-after-unlink");
    sidtab_destroy_entry(&entries[2]); entries[2].cache = NULL;
    assert(owner->live == 1 && !pending_count && contexts_destroyed == 1);
    assert(!lsf_factory_sidcache_current(parent.context, ticket, anchor, &address));
    sid_observed("original-policy-destroy-returns-published-birth-before-sid_table-address-reuse");
    sid_reset(); memset(entries, 0, sizeof(entries)); owner = &factory.pool.contexts[0];
    sidtab_sid2str_put(&sid_table, &entries[0], "a:b:c", 6);
    assert(sid_normal_allocated == 1 && owner->live == 1);
    sidtab_destroy_entry(&entries[0]); entries[0].cache = NULL;
    assert(sid_normal_freed == 1);
    sid_observed("ordinary-cache-allocation-and-final-free-retain-original-allocator");
    sid_reset(); memset(entries, 0, sizeof(entries)); owner = &factory.pool.contexts[0];
    assert(lsf_prepaid_sid2str_put(&sid_table, &entries[0], "a:b:c", 6, &parent) == 0);
    sidtab_sid2str_put(&sid_table, &entries[1], "d:e:f", 6);
    sidtab_sid2str_put(&sid_table, &entries[2], "g:h:i", 6);
    assert(!entries[0].cache && pending_count == 1 && owner->live == 2);
    callbacks(); assert(owner->live == 1 && !sid_normal_freed);
    sid_observed("normal-producer-evicts-private-victim-without-freeing-arena-on-heap");
    sid_reset(); memset(entries, 0, sizeof(entries)); owner = &factory.pool.contexts[0];
    owner->cursor = LSF_TCP_BYTES;
    assert(lsf_prepaid_sid2str_put(&sid_table, &entries[0], "a:b:c", 6, &parent) == -ENOMEM);
    assert(!entries[0].cache && owner->live == 1 && !sid_normal_allocated);
    sid_observed("original-96k-cap-refuses-before-publication-without-heap-fallback");
    sid_reset(); owner = &factory.pool.contexts[0];
    memset(&race_entry, 0, sizeof(race_entry));
    assert(lsf_prepaid_sid2str_put(&sid_table, &race_entry, "a:b:c", 6, &parent) == 0);
    assert(lsf_factory_blob_lookup(race_entry.cache, LSF_PREPAID_SIDCACHE, &birth) == 1);
    assert(lsf_factory_sidcache_candidate(parent.context, birth.ticket.slot, &ticket, &anchor) == 1);
    before_sid_lock = destroy_snapshot_race;
    lsf_prepaid_sidcache_detach(&sid_table, parent.context, ticket);
    assert(owner->live == 1 && !pending_count);
    sid_observed("policy-destroy-between-snapshot-and-cache-lock-prevents-stale-dereference");
    sid_reset(); assert(lsf_factory_sidcache_destroy(backing+1) == -1);
    assert(factory.pool.poisoned && !sid_normal_freed);
    sid_observed("unknown-arena-address-poisons-and-retains-without-normal-free");
    assert(LSF_ALLOCATION_SLOTS == 256 && LSF_OWNER_SLOTS == 64);
    assert(sizeof(factory) + LSF_BACKING_BYTES < LSF_BOOTSTRAP_CEILING);
    sid_observed("original-fixed-record-and-bootstrap-bounds-remain");
    return 0;
}
#endif
