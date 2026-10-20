/* SPDX-License-Identifier: GPL-2.0-only */
/* Exact original/derived constructors, explicit protocol doubles only. */
#ifdef LSF_FREESTANDING_REFERENCE
#include "reference-io.h"
#else
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <assert.h>
#include <stdio.h>
#include <string.h>
#endif
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "admission.h"

typedef unsigned int gfp_t;
typedef unsigned char u8;
struct kmem_cache { unsigned int marker; };
struct module { unsigned int marker; };
struct twsk_proto { struct kmem_cache *twsk_slab; };
struct proto {
    struct kmem_cache *slab;
    unsigned int obj_size;
    struct module *owner;
    struct twsk_proto *twsk_prot;
};
struct inet_sock { int inet_daddr, inet_rcv_saddr, tos, inet_num, inet_sport, inet_dport; };
struct sock {
    struct proto *sk_prot_creator;
    lsf_u64 sk_cookie;
    int sk_bound_dev_if, sk_family, sk_reuse, sk_reuseport, sk_hash;
};
struct inet_timewait_death_row { int tw_refcount, sysctl_max_tw_buckets; };
struct inet_timewait_sock {
    struct inet_timewait_death_row *tw_dr;
    struct proto *tw_prot;
    lsf_u64 tw_cookie;
    int tw_daddr, tw_rcv_saddr, tw_bound_dev_if, tw_tos, tw_num, tw_state,
        tw_substate, tw_sport, tw_dport, tw_family, tw_reuse, tw_reuseport,
        tw_hash, tw_ipv6only, tw_transparent, tw_timer, tw_refcnt;
};
struct sk_buff { unsigned char *head; unsigned int tail; bool pfmemalloc; int fclone; };
struct sk_buff_fclones { struct sk_buff skb1, skb2; int fclone_ref; };
static struct { struct kmem_cache *skbuff_cache, *skbuff_fclone_cache; } net_hotdata;
#define __GFP_ZERO 1u
#define __GFP_MEMALLOC 2u
#define GFP_DMA 4u
#define GFP_ATOMIC 8u
#define SKB_ALLOC_FCLONE 1u
#define SKB_ALLOC_NAPI 2u
#define SKB_ALLOC_RX 4u
#define NUMA_NO_NODE (-1)
#define TCP_TIME_WAIT 6
#define SKB_FCLONE_ORIG 1
#define SKB_WITH_OVERHEAD(size) ((size) - 16)
#define likely(value) (value)
#define unlikely(value) (value)
#define READ_ONCE(value) (value)
#define EXPORT_SYMBOL(value)
#define container_of(ptr, type, member) ((type *)((char *)(ptr) - offsetof(type, member)))

static struct lsf_lineage state;
static struct lsf_admission admission;
static struct lsf_key key;
static struct lsf_token parent;
static struct lsf_scope scope = {{1, 2, 3, 4, 5, 6, 7, 8}};
static struct sock socket_model;
static struct inet_sock inet_model;
static struct inet_timewait_sock timewait_model;
static struct sk_buff_fclones skb_model;
static unsigned char data_model[128];
static struct module module_model;
static struct kmem_cache cache_model;
static unsigned int allocators, frees, calls, committed, prepared, context,
                    failed_allocator, security_failure, module_failure, modules;
static struct lsf_bundle *active;
static struct lsf_bundle last_bundle;

