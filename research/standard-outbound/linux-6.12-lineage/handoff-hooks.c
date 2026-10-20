/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in the same uninstalled private lineage translation unit. */
#include <linux/sock_diag.h>
#include <net/lsf_stream_handoff.h>

void lsf_stream_socket_reserved(struct lsf_bundle *bundle, const void *address)
{
    unsigned long flags;
    spin_lock_irqsave(&lsf_stream_lock, flags);
    (void)lsf_socket_bind_reserved(&lsf_stream_state, bundle, (unsigned long)address);
    spin_unlock_irqrestore(&lsf_stream_lock, flags);
}

void lsf_stream_socket_initialized(struct sock *sk)
{
    struct lsf_handoff handoff;
    lsf_u64 cookie;
    unsigned long flags;
    int selected;
    spin_lock_irqsave(&lsf_stream_lock, flags);
    selected = lsf_socket_capture_handoff(&lsf_stream_state, (unsigned long)sk, &handoff);
    spin_unlock_irqrestore(&lsf_stream_lock, flags);
    if (!selected)
        return;
    /* Exact caller owns the object through this call. Never read an allocator
     * preimage, force a reset, invent a cookie, or hold our lock over this. */
    cookie = sock_gen_cookie(sk);
    spin_lock_irqsave(&lsf_stream_lock, flags);
    (void)lsf_socket_commit_handoff(&lsf_stream_state, &handoff,
                                   (unsigned long)sk, cookie);
    spin_unlock_irqrestore(&lsf_stream_lock, flags);
}
