/* SPDX-License-Identifier: GPL-2.0-only */
/* Supplemental only: actual selected producer/destructor/helper bodies with
 * explicit type, policy, serialization and RCU doubles. No Linux ABI, LSM,
 * policy implementation, spinlock, callback scheduler or final-free executes. */
#include "reference-io.h"
#include <stdbool.h>
#include "prepaid.h"
#define CONFIG_LSF_STREAM_FACTORY 1
#define EOPNOTSUPP 95
#define ENOMEM 12
#define GFP_ATOMIC 4u
#define ERR_PTR(error) ((void *)(intptr_t)(error))
#define NETLBL_SECATTR_DOMAIN 0x00000001u
#define NETLBL_SECATTR_CACHE 0x00000002u
#define NETLBL_SECATTR_MLS_LVL 0x00000004u
#define NETLBL_SECATTR_MLS_CAT 0x00000008u
#define NETLBL_SECATTR_SECID 0x00000010u
#define NETLBL_SECATTR_FREE_DOMAIN 0x01000000u
#define NETLBL_SECATTR_DOMAIN_CPY (NETLBL_SECATTR_DOMAIN | NETLBL_SECATTR_FREE_DOMAIN)
#define container_of(value, type, member) ((type *)((char *)(value) - offsetof(type, member)))
typedef unsigned int u32;
struct rcu_head { unsigned int marker; };
struct ip_options_rcu { struct rcu_head rcu; unsigned int marker; };
struct netlbl_lsm_catmap { struct netlbl_lsm_catmap *next; unsigned long bits; };
struct netlbl_lsm_secattr {
    u32 flags;
    char *domain;
    void *cache;
    struct { struct { struct netlbl_lsm_catmap *cat; } mls; } attr;
};
struct sk_security_struct { u32 sid; struct netlbl_lsm_secattr *nlbl_secattr; };
struct lsf_factory_context { struct lsf_prepaid_key key; };
struct lsf_factory_blob { struct lsf_factory_context *context; struct lsf_prepaid_ticket ticket; };
struct sock {
    struct lsf_factory_context *sk_lsf_factory;
    lsf_u64 sk_lsf_view_generation;
    unsigned int sk_lsf_view_slot;
    struct sk_security_struct security;
};
#define selinux_sock(sk) (&(sk)->security)
static struct { struct lsf_prepaid pool; void *pages; } factory;
static struct lsf_factory_context context;
static struct lsf_factory_blob parent;
static struct sock socket;
static _Alignas(64) unsigned char backing[LSF_BACKING_BYTES], normal[256];
static unsigned int normal_allocated, normal_freed, cache_freed, policy_calls, policy_fail;
static struct rcu_head *pending;
static void (*callback)(struct rcu_head *);
static void *memcpy(void *dest, const void *source, size_t bytes)
{
    unsigned char *d = dest;
    const unsigned char *s = source;
    size_t i;
    for (i = 0; i < bytes; ++i) d[i] = s[i];
    return dest;
}
static size_t strnlen(const char *source, size_t limit)
{
    size_t i;
    for (i = 0; i < limit && source[i]; ++i) { }
    return i;
}
static void kfree(void *value)
{
    assert(!value || value == normal);
    normal_freed += value != NULL;
}
static void netlbl_secattr_cache_free(void *value)
{
    assert(value == normal);
    cache_freed++;
}
static struct netlbl_lsm_secattr *netlbl_secattr_alloc(unsigned int priority)
{
    assert(priority == GFP_ATOMIC);
    normal_allocated++;
    return memset(normal, 0, sizeof(normal));
}
static int security_netlbl_sid_to_secattr(u32 sid, struct netlbl_lsm_secattr *label)
{
    assert(sid == 7 && label);
    policy_calls++;
    return policy_fail ? -7 : 0;
}
int lsf_prepaid_security_sid_to_secattr(u32 sid, struct netlbl_lsm_secattr *label,
                                       const struct lsf_factory_blob *source)
{
    assert(source->context == &context);
    return security_netlbl_sid_to_secattr(sid, label);
}
void lsf_factory_poison(struct lsf_factory_context *owner)
{
    if (owner == &context) factory.pool.contexts[context.key.slot].poisoned = 1;
    else factory.pool.poisoned = 1;
}
static int lsf_factory_blob_lookup_locked(const void *address, unsigned int kind, struct lsf_factory_blob *copy)
{
    struct lsf_prepaid_key key;
    uintptr_t base = (uintptr_t)backing, value = (uintptr_t)address;
    if (value < base || value - base >= sizeof(backing)) return 0;
    if (!lsf_prepaid_blob_find(&factory.pool, value - base, kind, &key, &copy->ticket)) return -1;
    assert(key.slot == context.key.slot && key.generation == context.key.generation);
    copy->context = &context;
    return 1;
}
static unsigned int pool_lock;
#define spin_lock_irqsave(lock, flags) do { (void)(lock); (flags) = 0; } while (0)
#define spin_unlock_irqrestore(lock, flags) do { (void)(lock); (void)(flags); } while (0)
static void *page_address(void *pages) { assert(pages == backing); return pages; }
static struct lsf_factory_context *lsf_factory_context_current(struct lsf_factory_context *value)
{
    return value == &context && lsf_prepaid_context_for(&factory.pool, context.key) ? value : NULL;
}
int lsf_factory_blob_lookup(const void *address, unsigned int kind, struct lsf_factory_blob *copy)
{
    return lsf_factory_blob_lookup_locked(address, kind, copy);
}
int lsf_factory_blob_finish(struct lsf_factory_blob copy, unsigned int kind)
{
    return lsf_prepaid_blob_finish(&factory.pool, copy.context->key, copy.ticket, kind);
}
static void call_rcu(struct rcu_head *head, void (*done)(struct rcu_head *))
{
    assert(!pending);
    pending = head;
    callback = done;
}
bool lsf_prepaid_label_domain_return(const void *);
bool lsf_prepaid_label_catmap_return(const void *);
bool lsf_prepaid_label_secattr_return(struct netlbl_lsm_secattr *);
#include "netlabel-derived-reference.h"

