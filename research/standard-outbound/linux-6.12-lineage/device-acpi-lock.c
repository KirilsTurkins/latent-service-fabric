/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in scan.c AFTER its actual initialized flag and scan mutex exist. */
int lsf_prepaid_acpi_scan_enter(void)
{
    if (READ_ONCE(acpi_disabled) || !READ_ONCE(acpi_scan_initialized) ||
        !mutex_trylock(&acpi_scan_lock))
        return 0;
    /* A popped deletion is still active through its ORIGINAL final put. The
     * original deletion mutex, not merely the scan mutex, serializes handle
     * invalidation against this cached lookup and pointer association. */
    if (!mutex_trylock(&acpi_device_del_lock)) {
        mutex_unlock(&acpi_scan_lock);
        return 0;
    }
    if (READ_ONCE(acpi_disabled) || !READ_ONCE(acpi_scan_initialized) ||
        lsf_acpi_deletion_uncertain || lsf_acpi_deletions_active ||
        !list_empty(&acpi_device_del_list)) {
        mutex_unlock(&acpi_device_del_lock);
        mutex_unlock(&acpi_scan_lock);
        return 0;
    }
    return 1;
}

void lsf_prepaid_acpi_scan_leave(void)
{
    mutex_unlock(&acpi_device_del_lock);
    mutex_unlock(&acpi_scan_lock);
}

/* Called INSIDE the original iterator's live-reference callback. No AML or
 * unknown hook is invoked. The deletion mutex is already held continuously
 * from admission through this reference and the actual fwnode association. */
int lsf_prepaid_acpi_reference(struct pci_dev *consumer, struct acpi_device *adev)
{
    lockdep_assert_held(&acpi_device_del_lock);
    if (!adev || !adev->handle || adev->handle == INVALID_ACPI_HANDLE)
        return -EOPNOTSUPP;
    return lsf_factory_device_firmware_get(consumer, adev);
}
