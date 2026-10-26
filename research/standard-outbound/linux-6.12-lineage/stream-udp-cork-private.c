/* SPDX-License-Identifier: GPL-2.0-only */
/* Include in original IPv4 ip_output.c. The caller owns the original socket
 * lock/reference and actual cork; no pointer/size can create a scope owner. */
#include "../factory-private.h"
#include <net/lsf_stream_packet_private.h>

static int lsf_stream_udp_cork_parent(struct sock *sk, struct lsf_factory_blob *parent)
{
    struct lsf_prepaid_ticket ticket;
    if (lsf_prepaid_stream_udp_sock(sk) != 1) return 0;
    ticket = (struct lsf_prepaid_ticket){sk->sk_lsf_view_slot, sk->sk_lsf_view_generation};
    return lsf_factory_protocol_parent(sk, sk->sk_lsf_factory, ticket, parent);
}

struct ip_options *lsf_prepaid_stream_udp_cork_allocate(struct sock *sk)
{
    struct lsf_factory_blob parent;
    if (__alignof__(struct ip_options) > 64 ||
        !lsf_stream_udp_cork_parent(sk, &parent)) return NULL;
    /* Same fixed original IPv4 option maximum; plain copied cork storage is
     * DISTINCT from published ip_options_rcu. Prepay before memcpy/publication.
     * Original child allocator also revalidates LIVE parent under pool_lock. */
    return lsf_factory_stream_cork_allocate(parent);
}

int lsf_prepaid_stream_udp_cork_current(struct sock *sk, const struct ip_options *address)
{
    struct lsf_factory_blob parent;
    if (!lsf_stream_udp_cork_parent(sk, &parent)) return 0;
    /* SAME-lock check of actual private child extent and original parent
     * ticket/generation, not context-only membership or adopted storage. */
    return lsf_factory_stream_cork_current(address, parent);
}

int lsf_prepaid_stream_udp_cork_return(struct ip_options **slot)
{
    struct lsf_factory_blob copy;
    int owned;
    if (!slot) return -1;
    owned = lsf_factory_blob_lookup(*slot, LSF_PREPAID_CORK_OPTIONS, &copy);
    if (!owned) return 0; /* Ordinary outside pointer/NULL: original kfree. */
    *slot = NULL; /* Clear actual cork alias BEFORE actual record return. */
    if (owned == 1 && !lsf_factory_stream_cork_finish(copy))
        return -1;
    /* Unknown private storage remains paid; never an ordinary kfree. */
    return owned;
}
