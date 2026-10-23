/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual maintained create/complete ownership handshake, using the existing
 * paid request and exact known provider entry. No heap request/name exists. */
struct task_struct *lsf_prepaid_cleanup_provider_task_create(
    struct lsf_cleanup_task_source source, void *worker)
{
    DECLARE_COMPLETION_ONSTACK(done);
    struct lsf_cleanup_request *owned;
    struct task_struct *task;
    void *address;
    if (!lsf_factory_cleanup_provider_open_request(source, worker, &address))
        return ERR_PTR(-EOPNOTSUPP);
    owned = address;
    owned->source = source;
    memcpy(owned->name, "lsf/firmware-cleanup", sizeof(owned->name));
    owned->create.full_name = owned->name;
    owned->create.threadfn = lsf_prepaid_cleanup_provider_worker_thread;
    owned->create.data = worker;
    owned->create.node = NUMA_NO_NODE;
    owned->create.done = &done;
    spin_lock(&kthread_create_lock);
    if (lsf_cleanup_pending) {
        spin_unlock(&kthread_create_lock);
        lsf_factory_cleanup_stack_poison(source);
        return ERR_PTR(-EBUSY);
    }
    WRITE_ONCE(lsf_cleanup_pending, owned);
    spin_unlock(&kthread_create_lock);
    wake_up_process(kthreadd_task);
    if (unlikely(wait_for_completion_killable(&done))) {
        if (xchg(&owned->create.done, NULL)) {
            lsf_factory_cleanup_request_put(source, LSF_CLEANUP_REQUEST_OPENER);
            return ERR_PTR(-EINTR);
        }
        wait_for_completion(&done);
    }
    task = owned->create.result;
    /* LAST request access precedes the real opener borrow release. Successful
     * provider Task remains in its original entry sleep until WQ binds it. */
    lsf_factory_cleanup_request_put(source, LSF_CLEANUP_REQUEST_OPENER);
    return task;
}