static void *allocate(void *address)
{
    ++allocators;
    if (prepared) {
        /* Both SKB charges/slots must already exist even at the FIRST call. */
        assert(active && state.owners[key.slot].allocations >= active->count);
        assert(state.owners[key.slot].live_bytes >=
               (active->count == 2 ? 8704u : 512u));
    }
    return failed_allocator == allocators ? 0 : address;
}
static void *kmem_cache_alloc(struct kmem_cache *cache, gfp_t flags)
{
    (void)flags;
    assert(cache == &cache_model);
    return allocate(calls == LSF_CONSTRUCT_TIMEWAIT ? (void *)&timewait_model : (void *)&socket_model);
}
static void *kmalloc(unsigned int bytes, gfp_t flags)
{
    (void)bytes; (void)flags;
    return allocate(&socket_model);
}
static void *kmem_cache_alloc_node(struct kmem_cache *cache, gfp_t flags, int node)
{
    (void)flags; (void)node;
    assert(cache == &cache_model);
    return allocate(&skb_model.skb1);
}
static void *napi_skb_cache_get(void) { return allocate(&skb_model.skb1); }
static void *kmalloc_reserve(unsigned int *size, gfp_t flags, int node, bool *pfmemalloc)
{
    (void)flags; (void)node;
    assert(*size <= sizeof(data_model));
    *size = sizeof(data_model);
    *pfmemalloc = false;
    return allocate(data_model);
}
static void kmem_cache_free(struct kmem_cache *cache, void *address)
{
    assert(cache == &cache_model && address);
    frees++;
}
static void kfree(void *address) { assert(address); frees++; }
static int want_init_on_alloc(gfp_t flags) { return !!(flags & __GFP_ZERO); }
static void sk_prot_clear_nulls(struct sock *sk, unsigned int size) { (void)sk; (void)size; }
static int security_sk_alloc(struct sock *sk, int family, gfp_t flags)
{
    (void)sk; (void)family; (void)flags; return (int)security_failure;
}
static void security_sk_free(struct sock *sk) { (void)sk; }
static int try_module_get(struct module *module) { assert(module == &module_model); return !module_failure; }
static void __module_get(struct module *module) { assert(module == &module_model); modules++; }
static int refcount_read(const int *value) { return *value; }
static void refcount_set(int *value, int count) { *value = count; }
static lsf_u64 atomic64_read(const lsf_u64 *value) { return *value; }
static void atomic64_set(lsf_u64 *value, lsf_u64 count) { *value = count; }
static const struct inet_sock *inet_sk(const struct sock *sk) { (void)sk; return &inet_model; }
static int inet_test_bit(int bit, const struct sock *sk) { (void)bit; (void)sk; return 0; }
#define TRANSPARENT 1
static int sock_net(const struct sock *sk) { (void)sk; return 1; }
static void twsk_net_set(struct inet_timewait_sock *tw, int net) { (void)tw; (void)net; }
static void tw_timer_handler(void) {}
static void timer_setup(int *timer, void (*handler)(void), int flags)
{
    (void)timer; (void)handler; (void)flags;
}
static int sk_memalloc_socks(void) { return 0; }
static int numa_mem_id(void) { return 0; }
static void prefetchw(const void *address) { (void)address; }
static void __build_skb_around(struct sk_buff *skb, unsigned char *data, unsigned int size)
{
    (void)size; skb->head = data;
}

/* These costs/context are EXPLICIT C DOUBLE INPUTS, never a kernel layout or
 * authenticated grant. The real candidate prepare() always refuses unknown. */
static int lsf_stream_constructor_prepare(unsigned int constructor, const void *subject,
                                           unsigned int size, unsigned int allocation_flags,
                                           unsigned int path_flags, int node,
                                           struct lsf_bundle *bundle)
{
    struct lsf_allocation_cost costs[2] = {{LSF_SOCKET, 512}, {LSF_SKB_HEAD, 8192}};
    unsigned int count = 1;
    (void)subject; (void)size; (void)allocation_flags; (void)path_flags; (void)node;
    calls = constructor;
    if (!context)
        return 0;
    if (constructor == LSF_CONSTRUCT_TIMEWAIT)
        costs[0].kind = LSF_TIMEWAIT;
    else if (constructor == LSF_CONSTRUCT_SKB || constructor == LSF_CONSTRUCT_FCLONE) {
        costs[0].kind = constructor == LSF_CONSTRUCT_SKB ? LSF_SKB_HEADER : LSF_SKB_CLONE;
        count = 2;
    }
    if (!lsf_bundle_prepare(&state, admission, parent, constructor, costs, count, bundle))
        return 0;
    prepared = 1;
    active = bundle;
    return 1;
}
static void lsf_stream_constructor_observed(struct lsf_bundle *bundle, unsigned int index,
                                             const void *address, lsf_u64 cookie)
{
    if (lsf_bundle_commit(&state, bundle, index, (lsf_u64)(uintptr_t)address, cookie))
        committed++;
    last_bundle = *bundle;
}
static void lsf_stream_constructor_uncertain(struct lsf_bundle *bundle)
{
    lsf_bundle_uncertain(&state, bundle);
}
#include "selected-constructors.h"

static void fresh(void)
{
    memset(&state, 0, sizeof(state));
    memset(&socket_model, 0, sizeof(socket_model));
    memset(&timewait_model, 0, sizeof(timewait_model));
    memset(&skb_model, 0, sizeof(skb_model));
    state.next_owner = state.next_allocation = 1;
    assert(lsf_owner_admit(&state, scope, LSF_TCP_BYTES, &key));
    assert(lsf_admission_capture(&state, key, scope, &admission));
    parent = lsf_empty_token();
    allocators = frees = calls = committed = prepared = 0;
    failed_allocator = security_failure = module_failure = modules = 0;
    active = 0; context = 1;
}
static void pass(const char *name) { puts(name); }

