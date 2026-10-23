/* SPDX-License-Identifier: GPL-2.0-only */
/* Provider-owned notification storage, charged with the existing static seals.
 * It stores no allocation authority, Root ticket, capacity or alternate ledger.
 * The real registration and paid Control remain the lifetime authority. */
static DECLARE_WAIT_QUEUE_HEAD(lsf_acpi_provider_constructor_wait);

void lsf_prepaid_acpi_provider_queue_changed(void)
{
    wake_up_all(&lsf_acpi_provider_constructor_wait);
}

static bool lsf_acpi_provider_constructor_settled(void)
{
    bool settled;
    mutex_lock(&lsf_acpi_provider_lifetime_mutex);
    settled = !lsf_acpi_provider_registration ||
        lsf_prepaid_cleanup_provider_queue_pending(lsf_acpi_provider_registration) == 0;
    mutex_unlock(&lsf_acpi_provider_lifetime_mutex);
    return settled;
}

static void lsf_prepaid_acpi_provider_terminate(void)
{
    void *control;
    for (;;) {
        mutex_lock(&lsf_acpi_provider_lifetime_mutex);
        /* Only our Root producer closes. All ordinary original ACPI producers
         * and all three original destroy_workqueue calls remain unchanged. */
        lsf_prepaid_acpi_reference_queue_state(false);
        control = lsf_acpi_provider_registration;
        if (!control) {
            mutex_unlock(&lsf_acpi_provider_lifetime_mutex);
            return;
        }
        lsf_factory_cleanup_provider_queue_closed();
        if (lsf_prepaid_cleanup_provider_queue_pending(control) == 0) {
            lsf_prepaid_cleanup_provider_queue_terminate(control);
            lsf_prepaid_acpi_provider_queue_unregister(control);
            mutex_unlock(&lsf_acpi_provider_lifetime_mutex);
            return;
        }
        /* No candidate pointer is followed beyond this unlock. The condition
         * reacquires the SAME lifetime mutex before reading registration and
         * authenticates the paid Control before its phase/completion fields.
         * A topology fault retains the real queue lifetime; no false settle. */
        mutex_unlock(&lsf_acpi_provider_lifetime_mutex);
        wait_event(lsf_acpi_provider_constructor_wait,
            lsf_acpi_provider_constructor_settled());
    }
}
