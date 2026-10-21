/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in pci-acpi.c after its actual lookup rwsem, hook and original
 * lookup definition. The generated private original body is above this file. */
int lsf_prepaid_pci_set_acpi_fwnode(struct pci_dev *dev)
{
    struct acpi_device *companion = NULL;
    int error = -EOPNOTSUPP;

    /* Positive whole-birth lookup MUST precede any device dereference. */
    if (lsf_factory_device_pci_owned(dev, sizeof(*dev)) != 1)
        return error;
    if (dev_fwnode(&dev->dev) || pci_dev_is_added(dev) ||
        !lsf_prepaid_acpi_reference_queue_ready())
        return error;
    /* Descriptor + original queue work metadata are prepaid BEFORE lookup/get.
     * Every failure propagates to the original PCI setup unwind. It records
     * retirement there; no final reference put runs under the scan/factory lock. */
    error = lsf_factory_device_firmware_begin(dev);
    if (error)
        return error;
    error = -EOPNOTSUPP;
    if (!lsf_prepaid_acpi_scan_enter())
        return error;
    if (!down_read_trylock(&pci_acpi_companion_lookup_sem))
        goto scan_out;
    /* Original writers hold this SAME rwsem. A custom allocating hook cannot
     * appear between this test and association, nor be silently ignored. */
    if (pci_acpi_find_companion_hook)
        goto lookup_out;
    error = lsf_prepaid_acpi_pci_find_companion(&dev->dev, &companion);
    if (!error && (!lsf_factory_device_firmware_current(dev, companion) ||
        (companion && acpi_fwnode_handle(companion)->secondary)))
        error = -EOPNOTSUPP;
    if (!error)
        ACPI_COMPANION_SET(&dev->dev, companion);
lookup_out:
    up_read(&pci_acpi_companion_lookup_sem);
scan_out:
    lsf_prepaid_acpi_scan_leave();
    return error;
}
