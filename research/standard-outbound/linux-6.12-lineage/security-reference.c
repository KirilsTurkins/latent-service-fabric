/* SPDX-License-Identifier: GPL-2.0-only */
/* Supplemental composite-LSM lifetime control. Exact maintained allocation,
 * hook/error and callback bodies run with explicit type/LSM/RCU/cache doubles.
 * No Linux hook implementation, kernel layout, spinlock or final-free runs. */
#include "reference-io.h"
#include <stdbool.h>
#include "prepaid.h"

#define CONFIG_LSF_STREAM_FACTORY 1
#define GFP_KERNEL 1u
#define GFP_NOFS 2u
#define __GFP_ZERO 4u
#define EOPNOTSUPP 95
#define ENOMEM 12
#define unlikely(value) (value)
typedef unsigned int gfp_t;
struct rcu_head { unsigned int marker; };
struct inode { void *i_security; };
struct sock { void *sk_security; };
struct lsf_factory_context { struct lsf_prepaid_key key; };
struct lsf_factory_blob {
    struct lsf_factory_context *context;
    struct lsf_prepaid_ticket ticket;
};
static struct lsf_prepaid pool;
static struct lsf_factory_context context;
static _Alignas(64) unsigned char backing[LSF_BACKING_BYTES], normal[128];
static struct { int lbs_inode, lbs_sock; } blob_sizes = {32, 32};
static unsigned int cache;
static void *lsm_inode_cache = &cache;
static unsigned int normal_allocated, normal_freed, alloc_hooks, free_hooks,
    callback_hooks, hook_fail;
static struct rcu_head *pending;
static void (*callback)(struct rcu_head *);

static void *kmem_cache_zalloc(void *selected, gfp_t gfp)
{
    assert(selected == lsm_inode_cache && gfp == GFP_NOFS);
    normal_allocated++;
    return memset(normal, 0, sizeof(normal));
}
static void kmem_cache_free(void *selected, void *value)
{
    assert(selected == lsm_inode_cache && value == normal);
    normal_freed++;
}
static int lsm_blob_alloc(void **dest, size_t bytes, gfp_t gfp)
{
    assert(bytes <= sizeof(normal) && gfp == (GFP_KERNEL | __GFP_ZERO));
    *dest = bytes ? memset(normal, 0, sizeof(normal)) : NULL;
    normal_allocated += bytes != 0;
    return 0;
}
static void kfree(void *value)
{
    assert(!value || value == normal);
    normal_freed += value != NULL;
}
static void call_rcu(struct rcu_head *head, void (*done)(struct rcu_head *))
{
    assert(!pending);
    pending = head;
    callback = done;
}
static int inode_alloc_hook(struct inode *inode)
{
    assert(inode->i_security);
    alloc_hooks++;
    return hook_fail ? -1 : 0;
}
static int sock_alloc_hook(struct sock *sock, int family, gfp_t priority)
{
    assert(sock->sk_security && family == 2 && priority == (GFP_KERNEL | __GFP_ZERO));
    alloc_hooks++;
    return hook_fail ? -1 : 0;
}
static void inode_free_hook(struct inode *inode)
{
    assert(inode->i_security);
    free_hooks++;
}
static void inode_callback_hook(struct rcu_head *head)
{
    assert(head);
    if ((uintptr_t)head >= (uintptr_t)backing && (uintptr_t)head - (uintptr_t)backing < sizeof(backing))
        assert(pool.contexts[context.key.slot].live == 1 && pool.contexts[context.key.slot].continuations == 1);
    callback_hooks++;
}
static void sock_free_hook(struct sock *sock)
{
    assert(sock->sk_security);
    if ((uintptr_t)sock->sk_security >= (uintptr_t)backing &&
        (uintptr_t)sock->sk_security - (uintptr_t)backing < sizeof(backing))
        assert(pool.contexts[context.key.slot].live == 1);
    free_hooks++;
}
#define call_int_hook(name, ...) reference_int_##name(__VA_ARGS__)
#define reference_int_inode_alloc_security inode_alloc_hook
#define reference_int_sk_alloc_security sock_alloc_hook
#define call_void_hook(name, ...) reference_void_##name(__VA_ARGS__)
#define reference_void_inode_free_security inode_free_hook
#define reference_void_inode_free_security_rcu inode_callback_hook
#define reference_void_sk_free_security sock_free_hook

