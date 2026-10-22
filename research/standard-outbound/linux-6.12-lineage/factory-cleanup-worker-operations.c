/* SPDX-License-Identifier: GPL-2.0-only */
/* Operation denial only; not allocation admission or an executor certificate. */
int lsf_factory_cleanup_worker_operation_current(void)
{
    struct lsf_cleanup_task_source source;
    unsigned long flags, base, address = (unsigned long)current;
    int result = 0;
    /* Interrupt/NMI/serving-softirq execution has its own actual producer.
     * It must not inherit this Task's origin merely because it interrupted it. */
    if (!in_task())
        return 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.pages)
        goto out;
    base = (unsigned long)page_address(factory.pages);
    if (address < base || address - base >= LSF_BACKING_BYTES)
        goto out;
    result = -EIO; /* Bank range is only a candidate, NEVER origin proof. */
    if (!factory.device)
        goto poison;
    source = (struct lsf_cleanup_task_source){factory.device->key, factory.device->root,
        factory.device->cleanup_request, factory.device->cleanup_task};
    /* Original full generations, parents and born current address precede
     * even the first current Task field. Closed admission preserves identity. */
    if (!lsf_cleanup_lifecycle_identity_locked(source, current) ||
        factory.device->cleanup_lifecycle != LSF_CLEANUP_PUBLISHED ||
        factory.device->cleanup_final_phase != LSF_CLEANUP_FINAL_NONE ||
        !refcount_read(&current->usage) || !(current->flags & PF_KTHREAD))
        goto poison;
    result = 1;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
