/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in actual osl.c after its original queue and admission adapter.
 * An identity check alone is NOT lasting queue lifetime registration. */
int lsf_prepaid_acpi_reference_queue_identity(struct workqueue_struct *candidate)
{
    unsigned long flags;
    int result;
    spin_lock_irqsave(&lsf_acpi_reference_queue_lock, flags);
    result = lsf_acpi_reference_queue_live && candidate == kacpi_hotplug_wq;
    spin_unlock_irqrestore(&lsf_acpi_reference_queue_lock, flags);
    return result;
}