/* These are explicit serialized factory/allocator doubles. The actual core
 * below is unchanged; real pool_lock/callback installation is NOT executed. */
void *lsf_factory_blob_allocate(struct lsf_factory_context *owner,
                                       unsigned long bytes, unsigned int kind)
{
    struct lsf_prepaid_ticket ticket;
    lsf_u64 offset;
    assert(owner == &context);
    if (!lsf_prepaid_blob_allocate(&pool, owner->key, bytes, kind, &ticket, &offset))
        return NULL;
    return memset(backing + offset, 0, bytes);
}
int lsf_factory_blob_lookup(const void *address, unsigned int kind,
                                   struct lsf_factory_blob *copy)
{
    struct lsf_prepaid_key key;
    uintptr_t base = (uintptr_t)backing, value = (uintptr_t)address;
    if (value < base || value - base >= sizeof(backing))
        return 0;
    if (!lsf_prepaid_blob_find(&pool, value - base, kind, &key, &copy->ticket))
        return -1;
    assert(key.slot == context.key.slot && key.generation == context.key.generation);
    copy->context = &context;
    return 1;
}
int lsf_factory_blob_queue(const void *address)
{
    struct lsf_factory_blob copy;
    int result = lsf_factory_blob_lookup(address, LSF_PREPAID_INODE_BLOB, &copy);
    if (result == 1 && !lsf_prepaid_blob_queue(&pool, copy.context->key, copy.ticket))
        result = -1;
    return result;
}
int lsf_factory_blob_finish(struct lsf_factory_blob copy, unsigned int kind)
{
    return lsf_prepaid_blob_finish(&pool, copy.context->key, copy.ticket, kind);
}
void security_inode_free(struct inode *inode);
void security_sk_free(struct sock *sock);
#include "security-derived-reference.h"

static void reset(void)
{
    struct lsf_scope scope = {{1,2,3,4,5,6,7,8}};
    memset(&pool, 0, sizeof(pool));
    memset(backing, 0, sizeof(backing));
    context = (struct lsf_factory_context){0};
    normal_allocated = normal_freed = alloc_hooks = free_hooks = callback_hooks = hook_fail = 0;
    pending = NULL;
    callback = NULL;
    assert(lsf_prepaid_initialize(&pool));
    assert(lsf_prepaid_context_create(&pool, scope, LSF_TCP_BYTES, &context.key));
}

#ifndef LSF_OLD_SECURITY
static void observed(const char *name)
{
    lsf_ref_write("SECURITY_CONTROL ", 17);
    lsf_ref_write(name, lsf_ref_length(name));
    lsf_ref_write(" PASS\n", 6);
}
static void flush(void)
{
    struct rcu_head *head = pending;
    void (*done)(struct rcu_head *) = callback;
    assert(head && done);
    pending = NULL;
    callback = NULL;
    done(head);
}
#endif

