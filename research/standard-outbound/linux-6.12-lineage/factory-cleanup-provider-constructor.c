/* SPDX-License-Identifier: GPL-2.0-only */
int lsf_factory_cleanup_provider_waiter_current(struct lsf_cleanup_task_source source)
{
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_provider_original_opener_locked(source) && !factory.pool.stopped &&
        !factory.pool.poisoned && !READ_ONCE(factory.uncertain) &&
        !factory.device->cleanup_provider_close_requested;
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void lsf_factory_cleanup_provider_waiter_cancel(struct lsf_cleanup_task_source source)
{
    unsigned long flags;
    int matching;
    spin_lock_irqsave(&pool_lock, flags);
    matching = lsf_provider_original_opener_locked(source);
    if (matching)
        factory.device->cleanup_provider_close_requested = 1u;
    spin_unlock_irqrestore(&pool_lock, flags);
    if (matching) {
        /* The caller still owns the real Control reader borrow. The original
         * Root cannot disappear/rebind between this fence and admission close.
         * These request retirement; no destructor, put or refund is certified. */
        lsf_cleanup_admission_close();
        lsf_prepaid_cleanup_provider_retirement_kick();
    }
}
