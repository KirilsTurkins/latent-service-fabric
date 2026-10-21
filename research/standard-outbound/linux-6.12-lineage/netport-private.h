/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef LSF_STREAM_NETPORT_PRIVATE_H
#define LSF_STREAM_NETPORT_PRIVATE_H
#include <linux/types.h>
struct lsf_factory_context;
struct lsf_factory_blob;
int lsf_prepaid_netport_sid(u8, u16, u32 *, const struct lsf_factory_blob *);
void lsf_prepaid_netport_drain(struct lsf_factory_context *);
#endif
