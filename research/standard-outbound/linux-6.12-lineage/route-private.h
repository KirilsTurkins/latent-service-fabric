/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef LSF_STREAM_ROUTE_PRIVATE_H
#define LSF_STREAM_ROUTE_PRIVATE_H
struct net;
struct sock;
struct flowi4;
struct net_device;
struct rtable;
struct lsf_factory_blob;
struct rtable *lsf_prepaid_route_key(struct net *, struct flowi4 *, const struct sock *);
struct rtable *lsf_prepaid_route_xfrm(struct net *, struct rtable *,
                                    struct flowi4 *, const struct sock *);
#endif
