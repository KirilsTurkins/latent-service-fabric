/* SPDX-License-Identifier: GPL-2.0-only */
/* Original find_vqs owns these three temporary arrays synchronously. Their
 * actual births charge the SAME fixed original arena before initialization.
 * Exhaustion refuses construction; no private fallback to kcalloc exists. */
#include <net/lsf_stream_material_geometry_private.h>

static int lsf_stream_find_vqs_geometry(struct lsf_stream_net_material_geometry *g)
{
    return !lsf_prepaid_stream_net_material_geometry(g) &&
        g->vqs_bytes && g->vqs_bytes <= ULONG_MAX - 63u &&
        g->vqs_info_bytes && g->vqs_info_bytes <= ULONG_MAX - 63u &&
        g->ctx_bytes && g->ctx_bytes <= ULONG_MAX - 63u;
}

static int lsf_stream_find_vqs_record_locked(struct lsf_stream_rx_state *state,
    const void *address, unsigned int kind, u64 bytes, struct lsf_prepaid_ticket *out)
{
    unsigned long base = (unsigned long)page_address(factory.pages), at = (unsigned long)address;
    struct lsf_prepaid_view *record;
    unsigned int i;
    lockdep_assert_held(&pool_lock);
    if (!state->virtio || !lsf_stream_rx_address_locked(address)) return 0;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->offset != at - base) continue;
        if (record->bytes != ((bytes + 63u) & ~63ull) || record->kind != kind ||
            record->deferred != LSF_PREPAID_PRIVATE ||
            !lsf_device_record(&factory.pool, state->owner,
                (struct lsf_prepaid_ticket){i, record->generation}, kind)) return 0;
        if (!lsf_device_record(&factory.pool, state->owner,
                (struct lsf_prepaid_ticket){record->cache_bucket, record->cache_anchor},
                LSF_DEVICE_VIRTIO)) return 0;
        if ((void *)(base + factory.pool.records[record->cache_bucket].offset) != state->virtio)
            return 0;
        *out = (struct lsf_prepaid_ticket){i, record->generation};
        return 1;
    }
    return 0;
}

int lsf_factory_stream_find_vqs_take(struct virtio_device *vdev, unsigned int count,
    bool control, bool large, bool mergeable, struct lsf_stream_find_vqs_views *views)
{
    struct lsf_stream_net_material_geometry g;
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_ticket parent = {}, ticket;
    struct lsf_prepaid_view *record;
    unsigned long flags, base;
    unsigned int i;
    u64 offsets[3], bytes[3], alignments[3];
    const unsigned int kinds[3] = {LSF_DEVICE_FIND_VQS, LSF_DEVICE_FIND_VQS_INFO,
        LSF_DEVICE_FIND_VQS_CTX};
    int result = -EOPNOTSUPP;
    if (!views) return -EINVAL;
    *views = (struct lsf_stream_find_vqs_views){};
    if (!lsf_factory_selected_consumer()) return 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (vdev && !lsf_stream_rx_address_locked(vdev)) {
        result = lsf_stream_rx_address_locked(vdev->dev.parent) ? -EOPNOTSUPP : 0;
        goto out;
    }
    if (count != 2 || control || large || mergeable || !lsf_stream_find_vqs_geometry(&g))
        goto out;
    bytes[0] = g.vqs_bytes; bytes[1] = g.vqs_info_bytes; bytes[2] = g.ctx_bytes;
    alignments[0] = g.vqs_alignment; alignments[1] = g.vqs_info_alignment;
    alignments[2] = g.ctx_alignment;
    state = lsf_stream_rx_current_locked();
    if (!state || state->virtio != vdev || state->closing || state->stopped ||
        !lsf_stream_rx_address_locked(vdev)) goto out;
    base = (unsigned long)page_address(factory.pages);
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->offset == (unsigned long)vdev - base &&
            lsf_device_record(&factory.pool, state->owner,
                (struct lsf_prepaid_ticket){i, record->generation}, LSF_DEVICE_VIRTIO)) {
            parent = (struct lsf_prepaid_ticket){i, record->generation}; break;
        }
    }
    if (!parent.slot) goto out;
    for (i = 0; i < 3; ++i) {
        result = lsf_stream_constructor_allocate_locked(state, kinds[i], parent,
            bytes[i], alignments[i], &ticket, &offsets[i]);
        if (result != 1) {
            /* An earlier claimed row remains paid. No partial tuple escapes. */
            state->poisoned = factory.pool.poisoned = 1;
            WRITE_ONCE(factory.uncertain, 1); goto out;
        }
        memset((void *)(base + offsets[i]), 0, bytes[i]);
    }
    *views = (struct lsf_stream_find_vqs_views){
        (void *)(base + offsets[0]), (void *)(base + offsets[1]), (void *)(base + offsets[2])};
    result = 1;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_find_vqs_return(struct virtio_device *vdev,
    struct lsf_stream_find_vqs_views *views)
{
    struct lsf_stream_net_material_geometry g;
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_ticket tickets[3];
    void *addresses[3];
    u64 bytes[3];
    const unsigned int kinds[3] = {LSF_DEVICE_FIND_VQS, LSF_DEVICE_FIND_VQS_INFO,
        LSF_DEVICE_FIND_VQS_CTX};
    unsigned long flags;
    unsigned int i;
    int result = -EIO;
    if (!views || !lsf_stream_find_vqs_geometry(&g)) return result;
    addresses[0] = views->vqs; addresses[1] = views->infos; addresses[2] = views->ctx;
    bytes[0] = g.vqs_bytes; bytes[1] = g.vqs_info_bytes; bytes[2] = g.ctx_bytes;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    if (!state || state->virtio != vdev) goto out;
    for (i = 0; i < 3; ++i)
        if (!lsf_stream_find_vqs_record_locked(state, addresses[i], kinds[i], bytes[i], &tickets[i]))
            goto poison;
    /* Caller cleared all actual driver aliases before entering this helper.
     * Clear the final tuple before the original records become RETURNED. */
    *views = (struct lsf_stream_find_vqs_views){};
    for (i = 3; i-- > 0;)
        if (!lsf_device_finish(&factory.pool, state->owner, tickets[i], kinds[i])) goto poison;
    result = 1; goto out;
poison:
    state->poisoned = factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
out:
    if (result != 1) {
        factory.pool.poisoned = 1;
        WRITE_ONCE(factory.uncertain, 1);
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
