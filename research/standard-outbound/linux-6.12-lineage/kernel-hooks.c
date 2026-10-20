/* SPDX-License-Identifier: GPL-2.0-only */
/* Uninstalled candidate. A complete qualified allocation/factory binding and
 * authenticated kernel build are still absent. Nothing emits a certificate. */
#include <linux/spinlock.h>
#include <net/lsf_stream_lineage.h>

static DEFINE_SPINLOCK(lsf_stream_lock);
static struct lsf_lineage lsf_stream_state = { .next_owner = 1, .next_allocation = 1 };

struct lsf_token lsf_stream_before_free(unsigned int kind, const void *address,
                                       lsf_u64 cookie)
{
    struct lsf_token token;
    unsigned long flags;
    spin_lock_irqsave(&lsf_stream_lock, flags);
    token = lsf_capture_free(&lsf_stream_state, kind, (unsigned long)address, cookie);
    spin_unlock_irqrestore(&lsf_stream_lock, flags);
    return token;
}

void lsf_stream_after_free(struct lsf_token token)
{
    unsigned long flags;
    spin_lock_irqsave(&lsf_stream_lock, flags);
    (void)lsf_post_free(&lsf_stream_state, token);
    spin_unlock_irqrestore(&lsf_stream_lock, flags);
}

void lsf_stream_unproved_fragment(const void *address)
{
    unsigned long flags;
    spin_lock_irqsave(&lsf_stream_lock, flags);
    lsf_unproved_allocation(&lsf_stream_state, (unsigned long)address);
    spin_unlock_irqrestore(&lsf_stream_lock, flags);
}
