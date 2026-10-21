/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in maintained lsm_audit.c, using its actual common formatter. */
int lsf_prepaid_common_lsm_audit(struct common_audit_data *data,
    void (*pre)(struct audit_buffer *, void *),
    int (*post)(struct audit_buffer *, void *, const struct lsf_factory_blob *),
    const struct lsf_factory_blob *source)
{
    struct audit_buffer *buffer;
    int error = 0;
    if (!data || !source)
        return -EINVAL;
    /* Only the approved IPv4 socket profile reaches this private branch.
     * Refuse other payload types before path/UNIX/etc formatters can allocate.
     * The normal common_lsm_audit and every other caller remain unchanged. */
    if (data->type != LSM_AUDIT_DATA_NONE &&
        (data->type != LSM_AUDIT_DATA_NET || !data->u.net ||
         (data->u.net->family && data->u.net->family != AF_INET) ||
         (data->u.net->sk && data->u.net->sk->sk_family != AF_INET)))
        return -EOPNOTSUPP;
    buffer = lsf_prepaid_audit_log_start(audit_context(), GFP_ATOMIC | __GFP_NOWARN,
                                         AUDIT_AVC, source, &error);
    if (!buffer)
        return error;
    if (pre)
        pre(buffer, data);
    dump_common_audit_data(buffer, data);
    if (post)
        error = post(buffer, data, source);
    /* Zero means original audit policy suppressed it, or a complete record
     * entered the real queue. It never claims delivery, reader retirement or
     * free of the SKB transferred out of this formatter. */
    return lsf_prepaid_audit_log_end(buffer, error);
}
