/* SPDX-License-Identifier: GPL-2.0-only */
/* Included after the maintained audit_buffer definition. Its extra status is
 * part of the actual charged formatter allocation, not a side-table/quota. */
struct lsf_prepaid_audit_envelope {
    struct audit_buffer buffer;
    int error;
};

static int lsf_prepaid_audit_buffer_free(struct audit_buffer *buffer)
{
    struct lsf_factory_blob birth;
    int owned = lsf_factory_blob_lookup(buffer, LSF_PREPAID_AUDIT_BUFFER, &birth);
    if (owned == 1) {
        /* Preserve original SKB users/dataref and socket destructor ordering.
         * Its birth remains independently live after formatter retirement. */
        kfree_skb(buffer->skb);
        if (!lsf_factory_blob_finish(birth, LSF_PREPAID_AUDIT_BUFFER))
            return -1;
    }
    return owned;
}

static void lsf_prepaid_audit_error(struct audit_buffer *buffer, int error)
{
    struct lsf_factory_blob birth;
    if (lsf_factory_blob_lookup(buffer, LSF_PREPAID_AUDIT_BUFFER, &birth) == 1) {
        struct lsf_prepaid_audit_envelope *envelope = (void *)buffer;
        if (!envelope->error)
            envelope->error = error < 0 ? error : -EIO;
    }
}

static struct audit_buffer *lsf_prepaid_audit_buffer_alloc(
    struct audit_context *context, gfp_t priority, int type,
    const struct lsf_factory_blob *source)
{
    struct lsf_prepaid_audit_envelope *envelope;
    struct audit_buffer *buffer;
    if (!source)
        return NULL;
    envelope = lsf_factory_child_allocate(*source, sizeof(*envelope),
                                          LSF_PREPAID_AUDIT_BUFFER);
    if (!envelope)
        return NULL;
    buffer = &envelope->buffer;
    buffer->skb = lsf_prepaid_audit_skb_new(*source, nlmsg_total_size(AUDIT_BUFSIZ));
    if (!buffer->skb || !nlmsg_put(buffer->skb, 0, 0, type, 0, 0)) {
        lsf_prepaid_audit_buffer_free(buffer);
        return NULL;
    }
    buffer->ctx = context;
    buffer->gfp_mask = priority;
    return buffer;
}