int main(void)
{
    struct inode inode = {0};
    reset();
#ifdef LSF_OLD_SECURITY
    assert(!security_inode_alloc(&inode, GFP_NOFS));
    if (normal_allocated == 1 && pool.contexts[context.key.slot].live == 0) {
        puts("SECURITY_OLD general-composite-blob RED");
        return 2;
    }
    return 3;
#else
    struct sock sock = {0};
    struct lsf_factory_blob saved;
    struct lsf_prepaid_ticket original;
    lsf_u64 offset;
    assert(!security_inode_alloc(&inode, GFP_NOFS));
    security_inode_free(&inode);
    flush();
    assert(normal_allocated == 1 && normal_freed == 1 && callback_hooks == 1);
    observed("ordinary-cache-and-original-callback-preserved");
    reset();
    assert(!lsf_prepaid_security_inode_alloc(&inode, GFP_NOFS, &context));
    assert(!normal_allocated && alloc_hooks == 1 && pool.contexts[context.key.slot].live == 1);
    security_inode_free(&inode);
    assert(pending && free_hooks == 1 && !callback_hooks);
    assert(pool.contexts[context.key.slot].live == 1 && pool.contexts[context.key.slot].continuations == 1);
    observed("inode-blob-keeps-independent-rcu-owner");
    pool.contexts[context.key.slot].closed = 1;
    assert(!lsf_prepaid_recycle(&pool, context.key));
    flush();
    assert(callback_hooks == 1 && !normal_freed && !pool.contexts[context.key.slot].live);
    assert(!pool.contexts[context.key.slot].continuations && pool.records[0].phase == LSF_PREPAID_LIVE);
    assert(lsf_prepaid_recycle(&pool, context.key));
    observed("actual-callback-hooks-before-view-return-no-backing-refund");
    reset();
    hook_fail = 1;
    assert(lsf_prepaid_security_inode_alloc(&inode, GFP_NOFS, &context) == -1);
    assert(pending && free_hooks == 1 && pool.contexts[context.key.slot].live == 1);
    flush();
    assert(callback_hooks == 1 && !pool.contexts[context.key.slot].live);
    observed("inode-allocation-hook-error-retains-until-real-callback");
    reset();
    assert(!lsf_prepaid_security_sk_alloc(&sock, 2, GFP_KERNEL | __GFP_ZERO, &context));
    assert(!normal_allocated && pool.contexts[context.key.slot].live == 1);
    security_sk_free(&sock);
    assert(!sock.sk_security && free_hooks == 1 && !pool.contexts[context.key.slot].live && !normal_freed);
    observed("socket-original-free-hook-before-view-return");
    reset();
    hook_fail = 1;
    assert(lsf_prepaid_security_sk_alloc(&sock, 2, GFP_KERNEL | __GFP_ZERO, &context) == -1);
    assert(!sock.sk_security && free_hooks == 1 && !pool.contexts[context.key.slot].live);
    observed("socket-allocation-hook-error-keeps-original-cleanup");
    reset();
    assert(!lsf_prepaid_security_inode_alloc(&inode, GFP_NOFS, &context));
    assert(lsf_factory_blob_lookup(inode.i_security, LSF_PREPAID_INODE_BLOB, &saved) == 1);
    assert(!lsf_prepaid_return(&pool, context.key, saved.ticket));
    assert(pool.contexts[context.key.slot].poisoned && pool.contexts[context.key.slot].live == 1);
    observed("generic-return-cannot-refund-typed-blob");
    reset();
    assert(!lsf_prepaid_security_inode_alloc(&inode, GFP_NOFS, &context));
    assert(lsf_factory_blob_lookup(inode.i_security, LSF_PREPAID_SOCK_BLOB, &saved) == -1);
    assert(pool.poisoned && pool.contexts[context.key.slot].live == 1);
    observed("wrong-free-kind-poisons-without-refund");
    reset();
    assert(!lsf_prepaid_security_inode_alloc(&inode, GFP_NOFS, &context));
    assert(lsf_factory_blob_queue(inode.i_security) == 1);
    assert(lsf_factory_blob_queue(inode.i_security) == -1);
    assert(pool.contexts[context.key.slot].poisoned && pool.contexts[context.key.slot].continuations == 1);
    observed("duplicate-rcu-queue-retains-original-charge");
    reset();
    assert(!lsf_prepaid_security_sk_alloc(&sock, 2, GFP_KERNEL | __GFP_ZERO, &context));
    assert(lsf_factory_blob_lookup(sock.sk_security, LSF_PREPAID_SOCK_BLOB, &saved) == 1);
    security_sk_free(&sock);
    pool.contexts[context.key.slot].closed = 1;
    assert(lsf_prepaid_recycle(&pool, context.key));
    assert(!lsf_factory_blob_finish(saved, LSF_PREPAID_SOCK_BLOB));
    observed("retired-generation-cannot-finish-again");
    reset();
    assert(lsf_prepaid_allocate(&pool, context.key, LSF_TCP_BYTES,
                                0, (struct lsf_prepaid_ticket){0}, &original, &offset));
    assert(lsf_prepaid_security_inode_alloc(&inode, GFP_NOFS, &context) == -ENOMEM);
    assert(!normal_allocated && pool.contexts[context.key.slot].live == 1);
    observed("original-96k-admission-before-allocation-no-fallback");
    reset();
    assert(lsf_factory_blob_lookup(backing + 1, LSF_PREPAID_INODE_BLOB, &saved) == -1);
    assert(pool.poisoned && !normal_freed);
    observed("unknown-interior-address-never-reaches-normal-free");
    return 0;
#endif
}
