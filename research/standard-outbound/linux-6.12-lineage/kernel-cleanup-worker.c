/* SPDX-License-Identifier: GPL-2.0-only */
/* Included after the actual __kthread_create_worker definition. This prefix
 * creates NO worker thread: the owned task copy refuses before guarded-stack
 * allocation. Ordinary create APIs, pool topology and ACPI queues are exact. */
struct lsf_cleanup_request {
    struct kthread_create_info create;
    struct kthread_worker worker;
    struct lock_class_key lock_key;
    struct lsf_cleanup_task_source source;
    char name[sizeof("lsf/firmware-cleanup")];
};
static_assert(sizeof(lsf_cleanup_pending) == sizeof(void *));

static void lsf_cleanup_create_kthread(struct lsf_cleanup_request *owned)
{
    struct completion *done;
    struct task_struct *task;
#ifdef CONFIG_NUMA
    /* Same kthreadd-local preference assignment as original create_kthread;
     * this is not an assertion about the pre-existing bank's physical node. */
    current->pref_node_fork = owned->create.node;
#endif
    /* The fixed pending slot handed this exact still-LIVE request to the
     * actual kthreadd. No caller task pointer or retrospective origin lookup.
     * Its child claim revalidates the original root/request/task generations. */
    task = lsf_prepaid_cleanup_dup_task_struct(owned->source, owned->create.node);
    done = xchg(&owned->create.done, NULL);
    owned->create.result = task;
    /* Keep the entire request (including embedded worker/name) charged even
     * when its opener is interrupted. No thread or reusable readiness escapes.
     * complete() is the LAST access: the original borrowed completion may die
     * immediately after the opener wakes. No pool lock spans this callback. */
    if (done)
        complete(done);
}

int lsf_prepaid_cleanup_worker_create(void)
{
    DECLARE_COMPLETION_ONSTACK(done);
    struct lsf_cleanup_request *owned;
    struct lsf_cleanup_task_source source;
    struct task_struct *task;
    unsigned long task_bytes, alignment;
    void *address;
    int error;
    /* Do not silently omit enabled allocation/lock instrumentation. Its
     * private creation path is an explicit remaining profile boundary. */
    if (IS_ENABLED(CONFIG_DEBUG_LOCK_ALLOC))
        return -EOPNOTSUPP;
    error = lsf_prepaid_cleanup_task_geometry(&task_bytes, &alignment);
    if (error)
        return error;
    error = lsf_factory_cleanup_task_reserve(sizeof(*owned), task_bytes, alignment,
        &source, &address);
    if (error)
        return error;
    owned = address;
    owned->source = source;
    __kthread_init_worker(&owned->worker, "lsf/firmware-cleanup", &owned->lock_key);
    memcpy(owned->name, "lsf/firmware-cleanup", sizeof(owned->name));
    owned->create.full_name = owned->name;
    owned->create.threadfn = kthread_worker_fn;
    owned->create.data = &owned->worker;
    owned->create.node = NUMA_NO_NODE;
    owned->create.done = &done;
    spin_lock(&kthread_create_lock);
    if (lsf_cleanup_pending) {
        spin_unlock(&kthread_create_lock);
        return -EBUSY;
    }
    WRITE_ONCE(lsf_cleanup_pending, owned);
    spin_unlock(&kthread_create_lock);
    wake_up_process(kthreadd_task);
    /* Preserve the actual original create/complete ownership handshake.
     * Interrupting the opener never releases or reuses pending request memory. */
    if (unlikely(wait_for_completion_killable(&done))) {
        if (xchg(&owned->create.done, NULL))
            return -EINTR;
        wait_for_completion(&done);
    }
    task = owned->create.result;
    if (IS_ERR(task))
        return PTR_ERR(task);
    /* The current constructor can ONLY return an error before stack birth.
     * An unexpected task is uncertainty, not permission to run or refund it. */
    return -EIO;
}