int main(void)
{
    struct twsk_proto tw_protocol = {&cache_model};
    struct proto protocol = {&cache_model, sizeof(socket_model), &module_model, &tw_protocol};
    struct inet_timewait_death_row dr = {1, 8};
    unsigned int which;
    /* Keep identical source warning-clean when original constructors have no hooks. */
    (void)lsf_stream_constructor_prepare;
    (void)lsf_stream_constructor_observed;
    (void)lsf_stream_constructor_uncertain;
    net_hotdata.skbuff_cache = net_hotdata.skbuff_fclone_cache = &cache_model;

    fresh(); context = 0;
    if (sk_prot_alloc(&protocol, 0, 2) || allocators) {
        fputs("CONSTRUCTOR_OLD_ALLOCATES_WITHOUT_ADMISSION\n", stderr);
        return 2;
    }
    assert(!state.owners[key.slot].live_bytes);
    pass("CONSTRUCTOR_CONTROL socket-unknown-refuses-before-allocator PASS");

    fresh(); context = 0;
    socket_model.sk_prot_creator = &protocol;
    assert(!inet_twsk_alloc(&socket_model, &dr, 1) && !allocators);
    pass("CONSTRUCTOR_CONTROL timewait-unknown-refuses-before-allocator PASS");

    fresh(); context = 0;
    assert(!__alloc_skb(64, 0, 0, NUMA_NO_NODE) && !allocators);
    pass("CONSTRUCTOR_CONTROL skb-unknown-refuses-before-either-allocator PASS");

    for (which = 0; which < 3; ++which) {
        fresh();
        security_failure = which == 0;
        module_failure = which == 1;
        failed_allocator = which == 2 ? 1 : 0;
        assert(!sk_prot_alloc(&protocol, 0, 2));
        assert(allocators == 1 && frees == (which == 2 ? 0u : 1u));
        assert(state.owners[key.slot].poisoned && state.owners[key.slot].live_bytes == 512);
    }
    pass("CONSTRUCTOR_CONTROL socket-failure-branches-preserve-original-cleanup PASS");

    fresh(); protocol.slab = 0;
    assert(sk_prot_alloc(&protocol, 0, 2) == &socket_model && allocators == 1);
    assert(state.poisoned && !committed && state.owners[key.slot].live_bytes == 512);
    protocol.slab = &cache_model;
    pass("CONSTRUCTOR_CONTROL preinitialized-socket-cookie-is-not-fabricated PASS");

    fresh(); dr.tw_refcount = 10;
    socket_model.sk_prot_creator = &protocol;
    assert(!inet_twsk_alloc(&socket_model, &dr, 1) && !allocators && !prepared);
    dr.tw_refcount = 1;
    pass("CONSTRUCTOR_CONTROL original-timewait-quota-precedes-new-reservation PASS");

    fresh();
    socket_model.sk_prot_creator = &protocol;
    socket_model.sk_cookie = 42;
    assert(lsf_birth_prepare(&state, key, parent, LSF_SOCKET, 1024, &parent));
    assert(lsf_birth_commit(&state, &parent, (lsf_u64)(uintptr_t)&socket_model, 42));
    assert(lsf_begin_drain(&state, key));
    assert(inet_twsk_alloc(&socket_model, &dr, 1) == &timewait_model);
    assert(allocators == 1 && committed == 1 && modules == 1);
    assert(timewait_model.tw_cookie == 42 && state.owners[key.slot].live_bytes == 1536);
    pass("CONSTRUCTOR_CONTROL timewait-child-in-drain-copies-live-cookie PASS");

    fresh(); failed_allocator = 1;
    assert(!__alloc_skb(64, 0, 0, NUMA_NO_NODE));
    assert(allocators == 1 && !committed && state.owners[key.slot].live_bytes == 8704);
    assert(state.owners[key.slot].poisoned);
    pass("CONSTRUCTOR_CONTROL skb-header-failure-retains-both-reservations PASS");

    fresh(); failed_allocator = 2;
    assert(!__alloc_skb(64, 0, 0, NUMA_NO_NODE));
    assert(allocators == 2 && committed == 1 && frees == 1);
    assert(state.owners[key.slot].poisoned && state.owners[key.slot].live_bytes == 8704);
    pass("CONSTRUCTOR_CONTROL skb-data-failure-preserves-cleanup-and-all-charges PASS");

    for (which = 0; which < 2; ++which) {
        fresh();
        assert(__alloc_skb(64, 0, which ? SKB_ALLOC_FCLONE : 0, NUMA_NO_NODE) == &skb_model.skb1);
        assert(allocators == 2 && committed == 2 && state.owners[key.slot].live_bytes == 8704);
        assert(last_bundle.tokens[0].kind == (which ? LSF_SKB_CLONE : LSF_SKB_HEADER));
        assert(last_bundle.tokens[1].kind == LSF_SKB_HEAD);
    }
    pass("CONSTRUCTOR_CONTROL skb-and-fclone-use-distinct-header-and-data-records PASS");
    puts("CONSTRUCTOR_SUMMARY 10 PASS; linux-executed=false; final-free-certified=false");
    return 0;
}
