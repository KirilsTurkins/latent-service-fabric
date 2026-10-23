/* SPDX-License-Identifier: GPL-2.0-only */
/* Included after the actual recipient/security helpers. Both original WORK
 * and held packet births must agree BEFORE any packet/socket field is read.
 * This is not packet adoption and is never used after queue transfer/free. */
#include <linux/netlink.h>
#include <net/sock.h>
#include <net/lsf_stream_device_notification.h>
int lsf_factory_device_recipient_packet(struct lsf_device_registration_source source,
    const struct sock *recipient, const struct sk_buff *skb)
{
    struct lsf_device_registration_source packet;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!recipient || !lsf_factory_device_recipient_current_locked(source, recipient) ||
        lsf_factory_device_uevent_lookup_locked(skb, LSF_DEVICE_UEVENT_SKB, &packet) != 1 ||
        packet.pci_slot != source.pci_slot || packet.pci_generation != source.pci_generation)
        goto poison;
    /* The actual source caller holds the recipient reference/table-user
     * extent and this pre-publication packet. These fields are not origin. */
    if (recipient->sk_family != AF_NETLINK || recipient->sk_protocol != NETLINK_KOBJECT_UEVENT)
        goto poison;
    result = 1;
    goto out;
poison:
    lsf_factory_device_firmware_poison();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
