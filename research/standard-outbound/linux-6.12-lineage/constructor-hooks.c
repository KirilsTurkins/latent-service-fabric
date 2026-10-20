/* SPDX-License-Identifier: GPL-2.0-only */
/* Included only by the uninstalled private lineage translation unit. */
#include <net/lsf_stream_constructors.h>

int lsf_stream_constructor_prepare(unsigned int constructor, const void *parent,
                                   unsigned int size, unsigned int allocation_flags,
                                   unsigned int path_flags, int node,
                                   struct lsf_bundle *bundle)
{
    /* No trusted factory context, running-kernel layout or socket-cookie
     * handoff has been authenticated. In the candidate CONFIG this is a
     * mandatory refusal BEFORE any allocator, not an ordinary network path.
     * Do not substitute proto->obj_size, wire size or user assertions here.
     * A future binder must select the complete prepaid scope and disjoint
     * physical plan, then use lsf_bundle_prepare under lsf_stream_lock. */
    (void)constructor;
    (void)parent;
    (void)size;
    (void)allocation_flags;
    (void)path_flags;
    (void)node;
    (void)bundle;
    return 0;
}

void lsf_stream_constructor_observed(struct lsf_bundle *bundle, unsigned int index,
                                     const void *address, lsf_u64 cookie)
{
    unsigned long flags;
    spin_lock_irqsave(&lsf_stream_lock, flags);
    (void)lsf_bundle_commit(&lsf_stream_state, bundle, index,
                            (unsigned long)address, cookie);
    spin_unlock_irqrestore(&lsf_stream_lock, flags);
}

void lsf_stream_constructor_uncertain(struct lsf_bundle *bundle)
{
    unsigned long flags;
    spin_lock_irqsave(&lsf_stream_lock, flags);
    lsf_bundle_uncertain(&lsf_stream_state, bundle);
    spin_unlock_irqrestore(&lsf_stream_lock, flags);
}
