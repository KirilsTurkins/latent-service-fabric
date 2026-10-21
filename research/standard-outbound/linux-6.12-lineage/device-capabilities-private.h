/* SPDX-License-Identifier: GPL-2.0-only */
/* Private original PCI capability-save allocation/free path. Uninstalled. */
#ifndef LSF_STREAM_DEVICE_CAPABILITIES_PRIVATE_H
#define LSF_STREAM_DEVICE_CAPABILITIES_PRIVATE_H
#include <linux/types.h>

struct pci_dev;
int lsf_prepaid_pci_add_cap_save_buffer(struct pci_dev *, u16, bool, unsigned int);

int lsf_factory_device_capabilities_owned(const void *);
void *lsf_factory_device_capability_allocate(const void *, unsigned long);
int lsf_factory_device_capability_return(const void *, const void *);

#endif
