/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef LSF_STREAM_DEVICE_FIRMWARE_PRIVATE_H
#define LSF_STREAM_DEVICE_FIRMWARE_PRIVATE_H

#include <linux/types.h>

struct acpi_device;
struct pci_dev;
struct work_struct;

/* Fixed private platform subset, not a request parameter or extra ledger. */
#define LSF_DEVICE_ACPI_CHILDREN 32u

int lsf_prepaid_acpi_scan_enter(void);
void lsf_prepaid_acpi_scan_leave(void);
int lsf_prepaid_acpi_reference(struct pci_dev *, struct acpi_device *);
int lsf_prepaid_acpi_queue_reference_put(struct work_struct *);
int lsf_prepaid_acpi_reference_queue_ready(void);
int lsf_prepaid_acpi_dev_for_each_child(struct acpi_device *parent,
                                      int (*fn)(struct acpi_device *, void *),
                                      void *data);
int lsf_prepaid_acpi_find_child_device(struct pci_dev *consumer,
                                      struct acpi_device *parent,
                                      unsigned long long address,
                                      bool check_children,
                                      struct acpi_device **result);
int lsf_prepaid_pci_set_acpi_fwnode(struct pci_dev *dev);
int lsf_factory_device_firmware_begin(const void *);
int lsf_factory_device_firmware_get(const void *, struct acpi_device *);
int lsf_factory_device_firmware_current(const void *, struct acpi_device *);
void lsf_factory_device_firmware_invalidate(struct acpi_device *, const void *);
int lsf_factory_device_firmware_retire(const void *);
int lsf_factory_device_firmware_constructor_enter(void);
void lsf_factory_device_firmware_constructor_leave(void);

#endif
