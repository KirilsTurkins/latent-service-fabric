/* SPDX-License-Identifier: GPL-2.0-only */
/* Built-in preparation-only image. The misc facility and its VFS/kernfs refs
 * belong to the original OS/platform prerequisite, NOT the later Node escrow.
 * No socket consumer, NodeFunding or NodeRetired issuer is installed here. */
#include <linux/cpu.h>
#include <linux/init.h>
#include <linux/pci.h>
#include <net/lsf_stream_device_private.h>

#if !defined(LSF_STREAM_NODE_CAPACITY_IMAGE) || !defined(LSF_STREAM_NODE_BOOTSTRAP_IMAGE)
#error "node boot requires the complete capacity-v2 image"
#endif
#if !defined(LSF_NODE_BOOT_PROFILE) || LSF_NODE_BOOT_PROFILE != 0x4c534e43u
#error "node boot requires its fixed Kbuild profile"
#endif

static bool lsf_node_boot_registered;

/* Read only the selected, still-unregistered slot. The actual PCI config read
 * occurs under the native rescan lock; a missing bus/device, a read error, an
 * unexpected identity or an existing pci_dev refuses the preparation entry.
 * This does not create or bind a PCI device, enable IRQs or prove constructor
 * funding. The fresh hosted owner checks the one actual console observation. */
static bool lsf_node_boot_selected_pci(void)
{
    struct pci_bus *bus;
    struct pci_dev *existing;
    u32 identity;
    bool found = false;

    pci_lock_rescan_remove();
    bus = pci_find_bus(LSF_DEVICE_PCI_DOMAIN, LSF_DEVICE_PCI_BUS);
    if (!bus || (unsigned int)pci_domain_nr(bus) != LSF_DEVICE_PCI_DOMAIN ||
        bus->number != LSF_DEVICE_PCI_BUS)
        goto out;
    existing = pci_get_slot(bus, LSF_DEVICE_PCI_DEVFN);
    if (existing) {
        pci_dev_put(existing);
        goto out;
    }
    if (pci_bus_read_config_dword(bus, LSF_DEVICE_PCI_DEVFN, PCI_VENDOR_ID,
                                  &identity) != PCIBIOS_SUCCESSFUL ||
        (identity & 0xffffu) != LSF_DEVICE_PCI_VENDOR ||
        (identity >> 16) != LSF_DEVICE_PCI_DEVICE)
        goto out;
    pr_notice("LSFQ35PCICONFIG1 bdf=%04x:%02x:%02x.%u vendor=%04x device=%04x unregistered=1\n",
        (unsigned int)pci_domain_nr(bus), (unsigned int)bus->number,
        PCI_SLOT(LSF_DEVICE_PCI_DEVFN), PCI_FUNC(LSF_DEVICE_PCI_DEVFN),
        identity & 0xffffu, identity >> 16);
    found = true;
out:
    pci_unlock_rescan_remove();
    return found;
}

static bool lsf_node_boot_entry_ready(void)
{
    /* The qualified machine has maxcpus=1, no CPU/device hotplug and no vIOMMU.
     * CONFIG_NR_CPUS is deliberately not interpreted as observed topology.
     * The hosted image owner separately authenticates QEMU/machine/KVM/argv. */
    return READ_ONCE(lsf_node_boot_registered) && num_possible_cpus() == 1 &&
        num_online_cpus() == 1 && cpu_possible(0) && cpu_online(0) &&
        lsf_node_boot_selected_pci();
}

static int __init lsf_node_boot_register(void)
{
    int error = -EOPNOTSUPP;

    cpus_read_lock();
    if (num_possible_cpus() != 1 || num_online_cpus() != 1 ||
        !cpu_possible(0) || !cpu_online(0))
        goto out;
    /* This registers only the distinct compiled Node fops. The ordinary mint,
     * create/connect and IRQ consumer remain absent. No Node exists yet and
     * registration is never retrospectively entered in its future records. */
    error = misc_register(&lsf_factory_device);
    if (!error)
        WRITE_ONCE(lsf_node_boot_registered, true);
out:
    cpus_read_unlock();
    return error;
}
device_initcall(lsf_node_boot_register);
