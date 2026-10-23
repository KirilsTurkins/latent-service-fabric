/* SPDX-License-Identifier: GPL-2.0-only */
/* Same real pending slot/creator handshake, but no borrowed stack completion.
 * This source-only API consumes the one pre-existing caller remaining budget. */
struct task_struct *lsf_prepaid_cleanup_provider_task_create(
    struct lsf_cleanup_task_source source, void *worker)
{
    struct completion *done;
    struct lsf_cleanup_request *owned;
    struct task_struct *task;
    void *address, *control;
    unsigned long remaining;
    long waited;
    int error, claimed_late;
    control = lsf_prepaid_cleanup_provider_birth_wait_get(source, worker, &done, &remaining);
    if (!control)
        return ERR_PTR(-EOPNOTSUPP);
    if (!remaining) {
        lsf_prepaid_cleanup_provider_birth_wait_put(control, 0);
        return ERR_PTR(-ETIMEDOUT); /* Request was never opened or submitted. */
    }
    if (!lsf_factory_cleanup_provider_open_request(source, worker, &address)) {
        lsf_prepaid_cleanup_provider_birth_wait_put(control, 0);
        return ERR_PTR(-EOPNOTSUPP);
    }
    owned = address;
    owned->source = source;
    memcpy(owned->name, "lsf/firmware-cleanup", sizeof(owned->name));
    owned->create.full_name = owned->name;
    owned->create.threadfn = lsf_prepaid_cleanup_provider_worker_thread;
    owned->create.data = worker;
    owned->create.node = NUMA_NO_NODE;
    owned->create.done = done;
    spin_lock(&kthread_create_lock);
    if (lsf_cleanup_pending) {
        spin_unlock(&kthread_create_lock);
        lsf_factory_cleanup_stack_poison(source);
        lsf_prepaid_cleanup_provider_birth_wait_put(control, 1);
        return ERR_PTR(-EBUSY); /* Unknown request state retains both borrows. */
    }
    if (!lsf_factory_cleanup_provider_submit(source, worker)) {
        spin_unlock(&kthread_create_lock);
        lsf_prepaid_cleanup_provider_birth_wait_put(control, 1);
        return ERR_PTR(-EOPNOTSUPP);
    }
    WRITE_ONCE(lsf_cleanup_pending, owned);
    spin_unlock(&kthread_create_lock);
    wake_up_process(kthreadd_task);
    remaining = lsf_prepaid_cleanup_provider_birth_remaining(control);
    waited = remaining ? wait_for_completion_killable_timeout(done, remaining) : 0;
    if (waited <= 0 || !lsf_prepaid_cleanup_provider_birth_remaining(control)) {
        error = waited < 0 ? (int)waited : -ETIMEDOUT;
        claimed_late = !xchg(&owned->create.done, NULL);
        lsf_factory_cleanup_provider_task_failed(source);
        /* Quarantine BEFORE the opener put if a real completer already took
         * the pointer. complete() may still access its internal wait lock. */
        if (claimed_late)
            lsf_prepaid_cleanup_provider_birth_wait_put(control, 1);
        lsf_factory_cleanup_request_put(source, LSF_CLEANUP_REQUEST_OPENER);
        if (!claimed_late)
            lsf_prepaid_cleanup_provider_birth_wait_put(control, 0);
        return ERR_PTR(error);
    }
    task = owned->create.result;
    if (IS_ERR(task))
        lsf_factory_cleanup_provider_task_failed(source);
    lsf_factory_cleanup_request_put(source, LSF_CLEANUP_REQUEST_OPENER);
    lsf_prepaid_cleanup_provider_birth_wait_put(control, 0);
    return task;
}
