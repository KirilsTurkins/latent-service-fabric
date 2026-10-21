/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in authenticated services.c. No ambient task/current owner lookup. */
void *lsf_prepaid_audit_dup(const struct lsf_factory_blob *source,
                           const void *bytes, u32 length)
{
    void *copy;
    if (!source || !bytes || !length || length > LSF_TCP_BYTES)
        return NULL;
    copy = lsf_factory_child_allocate(*source, length, LSF_PREPAID_AUDIT_STRING);
    if (copy)
        memcpy(copy, bytes, length);
    return copy;
}

int lsf_prepaid_audit_string_return(const void *address)
{
    struct lsf_factory_blob birth;
    int owned = lsf_factory_blob_lookup(address, LSF_PREPAID_AUDIT_STRING, &birth);
    if (owned == 1 && !lsf_factory_blob_finish(birth, LSF_PREPAID_AUDIT_STRING))
        return -1;
    /* Zero alone permits the unchanged normal allocator. Unknown in-extent
     * addresses and failed finishes retain the poisoned original owner. */
    return owned;
}

void lsf_prepaid_sidcache_drain(struct lsf_factory_context *context)
{
    struct lsf_prepaid_ticket ticket;
    struct selinux_policy *policy;
    unsigned int slot;
    lsf_u64 anchor;
    for (slot = 1; slot < LSF_ALLOCATION_SLOTS; ++slot) {
        if (lsf_factory_sidcache_candidate(context, slot, &ticket, &anchor) != 1)
            continue;
        rcu_read_lock();
        policy = rcu_dereference(selinux_state.policy);
        /* The copied anchor is compared only. It is never dereferenced.
         * Old tables are retired by their original policy destroy path,
         * which returns every private cache birth before address reuse. */
        if (policy && (lsf_u64)(unsigned long)policy->sidtab == anchor)
            lsf_prepaid_sidcache_detach(policy->sidtab, context, ticket);
        rcu_read_unlock();
    }
}
