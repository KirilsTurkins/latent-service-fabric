/* SPDX-License-Identifier: GPL-2.0-only */
/* Exact derived functions with explicit protocol doubles, not Linux execution. */
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
#include <stddef.h>
#include <stdint.h>
#include "lineage.h"

struct module { int marker; };
struct kmem_cache { int marker; };
struct twsk_proto { struct kmem_cache *twsk_slab; };
struct proto { struct module *owner; struct kmem_cache *slab; struct twsk_proto *twsk_prot; };
struct sock { int sk_cgrp_data; lsf_u64 sk_cookie; };
struct inet_timewait_sock { struct proto *tw_prot; lsf_u64 tw_cookie; };
struct sk_buff { unsigned char *head; int head_frag, end_offset, fclone; };
struct sk_buff_fclones { struct sk_buff skb1, skb2; int fclone_ref; };
static struct { struct kmem_cache *skb_small_head_cache, *skbuff_cache, *skbuff_fclone_cache; } net_hotdata;
#define SKB_SMALL_HEAD_HEADROOM 7u
#define SKB_FCLONE_UNAVAILABLE 0
#define SKB_FCLONE_ORIG 1
#define SKB_FCLONE_CLONE 2
#define container_of(ptr, type, member) ((type *)((char *)(ptr) - offsetof(type, member)))

static struct lsf_lineage state;
static struct lsf_key key;
static struct module module;
static struct kmem_cache cache;
static void *expected_address;
static size_t expected_size;
static unsigned int freed, modules, recycle;
static lsf_u64 atomic64_read(const lsf_u64 *value) { return *value; }
static void cgroup_sk_free(int *value) { (void)value; }
static void mem_cgroup_sk_free(struct sock *value) { (void)value; }
static void security_sk_free(struct sock *value) { (void)value; }
static void twsk_destructor(struct sock *value) { (void)value; }
static void module_put(struct module *value) { assert(value == &module); modules++; }

static void allocator_return(void *address)
{
    assert(address == expected_address && !freed);
    /* Destroy the model object before the post-free callback. Any late cookie
     * or owner read would now observe the wrong value. No real kernel is used. */
    memset(address, 0, expected_size);
    freed++;
}
static void kmem_cache_free(struct kmem_cache *selected, void *address)
{
    assert(selected == &cache);
    allocator_return(address);
}
static void kfree(void *address) { allocator_return(address); }
static int refcount_read(const int *value) { return *value; }
static int refcount_dec_and_test(int *value) { assert(*value > 0); return --*value == 0; }
static int skb_pp_recycle(struct sk_buff *skb, void *head) { (void)skb; (void)head; return recycle; }
static void skb_free_frag(void *head) { (void)head; }
static unsigned int skb_end_offset(struct sk_buff *skb) { return (unsigned int)skb->end_offset; }

static struct lsf_token lsf_stream_before_free(unsigned int kind, const void *address,
                                               lsf_u64 cookie)
{
    assert(!freed);
    return lsf_capture_free(&state, kind, (lsf_u64)(uintptr_t)address, cookie);
}
static void lsf_stream_after_free(struct lsf_token token)
{
    assert(freed == 1);
    assert(lsf_post_free(&state, token));
}
static void lsf_stream_unproved_fragment(const void *head)
{
    lsf_unproved_allocation(&state, (lsf_u64)(uintptr_t)head);
}

/* Generated from authenticated upstream or derived function preimages. */
#include "selected-functions.h"

static void fresh(void *address, size_t bytes, unsigned int kind, lsf_u64 cookie)
{
    struct lsf_scope scope = {{1, 2, 3, 4, 5, 6, 7, 8}};
    struct lsf_token token;
    memset(&state, 0, sizeof(state));
    state.next_owner = state.next_allocation = 1;
    assert(lsf_owner_admit(&state, scope, LSF_TCP_BYTES, &key));
    assert(lsf_birth_prepare(&state, key, lsf_empty_token(), kind, bytes, &token));
    assert(lsf_birth_commit(&state, &token, (lsf_u64)(uintptr_t)address, cookie));
    assert(lsf_begin_drain(&state, key));
    expected_address = address;
    expected_size = bytes;
    freed = modules = recycle = 0;
}

