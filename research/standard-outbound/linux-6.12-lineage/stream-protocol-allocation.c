/* SPDX-License-Identifier: GPL-2.0-only */
/* Normal source-only replacement of ONE private allocator body. Ordinary
 * slab allocation and historical TCP-only derivation remain unchanged.
 * This does not select a consumer or lift any packet/LSM/Netlabel refusal. */
struct sock *lsf_prepaid_protocol_allocate(struct proto *prot, gfp_t priority,
                                          int family, struct lsf_factory_context *context)
{
    struct lsf_prepaid_ticket ticket = {0};
    struct sock *sk;
    unsigned long bytes = 0;
    static_assert(__alignof__(struct tcp_sock) <= 64);
    static_assert(__alignof__(struct udp_sock) <= 64);
    static_assert(sizeof(struct tcp_sock) <= LSF_TCP_BYTES);
    static_assert(sizeof(struct udp_sock) <= LSF_DNS_BYTES);
    if (!context || priority != (GFP_KERNEL | __GFP_ZERO) ||
        !lsf_prepaid_protocol_security_supported()) return NULL;
    if (family == PF_INET) {
        if (prot == &tcp_prot) bytes = sizeof(struct tcp_sock);
        else if (prot == &udp_prot) bytes = sizeof(struct udp_sock);
    }
#if IS_BUILTIN(CONFIG_IPV6)
    else if (family == PF_INET6) {
        static_assert(__alignof__(struct tcp6_sock) <= 64);
        static_assert(__alignof__(struct udp6_sock) <= 64);
        static_assert(sizeof(struct tcp6_sock) <= LSF_TCP_BYTES);
        static_assert(sizeof(struct udp6_sock) <= LSF_DNS_BYTES);
        if (prot == &tcpv6_prot) bytes = sizeof(struct tcp6_sock);
        else if (prot == &udpv6_prot) bytes = sizeof(struct udp6_sock);
    }
#endif
    /* Actual compiled type + exact registered proto; no integer size claim,
     * wildcard protocol, module autoload, raw socket or other-family fallback.
     * The SAME original context enforces its96/64KiB and record ceiling BEFORE
     * this physical initialization, including TCP in an original DNS context. */
    if (!bytes || prot->obj_size != bytes) return NULL;
    sk = lsf_factory_allocate(context, bytes,
        (struct lsf_prepaid_ticket){0}, 0, &ticket);
    if (!sk) return NULL;
    sk->sk_lsf_factory = context;
    sk->sk_lsf_view_generation = ticket.generation;
    sk->sk_lsf_view_slot = ticket.slot;
    return sk;
}
