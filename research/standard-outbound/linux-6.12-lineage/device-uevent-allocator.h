/* SPDX-License-Identifier: GPL-2.0-only */
/* WIP explicit descendant publication, included after device-prepaid.h.
 * Caller holds the original pool_lock. This does not reopen root admission,
 * change either capacity, reuse any returned slot or forgive unknown origin. */
#ifndef LSF_STREAM_DEVICE_UEVENT_ALLOCATOR_H
#define LSF_STREAM_DEVICE_UEVENT_ALLOCATOR_H
static inline int lsf_device_uevent_publish(struct lsf_prepaid *pool,
    struct lsf_prepaid_key key, struct lsf_prepaid_ticket ticket,
    unsigned int kind, struct lsf_prepaid_ticket parent)
{
    struct lsf_prepaid_view *record, *original;
    if (kind != LSF_DEVICE_UEVENT_ENV && kind != LSF_DEVICE_UEVENT_PATH &&
        kind != LSF_DEVICE_UEVENT_SKB && kind != LSF_DEVICE_UEVENT_HEAD)
        return 0;
    record = lsf_device_record(pool, key, ticket, kind);
    original = lsf_device_record(pool, key, parent, LSF_DEVICE_PCI);
    if (!record || !original || record->deferred != LSF_PREPAID_PRIVATE ||
        original->deferred != LSF_PREPAID_PUBLISHED ||
        record->cache_bucket != parent.slot || record->cache_anchor != parent.generation)
        return 0;
    record->deferred = LSF_PREPAID_PUBLISHED;
    return 1;
}
#endif
