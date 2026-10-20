/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef LSF_STREAM_PHYSICAL_HOOKS_H
#define LSF_STREAM_PHYSICAL_HOOKS_H
#include <net/lsf_stream_lineage_core.h>
#ifdef CONFIG_LSF_STREAM_LINEAGE
void lsf_stream_allocator_returned(struct lsf_token token);
#else
static inline void lsf_stream_allocator_returned(struct lsf_token token)
{
    (void)token;
}
#endif
#endif
