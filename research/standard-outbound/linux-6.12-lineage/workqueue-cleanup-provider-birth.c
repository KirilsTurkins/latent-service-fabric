/* SPDX-License-Identifier: GPL-2.0-only */
/* Existing global IDR nodes remain original provider infrastructure. This
 * route may consume an already installed free cell, but never grows the IDR,
 * borrows the per-CPU preload cache, or attaches a Root node to ordinary IDs. */
int lsf_prepaid_cleanup_provider_pool_idr_current(struct lsf_cleanup_task_source source,
    const void *root, const void *pool)
{
    if (root != &worker_pool_idr.idr_rt ||
        !lsf_factory_cleanup_provider_birth_current(source, pool))
        return 0;
    lockdep_assert_held(&wq_pool_mutex);
    return 1;
}

static int lsf_provider_pool_assign_id(struct lsf_cleanup_task_source source,
    struct worker_pool *pool)
{
    int ret;
    if (!lsf_prepaid_cleanup_provider_pool_idr_current(source,
            &worker_pool_idr.idr_rt, pool))
        return -EOPNOTSUPP;
    /* The caller already holds the REAL original IDR writer mutex. */
    if (pool->id != -1)
        return -EOPNOTSUPP;
    ret = lsf_prepaid_cleanup_provider_pool_idr_alloc(source, &worker_pool_idr,
        pool, 0, WORK_OFFQ_POOL_NONE, GFP_KERNEL);
    if (ret >= 0) {
        pool->id = ret;
        return 0;
    }
    return ret;
}