static void reset(void)
{
    struct lsf_scope scope = {{1,2,3,4,5,6,7,8}};
    lsf_u64 offset;
    memset(&factory.pool, 0, sizeof(factory.pool));
    memset(backing, 0, sizeof(backing));
    factory.pages = backing;
    memset(&socket, 0, sizeof(socket));
    normal_allocated = normal_freed = cache_freed = policy_calls = policy_fail = 0;
    pending = NULL;
    callback = NULL;
    assert(lsf_prepaid_initialize(&factory.pool));
    assert(lsf_prepaid_context_create(&factory.pool, scope, LSF_TCP_BYTES, &context.key));
    parent.context = &context;
    assert(lsf_prepaid_allocate(&factory.pool, context.key, sizeof(socket), 0,
        (struct lsf_prepaid_ticket){0}, &parent.ticket, &offset));
    socket = (struct sock){&context, parent.ticket.generation, parent.ticket.slot, {7, NULL}};
    /* Address identity is explicit in the protocol source double; producer
     * source() is tested independently below against the in-backing socket. */
}
#ifndef LSF_OLD_NETLABEL
static void observed(const char *label)
{
    lsf_ref_write("NETLABEL_CONTROL ", 17);
    lsf_ref_write(label, lsf_ref_length(label));
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
    reset();
#ifdef LSF_OLD_NETLABEL
    assert(selinux_netlbl_sock_genattr(&socket) == (void *)normal);
    assert(normal_allocated == 1 && policy_calls == 1);
    puts("NETLABEL_OLD general-label-allocation RED");
    return 2;
#else
    struct netlbl_lsm_secattr *label;
    struct netlbl_lsm_catmap *cat;
    struct ip_options_rcu *options;
    struct lsf_factory_blob saved, source;
    struct lsf_prepaid_ticket extra;
    lsf_u64 offset;
    unsigned int before;
    struct sock *actual = (void *)(backing + factory.pool.records[parent.ticket.slot].offset);
    *actual = socket;
    assert(lsf_prepaid_netlabel_source(actual, &source) == 1);
    assert(source.context == &context && source.ticket.generation == parent.ticket.generation);
    observed("actual-origin-fields-require-existing-live-object");
    label = lsf_prepaid_netlabel_sock_genattr(&socket, &parent);
    assert(label && label != (void *)normal && !normal_allocated && policy_calls == 1);
    assert(lsf_prepaid_netlabel_sock_genattr(&socket, &parent) == label && policy_calls == 1);
    assert(factory.pool.contexts[context.key.slot].live == 2);
    observed("existing-owner-label-and-cache-no-generic-allocation");
    assert(lsf_prepaid_label_secattr_return(label));
    assert(factory.pool.contexts[context.key.slot].live == 1 && !normal_freed);
    observed("original-label-destructor-returns-only-child-view");
    reset();
    policy_fail = 1;
    assert(lsf_prepaid_netlabel_sock_genattr(&socket, &parent) == ERR_PTR(-7));
    assert(factory.pool.contexts[context.key.slot].live == 1 && !socket.security.nlbl_secattr && !normal_freed);
    observed("original-policy-error-cleanup-does-not-publish-label");
    reset();
    label = lsf_prepaid_netlabel_sock_genattr(&socket, &parent);
    label->domain = lsf_prepaid_netlabel_strdup("actual-policy-domain", &parent);
    cat = lsf_factory_child_allocate(parent, sizeof(*cat), LSF_PREPAID_LABEL_CATMAP);
    assert(label->domain && cat);
    label->flags = NETLBL_SECATTR_DOMAIN_CPY | NETLBL_SECATTR_MLS_CAT;
    label->attr.mls.cat = cat;
    assert(factory.pool.contexts[context.key.slot].live == 4);
    assert(lsf_prepaid_label_secattr_return(label));
    assert(factory.pool.contexts[context.key.slot].live == 1 && !normal_freed && !cache_freed);
    observed("domain-and-category-chain-return-under-original-context");
    reset();
    options = lsf_factory_child_allocate(parent, sizeof(*options), LSF_PREPAID_IP_OPTIONS);
    assert(options && lsf_factory_options_publish(options) == 1);
    assert(lsf_prepaid_options_retire(options));
    assert(pending && factory.pool.contexts[context.key.slot].live == 2 && factory.pool.contexts[context.key.slot].continuations == 1);
    factory.pool.contexts[context.key.slot].closed = 1;
    assert(lsf_prepaid_return(&factory.pool, context.key, parent.ticket));
    assert(!lsf_prepaid_recycle(&factory.pool, context.key));
    flush();
    assert(!factory.pool.contexts[context.key.slot].live && !factory.pool.contexts[context.key.slot].continuations);
    assert(lsf_prepaid_recycle(&factory.pool, context.key) && factory.pool.records[0].phase == LSF_PREPAID_LIVE);
    observed("published-options-outlive-socket-until-actual-callback");
    reset();
    options = lsf_factory_child_allocate(parent, sizeof(*options), LSF_PREPAID_IP_OPTIONS);
    assert(lsf_factory_options_publish(options) == 1);
    assert(lsf_factory_options_owned(options, parent) == 1);
    assert(lsf_factory_options_owned(normal, parent) == 0 && factory.pool.poisoned);
    observed("owned-option-replacement-refuses-normal-origin");
    reset();
    options = lsf_factory_child_allocate(parent, sizeof(*options), LSF_PREPAID_IP_OPTIONS);
    assert(lsf_factory_options_publish(options) == 1);
    assert(lsf_prepaid_options_failed_return(options));
    assert(factory.pool.contexts[context.key.slot].poisoned && factory.pool.contexts[context.key.slot].live == 2);
    observed("published-option-cannot-take-synchronous-failure-refund");
    reset();
    options = lsf_factory_child_allocate(parent, sizeof(*options), LSF_PREPAID_IP_OPTIONS);
    assert(lsf_factory_options_publish(options) == 1 && lsf_factory_options_queue(options) == 1);
    assert(lsf_factory_options_queue(options) == -1);
    assert(factory.pool.contexts[context.key.slot].live == 2 && factory.pool.contexts[context.key.slot].continuations == 1);
    observed("duplicate-options-queue-retains-original-charge");
    reset();
    factory.pool.contexts[context.key.slot].closed = 1;
    assert(lsf_factory_child_allocate(parent, 8, LSF_PREPAID_CIPSO_BUFFER));
    assert(!lsf_prepaid_allocate(&factory.pool, context.key, 8, 0, (struct lsf_prepaid_ticket){0}, &extra, &offset));
    observed("sealed-root-allows-only-live-original-descendant");
    reset();
    saved = parent;
    assert(lsf_prepaid_return(&factory.pool, context.key, parent.ticket));
    assert(!lsf_factory_child_allocate(saved, 8, LSF_PREPAID_CIPSO_BUFFER));
    assert(!factory.pool.contexts[context.key.slot].live);
    observed("retired-parent-cannot-create-late-child");
    reset();
    before = (unsigned int)factory.pool.contexts[context.key.slot].cursor;
    assert(lsf_factory_child_allocate(parent, LSF_TCP_BYTES - before, LSF_PREPAID_CIPSO_BUFFER));
    assert(!lsf_factory_child_allocate(parent, 1, LSF_PREPAID_LABEL_DOMAIN));
    assert(factory.pool.contexts[context.key.slot].cursor == LSF_TCP_BYTES && !normal_allocated);
    observed("original-96k-preallocation-refusal-without-fallback");
    reset();
    label = lsf_prepaid_netlabel_sock_genattr(&socket, &parent);
    label->flags = NETLBL_SECATTR_CACHE;
    label->cache = normal;
    assert(lsf_prepaid_label_secattr_return(label));
    assert(factory.pool.contexts[context.key.slot].poisoned && factory.pool.contexts[context.key.slot].live == 2 && !cache_freed);
    observed("unknown-cache-callback-poisons-without-refund");
    reset();
    label = lsf_prepaid_netlabel_sock_genattr(&socket, &parent);
    cat = lsf_factory_child_allocate(parent, sizeof(*cat), LSF_PREPAID_LABEL_CATMAP);
    cat->next = cat;
    label->flags = NETLBL_SECATTR_MLS_CAT;
    label->attr.mls.cat = cat;
    assert(lsf_prepaid_label_secattr_return(label));
    assert(factory.pool.contexts[context.key.slot].poisoned && factory.pool.contexts[context.key.slot].live == 3);
    observed("cyclic-category-chain-prevalidation-retains-every-owner");
    reset();
    assert(lsf_prepaid_label_domain_return(backing + 1));
    assert(factory.pool.poisoned && !normal_freed);
    observed("unknown-interior-never-reaches-normal-free");
    reset();
    label = netlbl_secattr_alloc(GFP_ATOMIC);
    netlbl_secattr_free(label);
    assert(normal_allocated == 1 && normal_freed == 1 && factory.pool.contexts[context.key.slot].live == 1);
    observed("ordinary-generic-allocation-and-free-preserved");
    reset();
    options = lsf_factory_child_allocate(parent, sizeof(*options), LSF_PREPAID_IP_OPTIONS);
    assert(lsf_factory_blob_lookup(options, LSF_PREPAID_IP_OPTIONS, &saved) == 1);
    assert(lsf_factory_options_publish(options) == 1);
    assert(!lsf_prepaid_return(&factory.pool, context.key, saved.ticket));
    assert(factory.pool.contexts[context.key.slot].live == 2);
    observed("generic-return-cannot-refund-typed-published-option");
    return 0;
#endif
}
