/* SPDX-License-Identifier: GPL-2.0-only */
/* Private maintained-kernel linear packet producers. Not an origin binder,
 * public ABI, complete platform selection or final-free certificate. */
#ifndef LSF_STREAM_PACKET_PRIVATE_H
#define LSF_STREAM_PACKET_PRIVATE_H
#define LSF_STREAM_PACKET_SOURCE 1
struct sk_buff;
struct sock;
struct lsf_factory_blob;

/* Match only a prior live PACKET birth or the corresponding known AUDIT kind.
 * The latter remains owned by the existing audit routing; unknown interior
 * addresses poison and retain. No prefix is read before proving membership. */
int lsf_factory_packet_birth(const void *, unsigned int, struct lsf_factory_blob *);
int lsf_factory_packet_head_current(const void *, unsigned long,
                                     struct lsf_factory_blob *);
struct sk_buff *lsf_prepaid_packet_skb_new(struct lsf_factory_blob, unsigned int);
struct sk_buff *lsf_prepaid_packet_alloc_sock(struct sock *, unsigned int);
bool lsf_prepaid_packet_linear(const struct sk_buff *, struct lsf_factory_blob);
bool lsf_prepaid_packet_for_sock(const struct sk_buff *, struct sock *);

/* Payload capacity is a source-selected constructor bound, not extra budget.
 * Header, full aligned head/shared-info and every clone still consume the same
 * original context and 256 records BEFORE publication. Unsupported shapes
 * fail closed; the selected complete consumer remains NULL. */
#define LSF_PACKET_LINEAR_BYTES 2048u
#endif
