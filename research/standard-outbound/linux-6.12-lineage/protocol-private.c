/* SPDX-License-Identifier: GPL-2.0-only */
/* Included inside the exact maintained net/core/sock.c derivation. Uninstalled.
 * The selected complete factory consumer is still NULL. This is not a general
 * allocator, public pointer binder, physical-free proof or profile selector. */
#include <linux/in.h>
#include <net/tcp.h>
#include "../factory-private.h"
#include <net/lsf_stream_protocol_private.h>

/* Ordinary shared-slab constructors initialize private noncopy fields to the
 * single nonowned state before security/publication. Their allocator and all
 * existing initialization, cgroup, security and module ownership stay intact. */
void lsf_prepaid_protocol_clear(struct sock *sk)
{
    sk->sk_lsf_factory = NULL;
    sk->sk_lsf_view_generation = 0;
    sk->sk_lsf_view_slot = 0;
}

struct sock *lsf_prepaid_protocol_allocate(struct proto *prot, gfp_t priority,
                                          int family, struct lsf_factory_context *context)
{
    struct lsf_prepaid_ticket ticket = {0};
    struct sock *sk;
    /* These use actual selected compiler types, not a userspace size claim.
     * Complete outer/TCP/SKB/RX/LSM geometry still has to fit the original
     * arena. A successful object allocation alone cannot qualify that closure. */
    static_assert(__alignof__(struct tcp_sock) <= 64);
    static_assert(sizeof(struct tcp_sock) <= LSF_TCP_BYTES);
    if (!context || prot != &tcp_prot || prot->obj_size != sizeof(struct tcp_sock) ||
        family != PF_INET || priority != (GFP_KERNEL | __GFP_ZERO) ||
        !lsf_prepaid_protocol_security_supported())
        return NULL;
    sk = lsf_factory_allocate(context, prot->obj_size,
        (struct lsf_prepaid_ticket){0}, 0, &ticket);
    if (!sk)
        return NULL;
    /* The allocator zeroes the entire actual object. Origin is attached HERE
     * at birth, before the unchanged security allocation and module get calls.
     * Nothing accepts an independently allocated object as an owned one. */
    sk->sk_lsf_factory = context;
    sk->sk_lsf_view_generation = ticket.generation;
    sk->sk_lsf_view_slot = ticket.slot;
    return sk;
}

/* Called only where the original allocator would return its final sock object,
 * after original security/cgroup/sk_owner cleanup. For published owned sockets,
 * private initialization selects SOCK_RCU_FREE; the original sk_destruct/RCU
 * path reaches this point. Original wmem/other live references still delay it.
 * Copy everything BEFORE view return. The caller has already copied the module
 * owner needed after storage return. No backing pages are physically freed. */
bool lsf_prepaid_protocol_return(struct sock *sk)
{
    struct lsf_factory_context *context = sk->sk_lsf_factory;
    struct lsf_prepaid_ticket ticket = {
        .slot = sk->sk_lsf_view_slot,
        .generation = sk->sk_lsf_view_generation,
    };
    if (!context && !ticket.slot && !ticket.generation)
        return false;
    if (!context || !ticket.slot || !ticket.generation ||
        !lsf_factory_return(context, ticket))
        lsf_factory_poison(context);
    /* Even inconsistent private fields must not send arena storage to SLUB or
     * kmalloc. Unknown state retains capacity and fences, rather than refunds. */
    return true;
}
