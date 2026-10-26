/* SPDX-License-Identifier: GPL-2.0-only */
/* Included after the exact completed RX state/core projection. */
/* Namespace dispatch only: 1 proves the exact live original RX loan; 2 means
 * another private address and grants NO ownership (the original namespace must
 * still validate it); 0 is outside this selected bank. Unknown RX is negative.
 * Never adopt a pointer, mutate loan state or return physical backing here. */
int lsf_factory_stream_rx_skb_kind(const void *address, unsigned int which)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *record;
    struct lsf_prepaid_ticket ticket;
    unsigned long flags, base;
    u64 bytes;
    unsigned int i, kind;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_stream_rx_address_locked(address)) goto out;
    result = -1;
    state = lsf_stream_rx_current_locked();
    if (!state || which > LSF_STREAM_SKB_HEADER ||
        state->root.slot != factory.device->root.slot ||
        state->root.generation != factory.device->root.generation ||
        !lsf_device_record(&factory.pool, state->owner, state->root, LSF_DEVICE_ROOT))
        goto out;
    base = (unsigned long)page_address(factory.pages);
    result = 2;
    for (i = 0; i < LSF_STREAM_RX_DESCRIPTORS; ++i) {
        if (state->heads[i].address == address) {
            result = -1;
            if (which != LSF_STREAM_SKB_HEAD || !state->heads[i].incarnation ||
                state->heads[i].data_returned) goto out;
            ticket = state->heads[i].ticket;
            kind = LSF_DEVICE_RX_HEAD; bytes = state->geometry.rx_head_bytes;
            goto check;
        }
        if (state->headers[i].address == address) {
            struct lsf_stream_rx_header *header = &state->headers[i];
            result = -1;
            if (which != LSF_STREAM_SKB_HEADER || header->borrowed != 1 ||
                !header->incarnation || header->head_slot >= LSF_STREAM_RX_DESCRIPTORS ||
                header->incarnation != state->heads[header->head_slot].incarnation)
                goto out;
            ticket = header->ticket;
            kind = LSF_DEVICE_RX_HEADER; bytes = state->geometry.rx_header_bytes;
            goto check;
        }
    }
    goto out;
check:
    record = lsf_device_record(&factory.pool, state->owner, ticket, kind);
    if (!record || record->deferred != LSF_PREPAID_PUBLISHED ||
        !bytes || bytes > U64_MAX - 63 || record->bytes != ((bytes + 63) & ~63ull) ||
        record->offset != (unsigned long)address - base ||
        record->cache_bucket != state->state.slot ||
        record->cache_anchor != state->state.generation)
        goto out;
    result = 1;
out:
    if (result < 0) {
        factory.pool.poisoned = 1;
        WRITE_ONCE(factory.uncertain, 1);
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}
