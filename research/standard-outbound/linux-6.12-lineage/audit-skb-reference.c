/* SPDX-License-Identifier: GPL-2.0-only */
/* Supplemental serialized SKB layout/header/atomic/allocator doubles. Selected
 * factory, clone and return bodies remain actual maintained source. This is
 * not Linux geometry, concurrent atomic behavior or physical-free proof. */
#include "reference-io.h"
#undef main
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
typedef unsigned int gfp_t;
typedef struct { int count; } atomic_t;
#define atomic_inc(value) (++(value)->count)
#define atomic_set(value, n) ((value)->count = (n))
#define refcount_set(value, n) ((value)->count = (n))
#define refcount_read(value) ((value)->count)
#define refcount_dec_and_test(value) (!--(value)->count)
#define BUG_ON(value) assert(!(value))
#define WARN_ON_ONCE(value) (value)
#define SKB_FCLONE_UNAVAILABLE 0
#define SKB_FCLONE_ORIG 1
#define SKB_FCLONE_CLONE 2
#define __GFP_MEMALLOC 1u
#define NUMA_NO_NODE (-1)
#define NET_SKBUFF_DATA_USES_OFFSET 1
#define SKB_GSO_FRAGLIST 1u
struct sk_buff {
    struct sk_buff *next, *prev;
    void *sk;
    void (*destructor)(struct sk_buff *);
    unsigned int fclone, len, data_len, mac_len, hdr_len, nohdr, cloned, peeked;
    unsigned int pfmemalloc, pp_recycle, head_frag;
    atomic_t users;
    unsigned int tail, end;
    u8 *head, *data;
    unsigned int truesize, metadata, offsets;
};
struct sk_buff_fclones { struct sk_buff skb1, skb2; atomic_t fclone_ref; };
struct skb_shared_info {
    atomic_t dataref;
    unsigned int nr_frags, gso_type;
    struct sk_buff *frag_list;
    unsigned int frags[2];
};
#define SKB_ALIGN(n) (((n) + 63u) & ~63u)
#define SMP_CACHE_BYTES 64u
#define SKB_DATA_ALIGN(n) SKB_ALIGN(n)
#define SKB_HEAD_ALIGN(n) (SKB_ALIGN(n) + SKB_ALIGN(sizeof(struct skb_shared_info)))
#define SKB_WITH_OVERHEAD(n) ((n) - SKB_ALIGN(sizeof(struct skb_shared_info)))
static struct { unsigned int skbuff_cache, skbuff_fclone_cache; } net_hotdata;
static _Alignas(64) unsigned char heap[8][4096];
static unsigned int heap_count, heap_returns;
#define KFREE_SKB_BULK_SIZE 16u
#define NAPI_SKB_CACHE_SIZE 8u
#define NAPI_SKB_CACHE_HALF 4u
enum skb_drop_reason { reason_consumed };
struct skb_free_array { unsigned int skb_count; void *skb_array[KFREE_SKB_BULK_SIZE]; };
static struct { unsigned int bh_lock; } napi_alloc_cache;
struct napi_alloc_cache { unsigned int skb_count; void *skb_cache[NAPI_SKB_CACHE_SIZE]; };
static struct napi_alloc_cache napi_reference_cache;
#define this_cpu_ptr(value) ((void)(value), &napi_reference_cache)
#define local_lock_nested_bh(value) ((void)(value))
#define local_unlock_nested_bh(value) ((void)(value))
static void retire_skb(struct sk_buff *);
static void __kfree_skb(struct sk_buff *skb) { retire_skb(skb); }
static void skb_release_all(struct sk_buff *, enum skb_drop_reason);
static void skb_release_head_state(struct sk_buff *skb) { (void)skb; }
static bool kasan_mempool_poison_object(struct sk_buff *skb)
{ assert((u8 *)skb < backing || (u8 *)skb >= backing + sizeof(backing)); return true; }
static void kasan_mempool_unpoison_object(struct sk_buff *skb, unsigned int size)
{ (void)skb; (void)size; }
static unsigned int kmem_cache_size(unsigned int cache) { (void)cache; return sizeof(struct sk_buff); }
static void *kmem_cache_alloc(unsigned int cache, gfp_t flags)
{
    (void)cache; (void)flags; assert(heap_count < 8); return heap[heap_count++];
}
static void kmem_cache_free(unsigned int cache, void *pointer)
{
    (void)cache; bool found = false;
    for (unsigned int i = 0; i < heap_count; ++i) if (pointer == heap[i]) found = true;
    assert(found); heap_returns++;
}
static void kmem_cache_free_bulk(unsigned int cache, unsigned int count, void **items)
{ for (unsigned int i = 0; i < count; ++i) kmem_cache_free(cache, items[i]); }
static void kfree(void *pointer)
{
    assert((unsigned char *)pointer < backing || (unsigned char *)pointer >= backing + sizeof(backing));
    heap_returns++;
}
static void sock_edemux(struct sk_buff *skb) { (void)skb; }
static struct skb_shared_info *skb_shinfo(const struct sk_buff *skb)
{ return (void *)(skb->head + skb->end); }
static unsigned int skb_end_offset(const struct sk_buff *skb) { return skb->end; }
static u8 *skb_tail_pointer(const struct sk_buff *skb) { return skb->head + skb->tail; }
static unsigned int skb_headroom(const struct sk_buff *skb) { return (unsigned int)(skb->data - skb->head); }
static bool skb_zcopy(const struct sk_buff *skb) { (void)skb; return false; }
static bool skb_shared(const struct sk_buff *skb) { return skb->users.count > 1; }
static bool skb_cloned(const struct sk_buff *skb) { return skb->cloned && skb_shinfo(skb)->dataref.count != 1; }
static bool skb_pfmemalloc(const struct sk_buff *skb) { return skb->pfmemalloc != 0; }
static bool skb_frags_readable(const struct sk_buff *skb) { (void)skb; return true; }
static int skb_alloc_rx_flag(const struct sk_buff *skb) { (void)skb; return 0; }
static int skb_orphan_frags(struct sk_buff *skb, gfp_t flags) { (void)skb; (void)flags; return 0; }
static void __copy_skb_header(struct sk_buff *out, const struct sk_buff *in)
{ out->metadata = in->metadata; out->offsets = in->offsets; }
static void skb_copy_header(struct sk_buff *out, const struct sk_buff *in) { __copy_skb_header(out, in); }
static void skb_headers_offset_update(struct sk_buff *skb, int nhead) { skb->offsets += nhead; }
static void skb_metadata_clear(struct sk_buff *skb) { skb->metadata = 0; }
static void skb_set_end_offset(struct sk_buff *skb, unsigned int size) { skb->end = size; }
static void skb_reserve(struct sk_buff *skb, int bytes) { skb->data += bytes; skb->tail += bytes; }
static void skb_put(struct sk_buff *skb, unsigned int bytes) { assert(skb->tail + bytes <= skb->end); skb->tail += bytes; skb->len += bytes; }
static int skb_copy_bits(const struct sk_buff *skb, int offset, void *out, int bytes)
{ memcpy(out, skb->data + offset, (size_t)bytes); return 0; }
static void __build_skb_around(struct sk_buff *skb, void *data, unsigned int size)
{
    skb->head = skb->data = data; skb->end = SKB_WITH_OVERHEAD(size); skb->tail = 0;
    skb->users.count = 1; skb->truesize = size + sizeof(*skb);
    atomic_set(&skb_shinfo(skb)->dataref, 1);
}
static struct sk_buff *__alloc_skb(unsigned int size, gfp_t mask, int flags, int node)
{
    (void)mask; (void)flags; (void)node;
    struct sk_buff *skb = kmem_cache_alloc(0, 0);
    void *data = kmem_cache_alloc(0, 0);
    assert(SKB_HEAD_ALIGN(size) <= 4096);
    memset(skb, 0, sizeof(*skb)); memset(data, 0, 4096);
    __build_skb_around(skb, data, SKB_HEAD_ALIGN(size)); return skb;
}
static int lsf_prepaid_audit_return(const void *, unsigned int);
static void skb_release_data(struct sk_buff *skb, int reason);
static void skb_free_head(struct sk_buff *skb);
#define SKB_CONSUMED 0
/* The maintained skb_kfree_head has an intentionally unused end_offset.
 * Keep that body unchanged; this lexical exception matches its original
 * kernel warning policy without suppressing warnings in owned helpers. */
