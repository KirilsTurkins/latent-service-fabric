/* SPDX-License-Identifier: GPL-2.0-only */
/* Included after actual apply_wqattrs_ctx and original ordered-WQ helpers.
 * Source mechanisms only: no consumer selects or constructs this executor. */
enum lsf_provider_queue_phase {
    LSF_PROVIDER_QUEUE_EMPTY, LSF_PROVIDER_QUEUE_PARKING,
    LSF_PROVIDER_QUEUE_PARKED_RCU, LSF_PROVIDER_QUEUE_LIVE,
    LSF_PROVIDER_QUEUE_RETURNING, LSF_PROVIDER_QUEUE_RETIRED
};
struct lsf_cleanup_provider_control {
    struct lsf_cleanup_task_source source;
    struct workqueue_struct *wq;
    struct pool_workqueue *original, *private;
    struct apply_wqattrs_ctx *context;
    struct kthread_work handoff;
    struct completion prepared;
    unsigned int phase, original_reference;
};

int lsf_prepaid_cleanup_provider_part_geometry(unsigned int part,
    unsigned long *bytes, unsigned long *alignment)
{
    if (!bytes || !alignment || !nr_cpu_ids || nr_cpu_ids > 64u)
        return -EOPNOTSUPP;
    switch (part) {
    case LSF_PROVIDER_POOL:
        *bytes = sizeof(struct worker_pool); *alignment = __alignof__(struct worker_pool); break;
    case LSF_PROVIDER_WORKER:
        *bytes = sizeof(struct worker); *alignment = __alignof__(struct worker); break;
    case LSF_PROVIDER_PWQ:
        *bytes = sizeof(struct pool_workqueue); *alignment = __alignof__(struct pool_workqueue); break;
    case LSF_PROVIDER_ATTRS:
        /* Exact selected config has embedded cpumask_var_t, no extra heap masks. */
        if (IS_ENABLED(CONFIG_CPUMASK_OFFSTACK))
            return -EOPNOTSUPP;
        *bytes = sizeof(struct workqueue_attrs); *alignment = __alignof__(struct workqueue_attrs); break;
    case LSF_PROVIDER_CONTROL:
        *bytes = sizeof(struct lsf_cleanup_provider_control);
        *alignment = __alignof__(struct lsf_cleanup_provider_control); break;
    case LSF_PROVIDER_CONTEXT:
        *bytes = struct_size((struct apply_wqattrs_ctx *)NULL, pwq_tbl, nr_cpu_ids);
        *alignment = __alignof__(struct apply_wqattrs_ctx); break;
    default: return -EINVAL;
    }
    return 0;
}

static bool lsf_provider_pwq_quiescent_locked(struct pool_workqueue *pwq)
{
    int color;
    lockdep_assert_held(&pwq->pool->lock);
    /* Exactly OUR real borrowed reference remains. Slots, work, barriers,
     * temporary attribute contexts and all other original references are gone. */
    if (pwq->refcnt != 1 || pwq->nr_active || !list_empty(&pwq->inactive_works) ||
        pwq->flush_color != -1 || !list_empty(&pwq->pending_node))
        return false;
    for (color = 0; color < WORK_NR_COLORS; ++color)
        if (pwq->nr_in_flight[color])
            return false;
    return true;
}

static bool lsf_provider_slots_are(struct workqueue_struct *wq,
    struct pool_workqueue *expected)
{
    int cpu;
    lockdep_assert_held(&wq_pool_mutex);
    lockdep_assert_held(&wq->mutex);
    if (rcu_access_pointer(wq->dfl_pwq) != expected)
        return false;
    for_each_possible_cpu(cpu)
        if (rcu_access_pointer(*per_cpu_ptr(wq->cpu_pwq, cpu)) != expected)
            return false;
    return true;
}

