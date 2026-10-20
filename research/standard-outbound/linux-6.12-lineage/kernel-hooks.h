/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef LSF_STREAM_KERNEL_HOOKS_H
#define LSF_STREAM_KERNEL_HOOKS_H
#include <net/lsf_stream_lineage_core.h>

/* Internal kernel linkage only: no EXPORT_SYMBOL, ioctl, map or userspace ABI. */
#ifdef CONFIG_LSF_STREAM_LINEAGE
struct lsf_token lsf_stream_before_free(unsigned int kind, const void *address,
                                       lsf_u64 cookie);
void lsf_stream_after_free(struct lsf_token token);
void lsf_stream_unproved_fragment(const void *address);
#else
static inline struct lsf_token lsf_stream_before_free(unsigned int kind,
                                                      const void *address,
                                                      lsf_u64 cookie)
{
    (void)kind;
    (void)address;
    (void)cookie;
    return lsf_empty_token();
}
static inline void lsf_stream_after_free(struct lsf_token token) { (void)token; }
static inline void lsf_stream_unproved_fragment(const void *address) { (void)address; }
#endif
#endif
