/* SPDX-License-Identifier: GPL-2.0-only */
/* Private maintained-kernel consumer, never a socket-origin registration ABI. */
#ifndef LSF_STREAM_PROTOCOL_PRIVATE_H
#define LSF_STREAM_PROTOCOL_PRIVATE_H
#include <linux/gfp_types.h>
struct net;
struct proto;
struct sock;
struct socket;
struct net_proto_family;
struct lsf_factory_context;
struct inode;

#ifdef CONFIG_LSF_STREAM_FACTORY
void lsf_prepaid_protocol_clear(struct sock *);
struct sock *lsf_prepaid_protocol_allocate(struct proto *, gfp_t, int,
                                          struct lsf_factory_context *);
bool lsf_prepaid_protocol_return(struct sock *);
bool lsf_prepaid_protocol_security_supported(void);
bool lsf_prepaid_protocol_family(const struct net_proto_family *);
int lsf_prepaid_security_inode_alloc(struct inode *, gfp_t,
                                     struct lsf_factory_context *);
int lsf_prepaid_security_sk_alloc(struct sock *, int, gfp_t,
                                  struct lsf_factory_context *);
struct sock *lsf_prepaid_sk_alloc(struct net *, int, gfp_t, struct proto *, int,
                                  struct lsf_factory_context *);
int lsf_prepaid_inet_create(struct net *, struct socket *, int, int,
                            struct lsf_factory_context *, const struct net_proto_family *);
int lsf_prepaid_sock_create(struct net *, int, int, int, struct socket **, int,
                            struct lsf_factory_context *);
#endif
#endif