static void lsf_provider_park_handoff(struct kthread_work *work)
{
    struct lsf_cleanup_provider_control *control;
    struct pool_workqueue *original;
    struct workqueue_struct *wq;
    control = lsf_factory_cleanup_provider_control_current(
        container_of(work, struct lsf_cleanup_provider_control, handoff));
    if (!control)
        return;
    /* Exclude every pre-commit __queue_work RCU reader BEFORE testing the old
     * reference count. Ordered queueing always selects the newest PWQ. */
    synchronize_rcu();
    mutex_lock(&wq_pool_mutex);
    if (control->phase != LSF_PROVIDER_QUEUE_PARKING || !control->original_reference)
        goto out_pool;
    wq = control->wq;
    original = control->original;
    mutex_lock(&wq->mutex);
    raw_spin_lock_irq(&original->pool->lock);
    if (!lsf_provider_slots_are(wq, control->private) ||
        !lsf_provider_pwq_quiescent_locked(original) || list_empty(&wq->pwqs) ||
        list_first_entry(&wq->pwqs, struct pool_workqueue, pwqs_node) != original ||
        original->pwqs_node.next != &control->private->pwqs_node ||
        control->private->pwqs_node.next != &wq->pwqs)
        goto out_original;
    /* Manual equivalent of original release's list/unplug stage ONLY after
     * every original release condition apart from our borrow has completed.
     * The original physical PWQ/pool are NOT returned or adopted by Root. */
    list_del_rcu(&original->pwqs_node);
    control->phase = LSF_PROVIDER_QUEUE_PARKED_RCU;
    raw_spin_unlock_irq(&original->pool->lock);
    unplug_oldest_pwq(wq);
    mutex_unlock(&wq->mutex);
    mutex_unlock(&wq_pool_mutex);
    /* Old list readers must retire before this list node can be reused. */
    synchronize_rcu();
    mutex_lock(&wq_pool_mutex);
    mutex_lock(&wq->mutex);
    raw_spin_lock_irq(&original->pool->lock);
    if (control->phase == LSF_PROVIDER_QUEUE_PARKED_RCU &&
        lsf_provider_pwq_quiescent_locked(original)) {
        INIT_LIST_HEAD(&original->pwqs_node);
        control->phase = LSF_PROVIDER_QUEUE_LIVE;
        complete_all(&control->prepared); /* Actual park/RCU completion, not retirement. */
    }
out_original:
    raw_spin_unlock_irq(&original->pool->lock);
    mutex_unlock(&wq->mutex);
out_pool:
    mutex_unlock(&wq_pool_mutex);
}

/* Called at the real put_pwq boundary while original pool->lock is held, just
 * before the real decrement. The handoff takes that same lock before checking,
 * so it cannot certify quiescence before this final original reference drops. */
void lsf_prepaid_cleanup_provider_pwq_drop(void *address)
{
    struct lsf_cleanup_provider_control *control;
    struct pool_workqueue *pwq = address;
    control = lsf_factory_cleanup_provider_control_current(NULL);
    if (!control || READ_ONCE(control->phase) != LSF_PROVIDER_QUEUE_PARKING ||
        READ_ONCE(control->original) != pwq)
        return;
    lockdep_assert_held(&pwq->pool->lock);
    if (pwq->refcnt == 2)
        kthread_queue_work(pwq_release_worker, &control->handoff);
}

