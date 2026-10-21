/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in osl.c AFTER the original queue function. Initialization publishes
 * this queue only after all original BUG_ON checks; termination closes it under
 * this SAME lock before original destroy_workqueue. No lock spans destruction,
 * work callbacks, a final put, or the original initialization callbacks. */
static DEFINE_SPINLOCK(lsf_acpi_reference_queue_lock);
static bool lsf_acpi_reference_queue_live;

int lsf_prepaid_acpi_reference_queue_ready(void)
{
    unsigned long flags;
    int ready;
    spin_lock_irqsave(&lsf_acpi_reference_queue_lock, flags);
    ready = lsf_acpi_reference_queue_live;
    spin_unlock_irqrestore(&lsf_acpi_reference_queue_lock, flags);
    return ready;
}

static void lsf_prepaid_acpi_reference_queue_state(bool live)
{
    unsigned long flags;
    spin_lock_irqsave(&lsf_acpi_reference_queue_lock, flags);
    lsf_acpi_reference_queue_live = live;
    spin_unlock_irqrestore(&lsf_acpi_reference_queue_lock, flags);
}

int lsf_prepaid_acpi_queue_reference_put(struct work_struct *work)
{
    unsigned long flags;
    int queued = 0;
    spin_lock_irqsave(&lsf_acpi_reference_queue_lock, flags);
    if (lsf_acpi_reference_queue_live)
        queued = acpi_queue_hotplug_work(work);
    spin_unlock_irqrestore(&lsf_acpi_reference_queue_lock, flags);
    return queued;
}
