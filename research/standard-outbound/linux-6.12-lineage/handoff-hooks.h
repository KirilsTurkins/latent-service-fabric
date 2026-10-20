/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef LSF_STREAM_HANDOFF_HOOKS_H
#define LSF_STREAM_HANDOFF_HOOKS_H
#include <net/lsf_stream_handoff_core.h>
struct sock;
#ifdef CONFIG_LSF_STREAM_LINEAGE
void lsf_stream_socket_reserved(struct lsf_bundle *bundle, const void *address);
void lsf_stream_socket_initialized(struct sock *sk);
#else
static inline void lsf_stream_socket_reserved(struct lsf_bundle *bundle, const void *address)
{
    (void)bundle;
    (void)address;
}
static inline void lsf_stream_socket_initialized(struct sock *sk) { (void)sk; }
#endif
#endif