static int lsf_provider_ordered_park(struct lsf_cleanup_task_source source,
    struct workqueue_struct *wq, struct lsf_cleanup_provider_storage *storage)
{
    struct lsf_cleanup_provider_control *control;
    struct pool_workqueue *original, *private;
    struct apply_wqattrs_ctx *context;
    int cpu, result = -EOPNOTSUPP;
    /* Authenticate each paid extent BEFORE any field initialization/read. */
    if (!storage || !lsf_factory_cleanup_provider_storage_current(source,
            LSF_PROVIDER_CONTROL, storage->addresses[LSF_PROVIDER_CONTROL]) ||
        !lsf_factory_cleanup_provider_storage_current(source,
            LSF_PROVIDER_PWQ, storage->addresses[LSF_PROVIDER_PWQ]) ||
        !lsf_factory_cleanup_provider_storage_current(source,
            LSF_PROVIDER_CONTEXT, storage->addresses[LSF_PROVIDER_CONTEXT]))
        return result;
    control = storage->addresses[LSF_PROVIDER_CONTROL];
    private = storage->addresses[LSF_PROVIDER_PWQ];
    context = storage->addresses[LSF_PROVIDER_CONTEXT];
    /* Actual queue lifetime registration with ACPI termination and actual
     * private pool/Task construction remain required BEFORE calling this. */
    if (!wq || !lsf_prepaid_acpi_reference_queue_identity(wq) ||
        private->wq != wq || private->refcnt != 1 ||
        !lsf_factory_cleanup_provider_storage_current(source, LSF_PROVIDER_POOL, private->pool))
        return result;
    mutex_lock(&wq_pool_mutex);
    mutex_lock(&wq->mutex);
    original = rcu_access_pointer(wq->dfl_pwq);
    if (control->phase != LSF_PROVIDER_QUEUE_EMPTY || !original ||
        !(wq->flags & WQ_UNBOUND) || !(wq->flags & __WQ_ORDERED) ||
        (wq->flags & (__WQ_DESTROYING | __WQ_DRAINING)) || wq->max_active != 1 || wq->rescuer ||
        !lsf_provider_slots_are(wq, original) ||
        wq->pwqs.next != &original->pwqs_node || original->pwqs_node.next != &wq->pwqs)
        goto out;
    raw_spin_lock_irq(&original->pool->lock);
    if (original->refcnt <= 0) {
        raw_spin_unlock_irq(&original->pool->lock);
        goto out;
    }
    get_pwq(original); /* REAL original-provider borrow, not a new Root birth. */
    raw_spin_unlock_irq(&original->pool->lock);
    control->source = source;
    control->wq = wq;
    control->original = original;
    control->private = private;
    control->context = context;
    control->original_reference = 1;
    init_completion(&control->prepared);
    kthread_init_work(&control->handoff, lsf_provider_park_handoff);
    raw_spin_lock_irq(&private->pool->lock);
    private->plugged = true;
    /* Initial ref belongs to dfl; one real additional ref per actual CPU slot. */
    for_each_possible_cpu(cpu)
        get_pwq(private);
    raw_spin_unlock_irq(&private->pool->lock);
    control->phase = LSF_PROVIDER_QUEUE_PARKING;
    for_each_possible_cpu(cpu)
        context->pwq_tbl[cpu] = install_unbound_pwq(wq, cpu, private);
    context->dfl_pwq = install_unbound_pwq(wq, -1, private);
    mutex_unlock(&wq->mutex);
    for_each_possible_cpu(cpu)
        put_pwq_unlocked(context->pwq_tbl[cpu]);
    put_pwq_unlocked(context->dfl_pwq);
    mutex_unlock(&wq_pool_mutex);
    return 0; /* Parking may still be in flight; no Ready/final-free claim. */
out:
    mutex_unlock(&wq->mutex);
    mutex_unlock(&wq_pool_mutex);
    return result;
}

