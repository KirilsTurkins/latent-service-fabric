/* SPDX-License-Identifier: GPL-2.0-only */
/* WIP included AFTER the actual device_ktype/device_uevent_ops definitions in
 * drivers/base/core.c. These compare real source-selected objects; they never
 * replace mandatory callbacks with a successful stub. The original callbacks
 * still run after this preflight in actual kobject_uevent_env. */
int lsf_prepaid_device_uevent_ops_known(const struct kset_uevent_ops *candidate)
{
    return candidate == &device_uevent_ops;
}

int lsf_prepaid_device_uevent_device(const struct kobject *kobj)
{
    struct lsf_device_registration_source source;
    const struct device *dev;
    if (lsf_factory_device_uevent_kobject(kobj, &source) != 1 ||
        lsf_factory_device_uevent_current(source) != 1)
        return 0;
    /* Exact private PCI storage has been authenticated before kobj_to_dev.
     * Device nodes, DT, classes and arbitrary device-type/bus callbacks have
     * separate producer graphs and are Unsupported before any invocation. */
    if (kobj->ktype != &device_ktype || kobj->kset != devices_kset)
        return 0;
    dev = kobj_to_dev(kobj);
    if (dev->class || dev->devt || dev_of_node(dev) ||
        !lsf_prepaid_device_uevent_pci_bus_known(dev->bus) ||
        !lsf_prepaid_device_uevent_pci_type_known(dev->type))
        return 0;
    /* kobject_uevent_net_broadcast must take the genuine untagged branch,
     * without invoking an unclosed child-namespace callback first. Actual
     * devices_kset has no parent; refuse a changed topology rather than
     * silently redirecting or inventing an initial namespace certificate. */
    if ((kobj->parent && kobj->parent->ktype && kobj->parent->ktype->child_ns_type) ||
        !devices_kset || devices_kset->kobj.parent)
        return 0;
    return 1;
}
