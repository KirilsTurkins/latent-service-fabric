/* SPDX-License-Identifier: GPL-2.0-only */
/* Included only in the same uninstalled private lineage translation unit. */
#include <net/lsf_stream_physical_core.h>
#include <net/lsf_stream_physical.h>

void lsf_stream_allocator_returned(struct lsf_token token)
{
    unsigned long flags;
    spin_lock_irqsave(&lsf_stream_lock, flags);
    (void)lsf_physical_slot_return(&lsf_stream_state, token);
    spin_unlock_irqrestore(&lsf_stream_lock, flags);
}
