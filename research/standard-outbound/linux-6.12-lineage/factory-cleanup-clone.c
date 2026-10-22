/* SPDX-License-Identifier: GPL-2.0-only */
/* An already-born original request is authenticated before request fields.
 * This cannot admit a supplied pointer, claim a task or mint another owner. */
int lsf_factory_cleanup_constructor_request(const void *address, unsigned long bytes,
    struct lsf_cleanup_task_source *source)
{
    struct lsf_cleanup_task_source actual;
    struct lsf_prepaid_view *request;
    unsigned long flags, actual_bytes;
    int result = 0;
    if (!source || current != kthreadd_task || in_interrupt() || irqs_disabled() ||
        lsf_prepaid_cleanup_request_geometry(&actual_bytes) || bytes != actual_bytes)
        return 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.device)
        goto out;
    actual = (struct lsf_cleanup_task_source){factory.device->key, factory.device->root,
        factory.device->cleanup_request, factory.device->cleanup_task};
    if (!lsf_factory_cleanup_task_source_locked(actual) || factory.pool.stopped ||
        factory.pool.contexts[actual.owner.slot].closed || factory.device->cleanup_task_claimed ||
        factory.device->cleanup_lifecycle != LSF_CLEANUP_UNINITIALIZED)
        goto out;
    request = lsf_device_record(&factory.pool, actual.owner, actual.request, LSF_DEVICE_CLEANUP_REQUEST);
    if (!request || request->bytes < bytes ||
        address != (const char *)page_address(factory.pages) + request->offset)
        goto poison;
    *source = actual;
    result = 1;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