static int lsf_provider_ordered_restore(struct lsf_cleanup_provider_control *candidate)
{
    struct lsf_cleanup_provider_control *control;
    struct apply_wqattrs_ctx *context;
    struct pool_workqueue *original;
    struct workqueue_struct *wq;
    int cpu, result = -EBUSY;
    control = lsf_factory_cleanup_provider_control_current(candidate);
    if (!control)
        return -EIO;
    /* The context is the same still-LIVE prepaid extent, not new storage. */
    context = control->context;
    if (!lsf_factory_cleanup_provider_storage_current(control->source,
            LSF_PROVIDER_CONTEXT, context))
        return -EIO;
    mutex_lock(&wq_pool_mutex);
    if (control->phase != LSF_PROVIDER_QUEUE_LIVE || !control->original_reference)
        goto out_pool;
    wq = control->wq;
    original = control->original;
    mutex_lock(&wq->mutex);
    raw_spin_lock_irq(&original->pool->lock);
    if (!lsf_provider_pwq_quiescent_locked(original) || !list_empty(&original->pwqs_node) ||
        !lsf_provider_slots_are(wq, control->private)) {
        raw_spin_unlock_irq(&original->pool->lock);
        goto out_wq;
    }
    original->plugged = true;
    get_pwq(original); /* Real dfl slot reference. */
    for_each_possible_cpu(cpu)
        get_pwq(original);
    raw_spin_unlock_irq(&original->pool->lock);
    control->phase = LSF_PROVIDER_QUEUE_RETURNING;
    for_each_possible_cpu(cpu)
        context->pwq_tbl[cpu] = install_unbound_pwq(wq, cpu, original);
    context->dfl_pwq = install_unbound_pwq(wq, -1, original);
    mutex_unlock(&wq->mutex);
    /* Existing private callbacks finish in original order. Real last-PWQ
     * release removes the private node and unplugs this restored original. */
    for_each_possible_cpu(cpu)
        put_pwq_unlocked(context->pwq_tbl[cpu]);
    put_pwq_unlocked(context->dfl_pwq);
    control->original_reference = 0;
    put_pwq_unlocked(original); /* Drop ONLY our real parked borrow. */
    mutex_unlock(&wq_pool_mutex);
    return 0; /* Does not retire new pool/worker/Task/PWQ/RCU or native backing. */
out_wq:
    mutex_unlock(&wq->mutex);
out_pool:
    mutex_unlock(&wq_pool_mutex);
    return result;
}

static bool lsf_provider_single_worker_locked(struct worker *worker, struct worker_pool *pool)
{
    struct lsf_cleanup_provider_control *control;
    struct pool_workqueue *pwq;
    unsigned int phase;
    lockdep_assert_held(&pool->lock);
    control = lsf_factory_cleanup_provider_control_current(NULL);
    if (!control)
        return false;
    phase = READ_ONCE(control->phase);
    if (phase != LSF_PROVIDER_QUEUE_PARKING && phase != LSF_PROVIDER_QUEUE_PARKED_RCU &&
        phase != LSF_PROVIDER_QUEUE_LIVE && phase != LSF_PROVIDER_QUEUE_RETURNING)
        return false;
    if (!lsf_factory_cleanup_provider_storage_current(control->source, LSF_PROVIDER_POOL, pool) ||
        !lsf_factory_cleanup_provider_storage_current(control->source, LSF_PROVIDER_WORKER, worker) ||
        !lsf_factory_cleanup_provider_storage_current(control->source,
            LSF_PROVIDER_PWQ, control->private))
        return false;
    pwq = control->private;
    return worker->task == current && worker->pool == pool && !worker->rescue_wq &&
        pool->cpu == -1 && pool->nr_workers == 1 && !(pool->flags & POOL_MANAGER_ACTIVE) &&
        list_is_singular(&pool->workers) && pool->workers.next == &worker->node &&
        pwq->pool == pool && pwq->wq == control->wq &&
        (READ_ONCE(control->wq->flags) & __WQ_ORDERED) && READ_ONCE(control->wq->max_active) == 1;
}

static int lsf_provider_worker_entry(void *candidate)
{
    struct lsf_cleanup_task_source source;
    void *worker, *pool;
    if (lsf_factory_cleanup_provider_physical_current(&source) != 2 ||
        lsf_factory_cleanup_provider_snapshot_source(source, &worker, &pool) != 1 ||
        candidate != worker)
        return -EIO;
    return 0;
}

int lsf_prepaid_cleanup_provider_attributes_bound(struct workqueue_struct *candidate)
{
    struct lsf_cleanup_provider_control *control;
    unsigned int phase;
    control = lsf_factory_cleanup_provider_control_current(NULL);
    if (!control || READ_ONCE(control->wq) != candidate)
        return 0;
    phase = READ_ONCE(control->phase);
    return phase == LSF_PROVIDER_QUEUE_PARKING || phase == LSF_PROVIDER_QUEUE_PARKED_RCU ||
        phase == LSF_PROVIDER_QUEUE_LIVE || phase == LSF_PROVIDER_QUEUE_RETURNING;
}
