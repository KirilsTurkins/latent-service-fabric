/* SPDX-License-Identifier: GPL-2.0-only */
/* Allocation admission, deliberately stricter than held physical identity. */
int lsf_factory_cleanup_provider_birth_current(struct lsf_cleanup_task_source source,
    const void *pool)
{
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_factory_cleanup_task_source_locked(source) || factory.pool.stopped ||
        factory.pool.poisoned || factory.pool.contexts[source.owner.slot].closed ||
        factory.device->cleanup_task_claimed || !factory.device->cleanup_provider_storage_attempted ||
        factory.device->cleanup_lifecycle != LSF_CLEANUP_UNINITIALIZED ||
        current->mm != factory.mm || task_tgid(current) != factory.tgid ||
        current_cred() != factory.cred || !current->nsproxy || current->nsproxy->net_ns != factory.net)
        goto out;
    result = pool && lsf_cleanup_provider_part_locked(source, LSF_PROVIDER_POOL, pool, 1);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
