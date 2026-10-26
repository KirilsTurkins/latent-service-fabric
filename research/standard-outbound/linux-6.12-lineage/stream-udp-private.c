/* SPDX-License-Identifier: GPL-2.0-only */
/* Include in original sock.c after its actual private helpers. SOURCE ONLY.
 * This is a prior socket-birth lookup, never an origin registration/allocator
 * override. IPv6 send/route/label ownership remains a separate missing port. */
#include "../factory-private.h"
#include <net/udp.h>
#include <net/lsf_stream_packet_private.h>

int lsf_prepaid_stream_udp_sock(struct sock *sk)
{
    struct lsf_factory_blob parent;
    struct lsf_prepaid_ticket ticket;
    if (!sk) return 0;
    if (!sk->sk_lsf_factory && !sk->sk_lsf_view_slot && !sk->sk_lsf_view_generation) return 0;
    if (!sk->sk_lsf_factory) return -EOPNOTSUPP;
    ticket = (struct lsf_prepaid_ticket){sk->sk_lsf_view_slot, sk->sk_lsf_view_generation};
    if (!lsf_factory_protocol_parent(sk, sk->sk_lsf_factory, ticket, &parent) ||
        sk->sk_family != AF_INET || sk->sk_type != SOCK_DGRAM ||
        sk->sk_protocol != IPPROTO_UDP || sk->sk_prot != &udp_prot)
        return -EOPNOTSUPP;
    return 1;
}
