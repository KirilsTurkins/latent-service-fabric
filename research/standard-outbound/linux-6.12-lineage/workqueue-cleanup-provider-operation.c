/* SPDX-License-Identifier: GPL-2.0-only */
/* Included after actual workqueue worker/pool definitions. No pool locking,
 * allocation, producer certificate or arbitrary kthread_data inference. */
int lsf_prepaid_cleanup_provider_geometry(unsigned long *worker_bytes,
    unsigned long *worker_alignment, unsigned long *pool_bytes,
    unsigned long *pool_alignment)
{
    if (!worker_bytes || !worker_alignment || !pool_bytes || !pool_alignment)
        return -EINVAL;
    *worker_bytes = sizeof(struct worker);
    *worker_alignment = __alignof__(struct worker);
    *pool_bytes = sizeof(struct worker_pool);
    *pool_alignment = __alignof__(struct worker_pool);
    return 0;
}

int lsf_prepaid_cleanup_provider_snapshot(struct lsf_cleanup_task_source source,
    struct work_struct **work, work_func_t *function)
{
    struct worker *worker;
    void *actual_worker, *actual_pool;
    if (!work || !function || !in_task())
        return -EIO;
    *work = NULL;
    *function = NULL;
    /* Full born Task and actual typed worker/pool records BEFORE fields. */
    if (lsf_factory_cleanup_provider_snapshot_source(source,
            &actual_worker, &actual_pool) != 1)
        return -EIO;
    worker = actual_worker;
    if (READ_ONCE(worker->task) != current || READ_ONCE(worker->pool) != actual_pool)
        return -EIO;
    /* K fields: this SAME Task sets them before dispatch, then clears them
     * after callback return. No interrupt or cross-Task observer is admitted. */
    *work = READ_ONCE(worker->current_work);
    *function = READ_ONCE(worker->current_func);
    return *work && *function ? 0 : -EIO;
}
