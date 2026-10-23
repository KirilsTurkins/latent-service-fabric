/* SPDX-License-Identifier: GPL-2.0-only */
/* Explicit private representation of an ALREADY admitted original owner.
 * Shape/equality is not authority: each factory operation revalidates the real
 * birth under pool_lock. Application domain zero retains its original source. */
#ifndef LSF_STREAM_DEVICE_OWNER_CARRIER_H
#define LSF_STREAM_DEVICE_OWNER_CARRIER_H

enum lsf_factory_owner_domain {
    LSF_FACTORY_OWNER_APPLICATION = 0,
    LSF_FACTORY_OWNER_DEVICE = 1
};

#define LSF_DEVICE_SECURITY_AVC_NODE 0x115u
#define LSF_DEVICE_SECURITY_AVC_XPERMS 0x116u
#define LSF_DEVICE_SECURITY_AVC_DECISION 0x117u
#define LSF_DEVICE_SECURITY_AVC_DATA 0x118u
#define LSF_DEVICE_SECURITY_SIDCACHE 0x119u
#define LSF_DEVICE_SECURITY_AUDIT_STRING 0x11au
#define LSF_DEVICE_SECURITY_AUDIT_BUFFER 0x11bu
#define LSF_DEVICE_SECURITY_AUDIT_SKB 0x11cu
#define LSF_DEVICE_SECURITY_AUDIT_HEAD 0x11du

struct lsf_factory_context;
struct lsf_factory_blob {
    struct lsf_factory_context *context;
    struct lsf_prepaid_ticket ticket;
    unsigned int domain;
    struct lsf_device_registration_source device;
};
int lsf_factory_device_recipient_blob(struct lsf_device_registration_source,
    struct lsf_factory_blob *);

static inline int lsf_device_security_kind(unsigned int kind)
{
    return kind == LSF_DEVICE_SECURITY_AVC_NODE || kind == LSF_DEVICE_SECURITY_AVC_XPERMS ||
        kind == LSF_DEVICE_SECURITY_AVC_DECISION || kind == LSF_DEVICE_SECURITY_AVC_DATA ||
        kind == LSF_DEVICE_SECURITY_SIDCACHE || kind == LSF_DEVICE_SECURITY_AUDIT_STRING ||
        kind == LSF_DEVICE_SECURITY_AUDIT_BUFFER || kind == LSF_DEVICE_SECURITY_AUDIT_SKB ||
        kind == LSF_DEVICE_SECURITY_AUDIT_HEAD;
}

static inline int lsf_factory_blob_shape(struct lsf_factory_blob source)
{
    if (!source.ticket.slot || source.ticket.slot >= LSF_ALLOCATION_SLOTS ||
        !source.ticket.generation)
        return 0;
    if (source.domain == LSF_FACTORY_OWNER_APPLICATION)
        return source.context && !source.device.address && !source.device.kind &&
            !source.device.slot && !source.device.generation && !source.device.pci_slot &&
            !source.device.pci_generation;
    if (source.domain != LSF_FACTORY_OWNER_DEVICE || source.context ||
        !source.device.address || !source.device.pci_slot ||
        source.device.pci_slot >= LSF_ALLOCATION_SLOTS || !source.device.pci_generation ||
        source.ticket.slot != source.device.slot ||
        source.ticket.generation != source.device.generation)
        return 0;
    return source.device.kind == LSF_DEVICE_RECIPIENT_KIND_WORK ||
        lsf_device_security_kind(source.device.kind);
}

/* Unlike pointer-only context equality, two device carriers require the same
 * actual original PCI generation. Different live children of it can share its
 * owner, but no unknown domain or NULL application context can compare equal. */
static inline int lsf_factory_blob_same_owner(struct lsf_factory_blob a,
    struct lsf_factory_blob b)
{
    if (!lsf_factory_blob_shape(a) || !lsf_factory_blob_shape(b) || a.domain != b.domain)
        return 0;
    if (a.domain == LSF_FACTORY_OWNER_APPLICATION)
        return a.context == b.context;
    return a.device.pci_slot == b.device.pci_slot &&
        a.device.pci_generation == b.device.pci_generation;
}

#endif
