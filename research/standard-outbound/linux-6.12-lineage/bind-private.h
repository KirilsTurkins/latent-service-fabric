/* SPDX-License-Identifier: GPL-2.0-only */
/* Builtin source seams, never an address registrar or exported ownership API. */
#ifndef LSF_STREAM_BIND_PRIVATE_H
#define LSF_STREAM_BIND_PRIVATE_H
#include <linux/types.h>
struct sock;
struct net;
struct kmem_cache;
struct inet_bind_bucket;
struct inet_bind_hashbucket;
#ifdef CONFIG_LSF_STREAM_FACTORY
int lsf_prepaid_bind_check(const struct sock *);
int lsf_prepaid_bind_owned(const struct sock *);
struct inet_bind_bucket *lsf_prepaid_bind_bucket_create(struct kmem_cache *,
    struct net *, struct inet_bind_hashbucket *, unsigned short, int,
    const struct sock *);
void *lsf_prepaid_bind2_allocate(struct kmem_cache *, struct net *, const struct sock *);
bool lsf_prepaid_bind_return(const void *, unsigned int);
#endif
#endif
