/* SPDX-License-Identifier: GPL-2.0-only */
/* Included after the maintained paid pool/worker definitions. */
static void lsf_provider_retire_handoff(struct kthread_work *work);

int lsf_prepaid_cleanup_provider_queue_available(void)
{
    /* These are original permanent boot providers. wq_online only transitions
     * false->true; no new Root adopts their Tasks, queues or physical frames. */
    return wq_online && pwq_release_worker && lsf_prepaid_acpi_reference_queue_ready();
}

static void lsf_provider_unlinked_barrier(struct kthread_work *work)
{
    struct lsf_cleanup_provider_control *control;
    control = lsf_factory_cleanup_provider_control_current(
        container_of(work, struct lsf_cleanup_provider_control, release_barrier));
    if (control)
        complete_all(&control->unlinked_released); /* LAST Control field access. */
}

int lsf_prepaid_cleanup_provider_retirement_kick_held(void *candidate)
{
    struct lsf_cleanup_provider_control *control = candidate;
    int phase;
    if (READ_ONCE(control->preparing))
        return 1;
    for (;;) {
        phase = atomic_read(&control->retire_pending);
        if (phase == 2 || phase == 3)
            return 1;
        if (phase == 1) {
            if (atomic_cmpxchg(&control->retire_pending, 1, 3) == 1)
                return 1; /* Actual event during current callback, not a requeue. */
            continue;
        }
        if (phase != 0) {
            return 0;
        }
        if (atomic_cmpxchg(&control->retire_pending, 0, 1) != 0)
            continue;
        return kthread_queue_work(pwq_release_worker, &control->retire);
    }
}

void lsf_prepaid_cleanup_provider_retirement_kick(void)
{
    struct lsf_cleanup_provider_control *control;
    control = lsf_factory_cleanup_provider_control_get(NULL);
    if (!control)
        return;
    if (!lsf_prepaid_cleanup_provider_retirement_kick_held(control))
        lsf_factory_cleanup_provider_hold(control->source);
    lsf_factory_cleanup_provider_control_put(control); /* LAST Control access. */
}

void lsf_prepaid_cleanup_provider_queue_detached(const void *pwq)
{
    struct lsf_cleanup_provider_control *control;
    control = lsf_factory_cleanup_provider_control_current(NULL);
    if (control && control->private == pwq && control->phase == LSF_PROVIDER_QUEUE_RETURNING)
        WRITE_ONCE(control->wq, NULL);
    /* Real private PWQ refcnt0 means no active/scheduled work remains. Its
     * original release removes the list node before this final WQ access seal,
     * and only afterwards may original last-PWQ cleanup free the WQ. */
}

static void lsf_provider_retire_handoff(struct kthread_work *work)
{
    struct lsf_cleanup_provider_control *control;
    struct lsf_cleanup_task_source source;
    void *context;
    int rerun;
    control = lsf_factory_cleanup_provider_control_current(
        container_of(work, struct lsf_cleanup_provider_control, retire));
    if (!control)
        return;
    source = control->source;
    if (READ_ONCE(control->preparing))
        goto again;
    (void)lsf_factory_cleanup_provider_unused_worker_finish(source);
    if (control->phase == LSF_PROVIDER_QUEUE_LIVE &&
        lsf_factory_cleanup_provider_close_ready(source) &&
        lsf_prepaid_acpi_provider_queue_lock(control)) {
        if (control->phase == LSF_PROVIDER_QUEUE_LIVE) {
            if (lsf_provider_ordered_restore(control))
                lsf_factory_cleanup_provider_hold(source);
            else
                lsf_prepaid_acpi_provider_queue_unregister(control);
        }
        lsf_prepaid_acpi_provider_queue_unlock();
    }
    if (control->phase != LSF_PROVIDER_QUEUE_RETURNING || control->original_reference ||
        READ_ONCE(control->wq) || !lsf_factory_cleanup_provider_core_retired(source))
        goto again;
    if (!lsf_factory_cleanup_provider_control_seal(source, control))
        goto again;
    /* This runs on the original pwq_release_worker after all original release
     * callbacks. Actual flushes prove the two earlier embedded work functions
     * have returned, with NO factory/WQ/ACPI/pool/VM/rq/create lock held. */
    kthread_flush_work(&control->handoff);
    kthread_flush_work(&control->release_barrier);
    context = control->context;
    control->context = NULL;
    control->phase = LSF_PROVIDER_QUEUE_RETIRED;
    atomic_set(&control->retire_pending, 2); /* No callback may requeue this work. */
    if (!lsf_factory_cleanup_provider_part_finish(source, LSF_PROVIDER_CONTEXT, context))
        return;
    /* LAST Control access. Maintained kthread_worker_fn explicitly does not
     * dereference work after func(work); trace-end uses the address only. */
    (void)lsf_factory_cleanup_provider_part_finish(source, LSF_PROVIDER_CONTROL, control);
    return;
again:
    rerun = atomic_xchg(&control->retire_pending, 0) == 3;
    if (rerun)
        if (!lsf_prepaid_cleanup_provider_retirement_kick_held(control))
            lsf_factory_cleanup_provider_hold(source);
}

