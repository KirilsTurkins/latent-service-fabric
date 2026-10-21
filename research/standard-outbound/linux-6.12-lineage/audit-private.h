/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef LSF_STREAM_AUDIT_PRIVATE_H
#define LSF_STREAM_AUDIT_PRIVATE_H
#include <linux/gfp_types.h>
#include <net/lsf_stream_sidcache_private.h>
#include "factory-private.h"
struct audit_buffer;
struct audit_context;
struct common_audit_data;
struct audit_buffer *lsf_prepaid_audit_log_start(struct audit_context *, gfp_t,
    int, const struct lsf_factory_blob *, int *);
int lsf_prepaid_audit_log_end(struct audit_buffer *, int);
int lsf_prepaid_common_lsm_audit(struct common_audit_data *,
    void (*)(struct audit_buffer *, void *),
    int (*)(struct audit_buffer *, void *, const struct lsf_factory_blob *),
    const struct lsf_factory_blob *);
#endif
