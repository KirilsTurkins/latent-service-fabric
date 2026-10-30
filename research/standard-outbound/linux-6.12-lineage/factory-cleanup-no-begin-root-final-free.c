/* SPDX-License-Identifier: GPL-2.0-only */
/* Initial successful-open Root only. BEGIN/failed births are not admitted.
 * Included after the original no-application guard; original pool_lock held.
 * This predicate supplies no ownership independent of the common collector. */
static int lsf_cleanup_root_no_begin_locked(void)
{
    struct lsf_factory_device_state *device = factory.device;
    struct lsf_prepaid_context *owner;
    struct lsf_prepaid_view *record;
    lsf_u64 rounded = (sizeof(*device) + 63u) & ~(lsf_u64)63u;
    unsigned int i, word;
    lockdep_assert_held(&pool_lock);
    if (!factory.pages || !device || factory.pool.initialized != 1u ||
        factory.pool.stopped != 1u || factory.pool.next_generation != 3u ||
        !lsf_cleanup_root_no_application_locked() ||
        device->key.slot != LSF_DEVICE_OWNER_SLOT || device->key.generation != 1u ||
        device->root.slot != 1u || device->root.generation != 2u ||
        device->bootstrap_state != LSF_FACTORY_BOOTSTRAP_CLOSED ||
        device->bootstrap_expires_ns || device->bootstrap_busy || device->bootstrap_error ||
        device->pci_attempted || device->constructor_active || device->constructor_task ||
        device->core_tail_task || device->firmware.slot || device->firmware.generation ||
        device->cleanup_request.slot || device->cleanup_request.generation ||
        device->cleanup_task.slot || device->cleanup_task.generation ||
        device->cleanup_attempted || device->cleanup_task_claimed ||
        device->cleanup_stack.slot || device->cleanup_stack.generation ||
        device->cleanup_stack_attempted || device->cleanup_kthread.slot ||
        device->cleanup_kthread.generation || device->cleanup_kthread_attempted ||
        device->cleanup_lifecycle || device->cleanup_retire_task ||
        device->cleanup_entry_started || device->cleanup_worker_associated ||
        device->cleanup_request_users || device->cleanup_worker_stop ||
        device->cleanup_request_returned || device->cleanup_child_attempted ||
        device->cleanup_final_phase || device->cleanup_vm_prepared ||
        device->cleanup_physical_role || device->cleanup_operation_active ||
        device->cleanup_provider_storage_attempted || device->cleanup_provider_pool_destructed ||
        device->cleanup_provider_submitted || device->cleanup_provider_task_failed ||
        device->cleanup_provider_close_requested || device->cleanup_provider_control_readers ||
        device->cleanup_provider_control_retiring || device->cleanup_provider_worker.slot ||
        device->cleanup_provider_worker.generation || device->cleanup_provider_pool.slot ||
        device->cleanup_provider_pool.generation || device->cleanup_operation_work ||
        device->cleanup_operation_function)
        return 0;
    owner = &factory.pool.contexts[LSF_DEVICE_OWNER_SLOT];
    if (owner->generation != 1u || owner->cursor != rounded || owner->live != 1u ||
        owner->continuations || owner->closed != 1u || owner->poisoned)
        return 0;
    for (word = 0; word < 8; ++word)
        if (owner->scope.identity[word])
            return 0;
    /* Other63 owners, including all historical scope/cursor/generation fields,
     * were checked by the original no-application guard above. */
    record = &factory.pool.records[1];
    if (record->phase != LSF_PREPAID_LIVE || record->generation != 2u ||
        record->owner != LSF_DEVICE_OWNER_SLOT || record->owner_generation != 1u ||
        record->kind != LSF_DEVICE_ROOT || record->deferred != LSF_PREPAID_PUBLISHED ||
        record->offset != LSF_FACTORY_INFRA_OFFSET || record->bytes != rounded ||
        record->cache_bucket || record->cache_anchor ||
        !lsf_route_cache_empty(&record->route_cache) ||
        record->security_cache_location || record->security_cache_identity ||
        device != (void *)((char *)page_address(factory.pages) + record->offset))
        return 0;
    /* No RETURNED history is accepted. Initial generation3 plus canonical
     * EMPTY slots proves that no child/application birth ever took place. */
    for (i = 0; i < LSF_ALLOCATION_SLOTS; ++i) {
        if (i == 1u)
            continue;
        record = &factory.pool.records[i];
        if (record->phase != (i == 0 ? LSF_PREPAID_LIVE : LSF_PREPAID_EMPTY) ||
            record->bytes != (i == 0 ? LSF_BACKING_BYTES : 0u) ||
            record->generation || record->owner_generation || record->offset ||
            record->owner || record->kind || record->deferred ||
            record->cache_bucket || record->cache_anchor ||
            !lsf_route_cache_empty(&record->route_cache) ||
            record->security_cache_location || record->security_cache_identity)
            return 0;
    }
    return lsf_prepaid_cleanup_irq_unborn();
}
