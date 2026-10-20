/* SPDX-License-Identifier: GPL-2.0-only */
/* Private uninstalled constructor seam. No trusted live context exists yet. */
#ifndef LSF_STREAM_CONSTRUCTOR_HOOKS_H
#define LSF_STREAM_CONSTRUCTOR_HOOKS_H
#include <net/lsf_stream_admission.h>

#ifdef CONFIG_LSF_STREAM_LINEAGE
int lsf_stream_constructor_prepare(unsigned int constructor, const void *parent,
                                   unsigned int size, unsigned int allocation_flags,
                                   unsigned int path_flags, int node,
                                   struct lsf_bundle *bundle);
void lsf_stream_constructor_observed(struct lsf_bundle *bundle, unsigned int index,
                                     const void *address, lsf_u64 cookie);
void lsf_stream_constructor_uncertain(struct lsf_bundle *bundle);
#else
static inline int lsf_stream_constructor_prepare(unsigned int constructor,
                                                  const void *parent,
                                                  unsigned int size,
                                                  unsigned int allocation_flags,
                                                  unsigned int path_flags, int node,
                                                  struct lsf_bundle *bundle)
{
    (void)constructor;
    (void)parent;
    (void)size;
    (void)allocation_flags;
    (void)path_flags;
    (void)node;
    (void)bundle;
    return 1;
}
static inline void lsf_stream_constructor_observed(struct lsf_bundle *bundle,
                                                   unsigned int index,
                                                   const void *address,
                                                   lsf_u64 cookie)
{
    (void)bundle;
    (void)index;
    (void)address;
    (void)cookie;
}
static inline void lsf_stream_constructor_uncertain(struct lsf_bundle *bundle)
{
    (void)bundle;
}
#endif
#endif
