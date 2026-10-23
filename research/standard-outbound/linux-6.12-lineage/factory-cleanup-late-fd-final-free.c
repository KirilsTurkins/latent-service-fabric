/* SPDX-License-Identifier: GPL-2.0-only */
/* Included after the original Root collector. The real final VFS release
 * transfers existing custody, never a file pointer or a new allocation owner. */
static int lsf_cleanup_root_fd_handoff_locked(struct file *file)
{
    unsigned long flags;
    int result = 0;
    lockdep_assert_held(&factory_lock);
    spin_lock_irqsave(&pool_lock, flags);
    if (!file || file->private_data != &factory || factory.opened != 1u ||
        file->f_cred != factory.cred || !factory.pages || !factory.device ||
        !factory.mm || !factory.tgid || !factory.cred || !factory.net ||
        !factory.pool.initialized)
        goto out;
    /* All FD-specific close/cache/payload accesses have finished. Keep the
     * same page/actor references in factory until exact physical collection.
     * Nonzero opened still refuses another birth; there is no reset/reopen. */
    factory.opened = 2u;
    file->private_data = NULL;
    result = 1;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Cheap scalar notification, not a lifetime or physical-return certificate.
 * Called by original kthreadd with or without its creation lock; no factory
 * mutex, waits, pointers escaping the lock, or new ownership records. */
static int lsf_cleanup_root_pending_locked(void)
{
    return factory.opened == 2u && factory.pages && factory.device &&
        !READ_ONCE(factory.uncertain) && !factory.pool.poisoned &&
        factory.device->cleanup_request_returned == 1u;
}

int lsf_factory_cleanup_root_pending(void)
{
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_cleanup_root_pending_locked();
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void lsf_factory_cleanup_root_drain(void)
{
    struct lsf_cleanup_root_release release = {0};
    unsigned long flags;
    int pending;
    if (current != kthreadd_task || in_interrupt() || irqs_disabled())
        return;
    /* The dispatching kthreadd dropped kthread_create_lock. Serialize with
     * the actual FD fast collector before checking the original bank again. */
    mutex_lock(&factory_lock);
    spin_lock_irqsave(&pool_lock, flags);
    pending = lsf_cleanup_root_pending_locked();
    spin_unlock_irqrestore(&pool_lock, flags);
    if (pending && !lsf_cleanup_root_release_take_locked(&release)) {
        spin_lock_irqsave(&pool_lock, flags);
        /* A disappeared owner is a completed competing take, never poison.
         * An actually returned Request with retained but unqualified terminal
         * metadata gets ONE attempt and original sticky quarantine, not an
         * always-true pending loop or a timeout-based physical refund. */
        if (lsf_cleanup_root_pending_locked()) {
            factory.pool.poisoned = 1;
            WRITE_ONCE(factory.uncertain, 1);
        }
        spin_unlock_irqrestore(&pool_lock, flags);
    }
    mutex_unlock(&factory_lock);
    lsf_cleanup_root_release_physical(release);
}
