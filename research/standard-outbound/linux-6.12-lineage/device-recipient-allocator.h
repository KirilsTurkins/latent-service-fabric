/* SPDX-License-Identifier: GPL-2.0-only */
/* Caller holds the original pool_lock. Uses the SAME bank and fixed records. */
#ifndef LSF_STREAM_DEVICE_RECIPIENT_ALLOCATOR_H
#define LSF_STREAM_DEVICE_RECIPIENT_ALLOCATOR_H

static inline int lsf_device_recipient_publish(struct lsf_prepaid *pool,
    struct lsf_prepaid_key key, struct lsf_prepaid_ticket ticket,
    unsigned int kind, struct lsf_prepaid_ticket parent)
{
    struct lsf_prepaid_view *record, *original;
    if (kind != LSF_DEVICE_RECIPIENT_WORK && kind != LSF_DEVICE_RECIPIENT_SIGQUEUE)
        return 0;
    record = lsf_device_record(pool, key, ticket, kind);
    original = lsf_device_record(pool, key, parent, LSF_DEVICE_PCI);
    if (!record || !original || record->deferred != LSF_PREPAID_PRIVATE ||
        original->deferred != LSF_PREPAID_PUBLISHED ||
        record->cache_bucket != parent.slot || record->cache_anchor != parent.generation)
        return 0;
    /* A real already-admitted descendant may finish its mandatory tail after
     * root close. This does not reopen constructor/root allocation authority. */
    record->deferred = LSF_PREPAID_PUBLISHED;
    return 1;
}

#endif