static void complete(const char *name)
{
    assert(freed == 1 && lsf_mechanism_drained(&state, key));
    printf("HOOK_CONTROL %s PASS\n", name);
}

int main(void)
{
    struct proto protocol = {&module, &cache, 0};
    struct twsk_proto timewait_protocol = {&cache};
    struct sock socket;
    struct inet_timewait_sock timewait;
    struct sk_buff skb;
    struct sk_buff_fclones pair;
    unsigned char head[32];

    /* Original functions lack these callbacks; keep the comparison harness
     * byte-identical while still compiling with unused-function diagnostics. */
    (void)lsf_stream_before_free;
    (void)lsf_stream_after_free;
    (void)lsf_stream_unproved_fragment;
    (void)atomic64_read;

    net_hotdata.skb_small_head_cache = net_hotdata.skbuff_cache = &cache;
    net_hotdata.skbuff_fclone_cache = &cache;
    socket.sk_cookie = 42;
    fresh(&socket, sizeof(socket), LSF_SOCKET, 42);
    sk_prot_free(&protocol, &socket);
    if (!lsf_mechanism_drained(&state, key)) {
        fputs("HOOK_OLD_NO_POST_FREE\n", stderr);
        return 2;
    }
    assert(modules == 1);
    complete("socket-slab-post-free-copy");

    protocol.slab = 0;
    socket.sk_cookie = 43;
    fresh(&socket, sizeof(socket), LSF_SOCKET, 43);
    sk_prot_free(&protocol, &socket);
    assert(modules == 1);
    complete("socket-heap-post-free-copy");

    protocol.twsk_prot = &timewait_protocol;
    timewait.tw_prot = &protocol;
    timewait.tw_cookie = 44;
    fresh(&timewait, sizeof(timewait), LSF_TIMEWAIT, 44);
    inet_twsk_free(&timewait);
    assert(modules == 1);
    complete("timewait-distinct-post-free-copy");

    skb.fclone = SKB_FCLONE_UNAVAILABLE;
    fresh(&skb, sizeof(skb), LSF_SKB_HEADER, 0);
    kfree_skbmem(&skb);
    complete("skb-header-post-free");

    pair.skb1.fclone = SKB_FCLONE_ORIG;
    pair.fclone_ref = 1;
    fresh(&pair, sizeof(pair), LSF_SKB_CLONE, 0);
    kfree_skbmem(&pair.skb1);
    complete("skb-fclone-fastpath-post-free");

    pair.skb1.fclone = SKB_FCLONE_ORIG;
    pair.skb2.fclone = SKB_FCLONE_CLONE;
    pair.fclone_ref = 2;
    fresh(&pair, sizeof(pair), LSF_SKB_CLONE, 0);
    kfree_skbmem(&pair.skb1);
    assert(!freed && !lsf_mechanism_drained(&state, key));
    kfree_skbmem(&pair.skb2);
    complete("shared-fclone-retained-until-last-reference");

    fresh(head, sizeof(head), LSF_SKB_HEAD, 0);
    skb_kfree_head(head, SKB_SMALL_HEAD_HEADROOM);
    complete("small-heap-head-post-free");

    fresh(head, sizeof(head), LSF_SKB_HEAD, 0);
    skb_kfree_head(head, SKB_SMALL_HEAD_HEADROOM + 1);
    complete("ordinary-heap-head-post-free");

    for (recycle = 0; recycle < 2;) {
        unsigned int selected = recycle;
        fresh(head, sizeof(head), LSF_SKB_HEAD, 0);
        recycle = selected;
        skb.head = head;
        skb.head_frag = 1;
        skb_free_head(&skb);
        assert(!freed && !lsf_mechanism_drained(&state, key));
        assert(state.owners[key.slot].poisoned);
        printf("HOOK_CONTROL %s PASS\n", recycle ? "page-pool-is-not-free" : "fragment-return-is-not-free");
        recycle++;
    }
    puts("HOOK_SUMMARY 10 PASS; linux-executed=false; final-free-certified=false");
    return 0;
}