#include "audit-skb-derived-reference.h"
/* This is a serialized model of the actual last-dataref condition; it does
 * not claim to execute Linux's atomic implementation or RCU. */
static void skb_free_head(struct sk_buff *skb) { skb_kfree_head(skb->head, skb->end); }
static void skb_release_data(struct sk_buff *skb, int reason)
{
    (void)reason;
    if (!skb->cloned || --skb_shinfo(skb)->dataref.count == 0)
        skb_free_head(skb);
    skb->pp_recycle = 0;
}
static void retire_skb(struct sk_buff *skb)
{ skb_release_data(skb, SKB_CONSUMED); kfree_skbmem(skb); }
static void skb_release_all(struct sk_buff *skb, enum skb_drop_reason reason)
{ skb_release_data(skb, (int)reason); }
static void audit_reset(void) { reset(); heap_count = heap_returns = 0; }
static void audit_observed(const char *label)
{ lsf_ref_write("AUDIT_SKB_CONTROL ", 18); lsf_ref_write(label, lsf_ref_length(label)); lsf_ref_write(" PASS\n", 6); }

int main(void)
{
    struct sk_buff *skb, *copy;
    struct lsf_prepaid_context *owner;
    struct lsf_factory_blob birth;
    (void)netport_reference_main;
    (void)skb_copy; (void)retire_skb; (void)lsf_prepaid_audit_expand;
    (void)audit_observed; (void)birth; (void)lsf_prepaid_audit_clone;
    (void)kfree_skb_add_bulk; (void)napi_skb_cache_put; (void)kfree_skb_partial;
    assert(netport_reference_main() == 0);
    audit_reset(); owner = &factory.pool.contexts[0];
    skb = lsf_prepaid_audit_skb_new(parent, 1024);
    assert(skb && owner->live == 3 && !heap_count);
#ifdef LSF_OLD_AUDIT_SKB
    copy = skb_clone(skb, GFP_ATOMIC);
    assert(copy && owner->live == 3 && heap_count == 1);
    puts("AUDIT_SKB_OLD clone-header-escapes-original-owner RED");
    return 2;
#else
    audit_observed("header-and-head-prepaid-before-publication");
    copy = skb_clone(skb, GFP_ATOMIC);
    assert(copy && owner->live == 4 && !heap_count && skb_shinfo(skb)->dataref.count == 2);
    audit_observed("actual-clone-inherits-birth-and-real-dataref");
    owner->closed = 1; factory.pool.stopped = 1;
    assert(lsf_prepaid_return(&factory.pool, parent.context->key, parent.ticket));
    retire_skb(skb);
    assert(owner->live == 2 && skb_shinfo(copy)->dataref.count == 1);
    assert(!lsf_prepaid_recycle(&factory.pool, parent.context->key));
    audit_observed("original-header-final-free-keeps-cloned-head-owned");
    retire_skb(copy); assert(owner->live == 0);
    assert(lsf_prepaid_recycle(&factory.pool, parent.context->key));
    assert(factory.pool.records[0].phase == LSF_PREPAID_LIVE && !heap_returns);
    audit_observed("last-dataref-and-header-return-before-recycle-without-backing-refund");

    audit_reset(); owner = &factory.pool.contexts[0];
    skb = lsf_prepaid_audit_skb_new(parent, 1024); assert(skb);
    owner->closed = 1; factory.pool.stopped = 1;
    assert(lsf_prepaid_return(&factory.pool, parent.context->key, parent.ticket));
    copy = skb_clone(skb, GFP_ATOMIC); assert(copy && owner->live == 3);
    retire_skb(skb); retire_skb(copy); assert(owner->live == 0);
    audit_observed("queued-audit-child-can-clone-after-root-close-without-new-root");

    audit_reset(); owner = &factory.pool.contexts[0];
    skb = lsf_prepaid_audit_skb_new(parent, 1024); assert(skb);
    skb_put(skb, 3); memcpy(skb->data, "abc", 3);
    copy = skb_copy(skb, GFP_ATOMIC);
    assert(copy && copy->head != skb->head && owner->live == 5 && !heap_count);
    assert(copy->len == 3 && copy->data[0] == 'a' && copy->data[2] == 'c');
    retire_skb(copy); retire_skb(skb); assert(owner->live == 1);
    audit_observed("actual-multicast-copy-retains-new-header-and-head");

    audit_reset(); owner = &factory.pool.contexts[0];
    skb = lsf_prepaid_audit_skb_new(parent, 1024); assert(skb);
    skb_put(skb, 4); memcpy(skb->data, "data", 4);
    copy = skb_clone(skb, GFP_ATOMIC); assert(copy);
    assert(lsf_factory_blob_lookup(skb, LSF_PREPAID_AUDIT_SKB, &birth) == 1);
    void *old = copy->head;
    assert(lsf_prepaid_audit_expand(skb, 64, 1024, birth) == 0);
    assert(skb->head != old && copy->head == old && copy->data[0] == 'd');
    assert(skb->data[0] == 'd' && skb->data[3] == 'a' && owner->live == 5);
    assert(skb->cloned == 0 && skb_shinfo(skb)->dataref.count == 1);
    retire_skb(copy); assert(owner->live == 3);
    retire_skb(skb); assert(owner->live == 1);
    audit_observed("expansion-preserves-cloned-old-head-until-its-last-reader");

    audit_reset(); owner = &factory.pool.contexts[0];
    owner->cursor = LSF_TCP_BYTES - 64;
    assert(!lsf_prepaid_audit_skb_new(parent, 1024) && owner->live == 1 && !heap_count);
    audit_observed("header-quota-refusal-never-allocates-head-or-heap");
    audit_reset(); owner = &factory.pool.contexts[0];
    owner->cursor = LSF_TCP_BYTES - SKB_ALIGN(sizeof(struct sk_buff));
    assert(!lsf_prepaid_audit_skb_new(parent, 1024) && owner->live == 1 && !heap_count);
    audit_observed("head-quota-failure-returns-unpublished-header");

    audit_reset(); owner = &factory.pool.contexts[0];
    skb = lsf_prepaid_audit_skb_new(parent, 1024); assert(skb);
    assert(lsf_factory_blob_lookup(skb, LSF_PREPAID_AUDIT_SKB, &birth) == 1);
    old = skb->head; owner->cursor = LSF_TCP_BYTES;
    assert(lsf_prepaid_audit_expand(skb, 0, 1024, birth) == -ENOMEM);
    assert(skb->head == old && owner->live == 3 && !heap_count);
    audit_observed("expansion-quota-failure-preserves-original-owned-buffer");

    audit_reset(); owner = &factory.pool.contexts[0];
    skb = lsf_prepaid_audit_skb_new(parent, 1024); assert(skb);
    skb_shinfo(skb)->nr_frags = 1;
    assert(!skb_clone(skb, GFP_ATOMIC) && owner->poisoned && owner->live == 3 && !heap_count);
    audit_observed("unexpected-fragment-shape-poisons-without-fallback");
    audit_reset(); owner = &factory.pool.contexts[0];
    skb = lsf_prepaid_audit_skb_new(parent, 1024); assert(skb);
    skb_shinfo(skb)->nr_frags = 1;
    assert(!skb_copy(skb, GFP_ATOMIC) && owner->poisoned && owner->live == 3 && !heap_count);
    audit_observed("private-copy-refuses-unclosed-fragments-before-new-allocation");
    audit_reset(); owner = &factory.pool.contexts[0];
    skb = lsf_prepaid_audit_skb_new(parent, 1024); assert(skb);
    skb->head = kmem_cache_alloc(0, 0); memset(skb->head, 0, 4096);
    assert(!skb_clone(skb, GFP_ATOMIC) && owner->poisoned && owner->live == 3 && heap_count == 1);
    audit_observed("private-header-cannot-adopt-a-normal-heap-head");
    audit_reset(); owner = &factory.pool.contexts[0];
    skb = lsf_prepaid_audit_skb_new(parent, 1024); assert(skb);
    skb->end = LSF_TCP_BYTES;
    assert(!skb_clone(skb, GFP_ATOMIC) && owner->poisoned && owner->live == 3 && !heap_count);
    audit_observed("shared-info-span-checked-against-original-head-before-dereference");
    audit_reset(); owner = &factory.pool.contexts[0];
    skb = lsf_prepaid_audit_skb_new(parent, 1024); assert(skb);
    skb->end++;
    assert(!skb_clone(skb, GFP_ATOMIC) && owner->poisoned && owner->live == 3 && !heap_count);
    audit_observed("misaligned-shared-info-refused-before-dereference");
    audit_reset(); owner = &factory.pool.contexts[0];
    skb_kfree_head(backing + 1, 0);
    assert(factory.pool.poisoned && owner->live == 1 && !heap_returns);
    audit_observed("unknown-arena-head-never-reaches-normal-free");
    audit_reset(); owner = &factory.pool.contexts[0];
    assert(lsf_prepaid_return(&factory.pool, parent.context->key, parent.ticket));
    assert(!lsf_prepaid_audit_skb_new(parent, 1024) && owner->live == 0 && !heap_count);
    audit_observed("retired-parent-cannot-create-audit-buffer");

    audit_reset(); owner = &factory.pool.contexts[0];
    skb = lsf_prepaid_audit_skb_new(parent, 1024); assert(skb);
    struct skb_free_array batch = {0};
    kfree_skb_add_bulk(skb, &batch, reason_consumed);
    assert(batch.skb_count == 0 && owner->live == 1 && !heap_returns);
    audit_observed("actual-bulk-final-free-never-inserts-private-header-in-slab-array");
    audit_reset(); owner = &factory.pool.contexts[0];
    skb = lsf_prepaid_audit_skb_new(parent, 1024); assert(skb);
    skb_release_data(skb, SKB_CONSUMED); napi_reference_cache.skb_count = 0;
    napi_skb_cache_put(skb);
    assert(napi_reference_cache.skb_count == 0 && owner->live == 1 && !heap_returns);
    audit_observed("actual-napi-final-free-routes-before-normal-cache-poisoning");
    audit_reset(); owner = &factory.pool.contexts[0];
    skb = lsf_prepaid_audit_skb_new(parent, 1024); assert(skb);
    void *transferred_head = skb->head;
    kfree_skb_partial(skb, true);
    assert(owner->live == 2 && !heap_returns);
    skb_kfree_head(transferred_head, 1024);
    assert(owner->live == 1 && !heap_returns);
    audit_observed("actual-stolen-head-final-free-retains-head-independently");
    audit_reset(); owner = &factory.pool.contexts[0];
    skb = __alloc_skb(1024, GFP_ATOMIC, 0, NUMA_NO_NODE);
    copy = skb_clone(skb, GFP_ATOMIC);
    assert(copy && heap_count == 3 && owner->live == 1);
    retire_skb(skb); retire_skb(copy);
    assert(heap_returns == 3 && owner->live == 1 && !factory.pool.poisoned);
    audit_observed("ordinary-outside-arena-clone-and-free-preserve-original-allocator");
    (void)audit_observed;
    return 0;
#endif
}
