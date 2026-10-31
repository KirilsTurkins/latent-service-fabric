/* SPDX-License-Identifier: GPL-2.0-only */
/* Built-in preparation-only image. The misc facility and its VFS/kernfs refs
 * belong to the original OS/platform prerequisite, NOT the later Node escrow.
 * No socket consumer, NodeFunding or NodeRetired issuer is installed here. */
#include <linux/cpu.h>
#include <linux/init.h>

#if !defined(LSF_STREAM_NODE_CAPACITY_IMAGE) || !defined(LSF_STREAM_NODE_BOOTSTRAP_IMAGE)
#error "node boot requires the complete capacity-v2 image"
#endif
#if !defined(LSF_NODE_BOOT_PROFILE) || LSF_NODE_BOOT_PROFILE != 0x4c534e43u
#error "node boot requires its fixed Kbuild profile"
#endif

static bool lsf_node_boot_registered;

static bool lsf_node_boot_entry_ready(void)
{
    /* The qualified machine has maxcpus=1, no CPU/device hotplug and no vIOMMU.
     * CONFIG_NR_CPUS is deliberately not interpreted as observed topology.
     * The hosted image owner separately authenticates QEMU/machine/KVM/argv. */
    return READ_ONCE(lsf_node_boot_registered) && num_possible_cpus() == 1 &&
        num_online_cpus() == 1 && cpu_possible(0) && cpu_online(0);
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
