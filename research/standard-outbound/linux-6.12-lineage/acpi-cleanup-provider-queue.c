/* SPDX-License-Identifier: GPL-2.0-only */
/* Lock order: this actual lifetime mutex precedes WQ pool/wq mutexes. The
 * original adapter spinlock is never held across creation, callbacks or puts.
 * Ordinary producers use their original queue and retain original ordering. */
static DEFINE_MUTEX(lsf_acpi_provider_lifetime_mutex);
static void *lsf_acpi_provider_registration;

unsigned long lsf_prepaid_acpi_provider_bootstrap_bytes(void)
{
    return sizeof(lsf_acpi_provider_lifetime_mutex) + sizeof(lsf_acpi_provider_registration) +
        sizeof(lsf_acpi_reference_queue_lock) + sizeof(lsf_acpi_reference_queue_live);
}

int lsf_prepaid_acpi_provider_queue_acquire(void *candidate, struct workqueue_struct **queue)
{
    unsigned long flags;
    int error = -EOPNOTSUPP;
    if (!queue || !candidate || lsf_factory_cleanup_provider_control_get(candidate) != candidate)
        return error;
    *queue = NULL;
    mutex_lock(&lsf_acpi_provider_lifetime_mutex);
    spin_lock_irqsave(&lsf_acpi_reference_queue_lock, flags);
    if (lsf_acpi_reference_queue_live && !lsf_acpi_provider_registration && kacpi_hotplug_wq) {
        lsf_acpi_provider_registration = candidate;
        *queue = kacpi_hotplug_wq;
        error = 0;
    }
    spin_unlock_irqrestore(&lsf_acpi_reference_queue_lock, flags);
    if (error) {
        mutex_unlock(&lsf_acpi_provider_lifetime_mutex);
        lsf_factory_cleanup_provider_control_put(candidate);
    }
    return error; /* On success the SAME caller retains the actual mutex. */
}

int lsf_prepaid_acpi_provider_queue_lock(void *candidate)
{
    int result;
    mutex_lock(&lsf_acpi_provider_lifetime_mutex);
    result = candidate && lsf_acpi_provider_registration == candidate;
    if (!result)
        mutex_unlock(&lsf_acpi_provider_lifetime_mutex);
    return result;
}

void lsf_prepaid_acpi_provider_queue_unlock(void)
{
    lockdep_assert_held(&lsf_acpi_provider_lifetime_mutex);
    mutex_unlock(&lsf_acpi_provider_lifetime_mutex);
}

void lsf_prepaid_acpi_provider_queue_unregister(void *candidate)
{
    unsigned long flags;
    int released = 0;
    lockdep_assert_held(&lsf_acpi_provider_lifetime_mutex);
    spin_lock_irqsave(&lsf_acpi_reference_queue_lock, flags);
    if (candidate && lsf_acpi_provider_registration == candidate) {
        lsf_acpi_provider_registration = NULL;
        released = 1;
    }
    spin_unlock_irqrestore(&lsf_acpi_reference_queue_lock, flags);
    if (released)
        lsf_factory_cleanup_provider_control_put(candidate); /* LAST candidate access. */
}

static void lsf_prepaid_acpi_provider_terminate(void)
{
    void *control;
    mutex_lock(&lsf_acpi_provider_lifetime_mutex);
    /* Exact original close under the SAME producer lock precedes restoration.
     * New Root work cannot enter; ordinary original destroy_workqueue still
     * drains all three original queues, including every pre-close callback. */
    lsf_prepaid_acpi_reference_queue_state(false);
    control = lsf_acpi_provider_registration;
    if (control) {
        lsf_factory_cleanup_provider_queue_closed();
        lsf_prepaid_cleanup_provider_queue_terminate(control);
        lsf_prepaid_acpi_provider_queue_unregister(control);
    }
    mutex_unlock(&lsf_acpi_provider_lifetime_mutex);
}
