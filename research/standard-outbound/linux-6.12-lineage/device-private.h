/* SPDX-License-Identifier: GPL-2.0-only */
/* Private fixed-platform producer. None of these are userspace ABI/exports. */
#ifndef LSF_STREAM_DEVICE_PRIVATE_H
#define LSF_STREAM_DEVICE_PRIVATE_H

/* Proposed dedicated modern virtio-net coordinate. This is compiled source,
 * not a vendor-wide match or caller/operator-supplied pointer/cost certificate.
 * It is NOT a claim that an installed platform exists at this coordinate. */
#define LSF_DEVICE_PCI_DOMAIN 0u
#define LSF_DEVICE_PCI_BUS 0u
#define LSF_DEVICE_PCI_DEVFN (3u << 3)
#define LSF_DEVICE_PCI_VENDOR 0x1af4u
#define LSF_DEVICE_PCI_DEVICE 0x1041u
#define LSF_DEVICE_PCI_NAME "0000:00:03.0"

static inline int lsf_factory_device_selected(unsigned int domain,
    unsigned int bus, unsigned int devfn)
{
    return domain == LSF_DEVICE_PCI_DOMAIN && bus == LSF_DEVICE_PCI_BUS &&
        devfn == LSF_DEVICE_PCI_DEVFN;
}

struct pci_bus;
struct pci_dev;
struct pci_dev *lsf_prepaid_pci_alloc_dev(struct pci_bus *, int);
int lsf_prepaid_pci_setup_device(struct pci_dev *);
struct pci_dev *lsf_prepaid_pci_scan_single_device(struct pci_bus *, int);
/* Enter retains the existing factory mutex through actual constructor/list
 * publication. Every selected exit must leave; this is not a public token. */
int lsf_factory_device_pci_enter(unsigned int, unsigned int, unsigned int);
void lsf_factory_device_pci_leave(void);
int lsf_factory_device_pci_ready(unsigned int, unsigned int, unsigned int);
/* Positive ONE is an existing complete view; zero/outside and negative/unknown
 * cannot authorize dereference or establish a new birth. */
int lsf_factory_device_pci_owned(const void *, unsigned long);
void *lsf_factory_device_pci_allocate(unsigned int, unsigned int, unsigned int,
                                      unsigned long);
/* Return: zero is genuinely outside the arena, one is returned, negative is a
 * private/unknown interior birth retained on poison. NEVER normal-free <0. */
int lsf_factory_device_pci_return(const void *);
#endif