void lsf_prepaid_cleanup_provider_queue_terminate(void *candidate)
{
    struct lsf_cleanup_provider_control *control;
    control = lsf_factory_cleanup_provider_control_current(candidate);
    if (!control)
        return;
    /* Actual ACPI lifetime mutex is held, producer lock already closed. The
     * opener cannot be between park/RCU stages while this mutex is acquired. */
    if (control->phase == LSF_PROVIDER_QUEUE_LIVE) {
        if (lsf_provider_ordered_restore(control))
            lsf_factory_cleanup_provider_hold(control->source);
    } else if (control->phase != LSF_PROVIDER_QUEUE_RETURNING) {
        lsf_factory_cleanup_provider_hold(control->source);
    }
    lsf_prepaid_cleanup_provider_retirement_kick();
}

int lsf_prepaid_cleanup_provider_destroy_full(void)
{
    if (!lsf_factory_cleanup_provider_request_close())
        return 0;
    lsf_prepaid_cleanup_provider_retirement_kick();
    return 1; /* Real close requested; no native final-free acknowledgement. */
}

int lsf_prepaid_cleanup_provider_queue_prepare(struct lsf_cleanup_task_source source,
    struct lsf_cleanup_provider_storage *storage)
{
    struct lsf_cleanup_provider_control *control;
    struct worker_pool *pool;
    struct pool_workqueue *private, *original;
    struct worker *worker;
    struct workqueue_struct *wq = NULL;
    unsigned int part;
    int error = -EOPNOTSUPP, acquired = 0, initialized_pwq = 0;
    if (!storage || !pwq_release_worker || !wq_online)
        return error;
    for (part = 0; part < LSF_PROVIDER_PARTS; ++part)
        if (!lsf_factory_cleanup_provider_storage_current(source, part, storage->addresses[part]))
            return error;
    pool = storage->addresses[LSF_PROVIDER_POOL];
    worker = storage->addresses[LSF_PROVIDER_WORKER];
    private = storage->addresses[LSF_PROVIDER_PWQ];
    control = storage->addresses[LSF_PROVIDER_CONTROL];
    control->source = source;
    control->private = private;
    control->context = storage->addresses[LSF_PROVIDER_CONTEXT];
    control->preparing = 1;
    init_completion(&control->prepared);
    init_completion(&control->unlinked_released);
    kthread_init_work(&control->handoff, lsf_provider_park_handoff);
    kthread_init_work(&control->retire, lsf_provider_retire_handoff);
    kthread_init_work(&control->release_barrier, lsf_provider_unlinked_barrier);
    atomic_set(&control->retire_pending, 0);
    error = lsf_provider_init_worker_pool(source, pool, storage->addresses[LSF_PROVIDER_ATTRS]);
    if (error) {
        lsf_factory_cleanup_provider_hold(source);
        return error; /* No known initialized destructor graph on this failure. */
    }
    for (part = 0; part < LSF_PROVIDER_PARTS; ++part)
        if (!lsf_factory_cleanup_provider_part_publish(source, part, storage->addresses[part])) {
            lsf_factory_cleanup_provider_hold(source);
            return -EIO;
        }
    error = lsf_prepaid_acpi_provider_queue_acquire(control, &wq);
    if (error)
        goto failed;
    acquired = 1;
    control->wq = wq;
    control->phase = LSF_PROVIDER_QUEUE_PREPARING;
    mutex_lock(&wq_pool_mutex);
    mutex_lock(&wq->mutex);
    original = rcu_access_pointer(wq->dfl_pwq);
    if (!original || !(wq->flags & WQ_UNBOUND) || !(wq->flags & __WQ_ORDERED) ||
        (wq->flags & (__WQ_DESTROYING | __WQ_DRAINING)) || wq->max_active != 1 || wq->rescuer ||
        !lsf_provider_slots_are(wq, original) ||
        wq->pwqs.next != &original->pwqs_node || original->pwqs_node.next != &wq->pwqs) {
        mutex_unlock(&wq->mutex);
        mutex_unlock(&wq_pool_mutex);
        error = -EOPNOTSUPP;
        goto failed;
    }
    /* Original queue/pool remains original-provider owned. Immutable pool
     * attrs are borrowed only under their actual original writer mutex. */
    pool->node = original->pool->node;
    copy_workqueue_attrs(pool->attrs, original->pool->attrs);
    wqattrs_clear_for_pool(pool->attrs);
    mutex_unlock(&wq->mutex);
    error = lsf_provider_pool_assign_id(source, pool); /* No growth or preload. */
    if (!error) {
        if (!lsf_provider_create_worker(source, pool, worker, &error) && !error)
            error = -ENOMEM;
    }
    if (!error) {
        init_pwq(private, wq, pool); /* Actual aligned paid subview. */
        initialized_pwq = 1;
        hash_add(unbound_pool_hash, &pool->hash_node, wqattrs_hash(pool->attrs));
    }
    mutex_unlock(&wq_pool_mutex);
    if (error)
        goto failed;
    error = lsf_provider_ordered_park(source, wq, storage);
    if (error)
        goto failed;
    wait_for_completion(&control->prepared); /* Actual old refs/colors + two RCU graces. */
    if (READ_ONCE(control->phase) != LSF_PROVIDER_QUEUE_LIVE) {
        lsf_factory_cleanup_provider_hold(source);
        lsf_prepaid_acpi_provider_queue_unlock();
        return -EIO;
    }
    WRITE_ONCE(control->preparing, 0);
    lsf_prepaid_acpi_provider_queue_unlock();
    lsf_prepaid_cleanup_provider_retirement_kick();
    return 0;
failed:
    if (error == -EIO || error == -EBUSY) {
        lsf_factory_cleanup_provider_hold(source);
        if (!initialized_pwq)
            WRITE_ONCE(control->wq, NULL);
        if (acquired) {
            lsf_prepaid_acpi_provider_queue_unregister(control);
            lsf_prepaid_acpi_provider_queue_unlock();
        }
        return error; /* Unknown association/submission retains the complete graph. */
    }
    /* Unsubmitted cancellation uses a real never-published request latch;
     * failed submitted creation instead waits its true Task/child returns. */
    (void)lsf_factory_cleanup_provider_cancel_unsubmitted(source);
    control->phase = LSF_PROVIDER_QUEUE_RETURNING;
    if (initialized_pwq) {
        put_pwq_unlocked(private);
        /* Do not follow PWQ bytes after the real final put. This separately
         * paid barrier runs AFTER its release callback on the SAME worker. */
        kthread_queue_work(pwq_release_worker, &control->release_barrier);
        wait_for_completion(&control->unlinked_released);
    } else {
        (void)lsf_factory_cleanup_provider_part_finish(source, LSF_PROVIDER_PWQ, private);
        WRITE_ONCE(control->wq, NULL); /* No PWQ ever referenced this WQ. */
        mutex_lock(&wq_pool_mutex);
        put_unbound_pool(pool); /* Full original worker/timer/IDA/RCU graph. */
        mutex_unlock(&wq_pool_mutex);
    }
    if (acquired) {
        lsf_prepaid_acpi_provider_queue_unregister(control);
        lsf_prepaid_acpi_provider_queue_unlock();
    }
    WRITE_ONCE(control->preparing, 0);
    lsf_prepaid_cleanup_provider_retirement_kick();
    return error;
}
