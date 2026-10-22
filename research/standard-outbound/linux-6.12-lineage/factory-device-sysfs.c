/* SPDX-License-Identifier: GPL-2.0-only */
/* Same factory TU, after registration.c. No address is adopted; normal parents
 * cannot erase a private symlink target's actual PCI generation. */
int lsf_factory_device_sysfs_pair(const void *parent, const void *target,
    struct lsf_device_registration_source *copy)
{
    struct lsf_device_registration_source left, right;
    unsigned long flags;
    int a, b, result = -1;
    if (!copy)
        return -1;
    spin_lock_irqsave(&pool_lock, flags);
    a = lsf_factory_device_registration_lookup_locked(parent, LSF_DEVICE_KERNFS_NODE, &left);
    b = lsf_factory_device_registration_lookup_locked(target, LSF_DEVICE_KERNFS_NODE, &right);
    if (a < 0 || b < 0)
        goto poison;
    if (!a && !b) {
        result = 0;
        goto out;
    }
    if (a && b && (left.pci_slot != right.pci_slot ||
        left.pci_generation != right.pci_generation))
        goto poison;
    *copy = a ? left : right;
    if (!lsf_factory_device_registration_current_locked(*copy))
        goto poison;
    result = 1;
    goto out;
poison:
    lsf_factory_device_firmware_poison();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

char *lsf_factory_device_sysfs_name(struct lsf_device_registration_source source,
    const char *name)
{
    unsigned long bytes;
    char *copy;
    if (!name || lsf_factory_device_registration_current(source) != 1)
        return NULL;
    bytes = strnlen(name, NAME_MAX + 1u);
    if (!bytes || bytes > NAME_MAX)
        return NULL;
    copy = lsf_factory_device_registration_allocate(source, bytes + 1u,
        LSF_DEVICE_KERNFS_NAME);
    if (copy)
        memcpy(copy, name, bytes + 1u);
    return copy;
}

/* Actual failure/RCU cleanup carries both the caller's existing birth and the
 * member's existing birth. Unknown/mixed origins retain; never normal-free.
 * The node caller can already be QUEUED, but its original PCI must stay LIVE. */
int lsf_factory_device_sysfs_release(struct lsf_device_registration_source source,
    const void *address, unsigned int kind)
{
    struct lsf_device_registration_source member;
    struct lsf_prepaid_ticket ticket;
    unsigned long flags;
    int result = -1;
    spin_lock_irqsave(&pool_lock, flags);
    if ((source.kind != LSF_DEVICE_PCI && source.kind != LSF_DEVICE_KERNFS_NODE) ||
        (!lsf_factory_device_registration_record_locked(source, LSF_PREPAID_PUBLISHED) &&
         !lsf_factory_device_registration_record_locked(source, LSF_PREPAID_QUEUED)) ||
        (kind != LSF_DEVICE_KERNFS_NAME && kind != LSF_DEVICE_KERNFS_NODE) ||
        lsf_factory_device_registration_lookup_locked(address, kind, &member) != 1 ||
        source.pci_slot != member.pci_slot || source.pci_generation != member.pci_generation)
        goto poison;
    ticket = (struct lsf_prepaid_ticket){member.slot, member.generation};
    if (!lsf_device_queue(&factory.pool, factory.device->key, ticket, kind) ||
        !lsf_device_finish(&factory.pool, factory.device->key, ticket, kind))
        goto poison;
    result = 1;
    goto out;
poison:
    lsf_factory_device_firmware_poison();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    if (result == 1)
        lsf_factory_device_firmware_schedule();
    return result;
}

/* This finite constructor currently supports only genuine default ownership
 * and no inherited xattr. Attribute allocation/mutation is an explicit error,
 * not a successful no-op. Reads still take original no-attrs/ENODATA branches.
 * A surprising actual iattr pointer is unknown allocation origin and poisons. */
int lsf_factory_device_sysfs_iattrs(const struct kernfs_node *node, int alloc)
{
    struct lsf_device_registration_source source;
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_factory_device_registration_lookup_locked(node, LSF_DEVICE_KERNFS_NODE, &source);
    if (result < 0 || (result == 1 && node->iattr))
        goto poison;
    if (result == 1 && alloc)
        result = -1;
    goto out;
poison:
    result = -1;
    lsf_factory_device_firmware_poison();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
