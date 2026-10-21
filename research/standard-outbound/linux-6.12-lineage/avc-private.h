/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef LSF_STREAM_AVC_PRIVATE_H
#define LSF_STREAM_AVC_PRIVATE_H
#include <linux/types.h>
struct av_decision;
struct common_audit_data;
struct lsf_factory_blob;
struct lsf_factory_context;
int lsf_prepaid_avc_has_perm(u32, u32, u16, u32,
    struct common_audit_data *, const struct lsf_factory_blob *);
void lsf_prepaid_avc_drain(struct lsf_factory_context *);
/* Implemented by the separately derived mandatory audit producer. No silent
 * no-op, generic audit fallback or success stub can satisfy this declaration. */
int lsf_prepaid_avc_audit(u32, u32, u16, u32, struct av_decision *, int,
    struct common_audit_data *, const struct lsf_factory_blob *);
#endif
