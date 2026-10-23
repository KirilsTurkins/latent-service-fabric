/* SPDX-License-Identifier: GPL-2.0-only */
/* Both the actual constructor and permission-checked set_task_ioprio use this
 * existing Task family. A known bank target can never borrow ordinary SLUB. */
int lsf_factory_cleanup_io_reserve(const struct task_struct *target, unsigned long bytes,
    unsigned long alignment, void **address)
{
    struct lsf_cleanup_task_source source;
    struct task_struct *task;
    struct lsf_prepaid_ticket ticket;
    unsigned long flags, base, at = (unsigned long)target, actual_bytes, actual_alignment;
    lsf_u64 offset;
    int result = 0, geometry = lsf_prepaid_cleanup_io_geometry(&actual_bytes, &actual_alignment);
    if (!address)
        return -1;
    *address = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.pages)
        goto out;
    base = (unsigned long)page_address(factory.pages);
    if (at < base || at - base >= LSF_BACKING_BYTES)
        goto out;
    result = -1;
    if (in_interrupt() || !lsf_cleanup_child_source_locked(&source, &task) || target != task ||
        geometry || bytes != actual_bytes || alignment != actual_alignment || !bytes ||
        bytes > LSF_FACTORY_INFRA_BYTES || !alignment || alignment > 64u ||
        (alignment & (alignment - 1u)) ||
        (factory.device->cleanup_lifecycle != LSF_CLEANUP_METADATA &&
         factory.device->cleanup_lifecycle != LSF_CLEANUP_PUBLISHED) ||
        factory.device->cleanup_final_phase != LSF_CLEANUP_FINAL_NONE ||
        !refcount_read(&task->usage))
        goto poison;
    result = 1; /* Recognized allocation failure MUST NOT enter normal SLUB. */
    if (factory.device->cleanup_child_attempted & (1u << LSF_CLEANUP_IO_CONTEXT))
        goto out;
    factory.device->cleanup_child_attempted |= 1u << LSF_CLEANUP_IO_CONTEXT;
    if (!lsf_device_allocate(&factory.pool, source.owner, bytes, LSF_DEVICE_CLEANUP_IO_CONTEXT,
            source.task, &ticket, &offset))
        goto out;
    if (((unsigned long)page_address(factory.pages) + offset) & (alignment - 1u))
        goto poison;
    *address = (char *)page_address(factory.pages) + offset;
    memset(*address, 0, bytes); /* Original charge and parent precede first write. */
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
