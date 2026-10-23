/* SPDX-License-Identifier: GPL-2.0-only */
/* Called only under the real ACPI lifetime mutex. A real registration borrow
 * pins this exact Control until settlement/restoration, independently of the
 * opener. Unknown states keep that borrow and never admit original WQ free. */
int lsf_prepaid_cleanup_provider_queue_pending(void *candidate)
{
    struct lsf_cleanup_provider_control *control;
    unsigned int phase;
    control = lsf_factory_cleanup_provider_control_current(candidate);
    if (!control || READ_ONCE(control->constructor_quarantined))
        return -EIO;
    phase = READ_ONCE(control->phase);
    if (READ_ONCE(control->preparing) || phase == LSF_PROVIDER_QUEUE_PREPARING ||
        phase == LSF_PROVIDER_QUEUE_PARKING || phase == LSF_PROVIDER_QUEUE_PARKED_RCU)
        return 1;
    if (phase == LSF_PROVIDER_QUEUE_RETURNING && READ_ONCE(control->failed_unlinked))
        return !completion_done(&control->unlinked_released) || READ_ONCE(control->wq) != NULL;
    if (phase == LSF_PROVIDER_QUEUE_LIVE || phase == LSF_PROVIDER_QUEUE_RETURNING)
        return 0;
    return -EIO;
}

/* Only the actual original opener may obtain the same paid completion. The
 * returned opaque value is a real Control reader borrow, not a new owner. */
void *lsf_prepaid_cleanup_provider_birth_wait_get(struct lsf_cleanup_task_source source,
    const void *worker, struct completion **done, unsigned long *remaining)
{
    struct lsf_cleanup_provider_control *control;
    unsigned long now;
    if (!done || !remaining)
        return NULL;
    *done = NULL;
    *remaining = 0;
    control = lsf_factory_cleanup_provider_control_get(NULL);
    if (!control)
        return NULL;
    if (!lsf_factory_cleanup_provider_storage_current(source, LSF_PROVIDER_CONTROL, control) ||
        !lsf_factory_cleanup_provider_storage_current(source, LSF_PROVIDER_WORKER, worker) ||
        !lsf_factory_cleanup_provider_waiter_current(source)) {
        lsf_factory_cleanup_provider_control_put(control);
        return NULL;
    }
    now = jiffies;
    *done = &control->born;
    if (time_before(now, control->constructor_expires))
        *remaining = control->constructor_expires - now;
    return control;
}

void lsf_prepaid_cleanup_provider_birth_wait_put(void *candidate, int claimed_late)
{
    struct lsf_cleanup_provider_control *control;
    control = lsf_factory_cleanup_provider_control_current(candidate);
    if (!control)
        return; /* Unknown identity cannot justify decrement or reuse. */
    if (claimed_late) {
        /* A real creator/child may still call complete() or remain asleep.
         * Keep preparing set and the complete paid graph indefinitely until
         * actual physical proof exists. No timeout can recycle these bytes. */
        WRITE_ONCE(control->constructor_quarantined, 1);
        lsf_factory_cleanup_provider_hold(control->source);
    }
    lsf_factory_cleanup_provider_control_put(control); /* LAST Control access. */
}

unsigned long lsf_prepaid_cleanup_provider_birth_remaining(void *candidate)
{
    struct lsf_cleanup_provider_control *control;
    unsigned long now;
    control = lsf_factory_cleanup_provider_control_current(candidate);
    if (!control)
        return 0;
    now = jiffies;
    return time_before(now, control->constructor_expires) ? control->constructor_expires - now : 0;
}

/* Caller supplies its existing narrower remaining budget in jiffies. There is
 * no invented constructor timeout, implicit retry, deadline extension or new
 * IoCall. This can only narrow the one expiry fixed before original birth.
 * The full consumer remains unselected; mutex/constructor execution timing
 * and the actual public IoCall integration remain unqualified. */
int lsf_prepaid_cleanup_provider_wait_ready(unsigned long remaining)
{
    struct lsf_cleanup_provider_control *control;
    struct lsf_cleanup_task_source source;
    long waited;
    int result;
    if (remaining > MAX_JIFFY_OFFSET)
        return -EINVAL;
    control = lsf_factory_cleanup_provider_control_get(NULL);
    if (!control)
        return -EOPNOTSUPP;
    source = control->source;
    if (!lsf_factory_cleanup_provider_waiter_current(source)) {
        result = -EOPNOTSUPP;
        goto out;
    }
    remaining = min(remaining, lsf_prepaid_cleanup_provider_birth_remaining(control));
    /* Actual paid reader borrow spans every completion/phase field access.
     * No factory, ACPI lifetime, WQ, pool, VM, rq or create lock is held. */
    waited = remaining ? wait_for_completion_killable_timeout(&control->prepared, remaining) : 0;
    if (waited <= 0 || !lsf_prepaid_cleanup_provider_birth_remaining(control)) {
        result = waited < 0 ? (int)waited : -ETIMEDOUT;
        lsf_factory_cleanup_provider_waiter_cancel(source);
    } else if (READ_ONCE(control->phase) != LSF_PROVIDER_QUEUE_LIVE ||
        !lsf_factory_cleanup_provider_waiter_current(source)) {
        result = -EIO;
    } else {
        result = 0;
    }
out:
    lsf_factory_cleanup_provider_control_put(control); /* LAST Control access. */
    return result;
}
