/* SPDX-License-Identifier: GPL-2.0-only */
/* Internal device-domain cache metadata. Caller holds the SAME pool_lock.
 * cache_bucket/anchor remain immutable PCI ancestry; security_cache_* is the
 * separate real cache identity, never an adoption certificate or free proof. */
#ifndef LSF_STREAM_DEVICE_SECURITY_PREPAID_H
#define LSF_STREAM_DEVICE_SECURITY_PREPAID_H

static inline unsigned int lsf_device_security_physical_kind(unsigned int kind)
{
    switch (kind) {
    case LSF_PREPAID_AVC_NODE: return LSF_DEVICE_SECURITY_AVC_NODE;
    case LSF_PREPAID_AVC_XPERMS: return LSF_DEVICE_SECURITY_AVC_XPERMS;
    case LSF_PREPAID_AVC_DECISION: return LSF_DEVICE_SECURITY_AVC_DECISION;
    case LSF_PREPAID_AVC_DATA: return LSF_DEVICE_SECURITY_AVC_DATA;
    case LSF_PREPAID_SIDCACHE: return LSF_DEVICE_SECURITY_SIDCACHE;
    case LSF_PREPAID_AUDIT_STRING: return LSF_DEVICE_SECURITY_AUDIT_STRING;
    case LSF_PREPAID_AUDIT_BUFFER: return LSF_DEVICE_SECURITY_AUDIT_BUFFER;
    case LSF_PREPAID_AUDIT_SKB: return LSF_DEVICE_SECURITY_AUDIT_SKB;
    case LSF_PREPAID_AUDIT_HEAD: return LSF_DEVICE_SECURITY_AUDIT_HEAD;
    default: return 0;
    }
}

static inline struct lsf_prepaid_view *lsf_device_security_record(
    struct lsf_prepaid *pool, struct lsf_prepaid_key key,
    struct lsf_device_registration_source source)
{
    struct lsf_prepaid_ticket ticket = {source.slot, source.generation};
    struct lsf_prepaid_ticket parent = {source.pci_slot, source.pci_generation};
    struct lsf_prepaid_view *record, *pci;
    if (source.kind != LSF_DEVICE_RECIPIENT_KIND_WORK && !lsf_device_security_kind(source.kind))
        return 0;
    record = lsf_device_record(pool, key, ticket, source.kind);
    pci = lsf_device_record(pool, key, parent, LSF_DEVICE_PCI);
    if (!record || !pci || !source.address || pci->deferred != LSF_PREPAID_PUBLISHED ||
        record->cache_bucket != parent.slot || record->cache_anchor != parent.generation ||
        record->deferred > LSF_PREPAID_PUBLISHED)
        return 0;
    if (source.kind == LSF_DEVICE_SECURITY_AVC_NODE && record->deferred != LSF_PREPAID_PRIVATE) {
        if (!record->security_cache_location || record->security_cache_location > 512u ||
            record->security_cache_identity)
            return 0;
    } else if (source.kind == LSF_DEVICE_SECURITY_SIDCACHE && record->deferred != LSF_PREPAID_PRIVATE) {
        if (record->security_cache_location || !record->security_cache_identity)
            return 0;
    } else if (record->security_cache_location || record->security_cache_identity) {
        return 0;
    }
    return record;
}

static inline int lsf_device_security_publish(struct lsf_prepaid *pool,
    struct lsf_prepaid_key key, struct lsf_device_registration_source source,
    unsigned int location, lsf_u64 identity)
{
    struct lsf_prepaid_view *record = lsf_device_security_record(pool, key, source);
    if (!record || record->deferred != LSF_PREPAID_PRIVATE ||
        record->security_cache_location || record->security_cache_identity)
        return 0;
    if (source.kind == LSF_DEVICE_SECURITY_AVC_NODE) {
        if (location >= 512u || identity)
            return 0;
        record->security_cache_location = location + 1u;
    } else if (source.kind == LSF_DEVICE_SECURITY_SIDCACHE) {
        if (location || !identity)
            return 0;
        record->security_cache_identity = identity;
    } else {
        return 0;
    }
    record->deferred = LSF_PREPAID_PUBLISHED;
    return 1;
}

static inline int lsf_device_security_queue(struct lsf_prepaid *pool,
    struct lsf_prepaid_key key, struct lsf_device_registration_source source)
{
    struct lsf_prepaid_view *record = lsf_device_security_record(pool, key, source);
    if (!record || record->deferred != LSF_PREPAID_PUBLISHED)
        return 0;
    if (source.kind == LSF_DEVICE_SECURITY_AVC_NODE) {
        if (!record->security_cache_location || record->security_cache_location > 512u ||
            record->security_cache_identity)
            return 0;
    } else if (source.kind == LSF_DEVICE_SECURITY_SIDCACHE) {
        if (record->security_cache_location || !record->security_cache_identity)
            return 0;
    } else {
        return 0;
    }
    return lsf_device_queue(pool, key,
        (struct lsf_prepaid_ticket){source.slot, source.generation}, source.kind);
}

#endif
