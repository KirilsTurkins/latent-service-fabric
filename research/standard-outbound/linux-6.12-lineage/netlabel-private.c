/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in authenticated net/netlabel/netlabel_kapi.c. Actual nested label
 * producers use an existing socket birth; no current-task ambient allocator,
 * caller proof, pointer registration or normal-host allocator replacement. */
#include "../factory-private.h"
#include <net/lsf_stream_netlabel_private.h>
#include <net/ip.h>
#include <net/sock.h>

int lsf_prepaid_netlabel_source(struct sock *sk, struct lsf_factory_blob *source)
{
    struct lsf_factory_context *context;
    struct lsf_prepaid_ticket ticket;
    if (!sk)
        return 0;
    context = sk->sk_lsf_factory;
    ticket = (struct lsf_prepaid_ticket){sk->sk_lsf_view_slot,
                                        sk->sk_lsf_view_generation};
    if (!context && !ticket.slot && !ticket.generation)
        return 0;
    if (!context || !ticket.slot || !ticket.generation ||
        !lsf_factory_protocol_parent(sk, context, ticket, source)) {
        lsf_factory_poison(context);
        return -EOPNOTSUPP;
    }
    return 1;
}

static bool lsf_prepaid_label_return(const void *address, unsigned int kind)
{
    struct lsf_factory_blob copy;
    int owned = lsf_factory_blob_lookup(address, kind, &copy);
    if (owned == 0)
        return false;
    if (owned == 1)
        lsf_factory_blob_finish(copy, kind);
    /* Unknown in-arena storage remains held, never falls through to kfree. */
    return true;
}

bool lsf_prepaid_label_domain_return(const void *domain)
{
    return lsf_prepaid_label_return(domain, LSF_PREPAID_LABEL_DOMAIN);
}

bool lsf_prepaid_label_catmap_return(const void *catmap)
{
    return lsf_prepaid_label_return(catmap, LSF_PREPAID_LABEL_CATMAP);
}

bool lsf_prepaid_cipso_buffer_return(const void *buffer)
{
    return lsf_prepaid_label_return(buffer, LSF_PREPAID_CIPSO_BUFFER);
}

bool lsf_prepaid_options_failed_return(const void *options)
{
    /* Published options cannot use this synchronous failure return. The actual
     * record state refuses them and retains the original owner instead. */
    return lsf_prepaid_label_return(options, LSF_PREPAID_IP_OPTIONS);
}

char *lsf_prepaid_netlabel_strdup(const char *text,
                                  const struct lsf_factory_blob *source)
{
    unsigned long bytes;
    char *copy;
    if (!text || !source)
        return NULL;
    bytes = strnlen(text, LSF_TCP_BYTES);
    if (bytes == LSF_TCP_BYTES)
        return NULL;
    /* The SAME original context's remaining rounded byte/slot capacity is
     * checked before the copy. No new string quota, heap or fallback owner. */
    copy = lsf_factory_child_allocate(*source, bytes + 1, LSF_PREPAID_LABEL_DOMAIN);
    if (copy)
        memcpy(copy, text, bytes + 1);
    return copy;
}

/* Validate the actual complete child chain BEFORE any destructor call, so a
 * wrong-kind, mixed-context, cyclic or unexpected cache pointer cannot partly
 * refund the original graph or invoke an unclosed cache-free callback. */
bool lsf_prepaid_label_secattr_return(struct netlbl_lsm_secattr *secattr)
{
    struct lsf_factory_blob copy, child;
    struct netlbl_lsm_catmap *iter;
    unsigned int count;
    const u32 allowed = NETLBL_SECATTR_DOMAIN_CPY | NETLBL_SECATTR_SECID |
                        NETLBL_SECATTR_MLS_LVL | NETLBL_SECATTR_MLS_CAT;
    int owned = lsf_factory_blob_lookup(secattr, LSF_PREPAID_LABEL, &copy);
    if (owned == 0)
        return false;
    if (owned < 0)
        return true;
    if ((secattr->flags & ~allowed) ||
        !!(secattr->flags & NETLBL_SECATTR_DOMAIN) !=
        !!(secattr->flags & NETLBL_SECATTR_FREE_DOMAIN))
        goto unknown;
    if (secattr->flags & NETLBL_SECATTR_FREE_DOMAIN) {
        if (lsf_factory_blob_lookup(secattr->domain, LSF_PREPAID_LABEL_DOMAIN, &child) != 1 ||
            child.context != copy.context)
            goto unknown;
    }
    if (secattr->flags & NETLBL_SECATTR_MLS_CAT) {
        for (count = 0, iter = secattr->attr.mls.cat;
             iter && count < LSF_ALLOCATION_SLOTS; ++count, iter = iter->next) {
            if (lsf_factory_blob_lookup(iter, LSF_PREPAID_LABEL_CATMAP, &child) != 1 ||
                child.context != copy.context)
                goto unknown;
        }
        if (iter || !count)
            goto unknown;
    }
    /* Original destructor order and all original flag tests remain. Its
     * closed domain/catmap free branches return only the original birth views. */
    netlbl_secattr_destroy(secattr);
    lsf_factory_blob_finish(copy, LSF_PREPAID_LABEL);
    return true;
unknown:
    lsf_factory_poison(copy.context);
    return true;
}

/* The actual source call site detaches or replaces this IP option before
 * entering here. It was marked PUBLISHED before its original publication.
 * This retains the same original context through its REAL RCU callback. */
static void lsf_prepaid_options_callback(struct rcu_head *head)
{
    struct ip_options_rcu *options = container_of(head, struct ip_options_rcu, rcu);
    struct lsf_factory_blob copy;
    int owned = lsf_factory_blob_lookup(options, LSF_PREPAID_IP_OPTIONS, &copy);
    if (owned == 1)
        lsf_factory_blob_finish(copy, LSF_PREPAID_IP_OPTIONS);
    else
        lsf_factory_poison(NULL);
    /* Copy precedes return; neither options nor head is read afterwards.
     * Unknown origin is poisoned by lookup and remains retained. */
}

bool lsf_prepaid_options_retire(struct ip_options_rcu *options)
{
    int owned = lsf_factory_options_queue(options);
    if (owned == 0)
        return false;
    if (owned == 1)
        call_rcu(&options->rcu, lsf_prepaid_options_callback);
    return true;
}
