/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in authenticated SELinux netport.c. Original cache lock, policy,
 * lookup keys, bucket limit and RCU publication/removal stay authoritative. */

static void lsf_prepaid_netport_callback(struct rcu_head *head)
{
    struct sel_netport *port = container_of(head, struct sel_netport, rcu);
    struct lsf_factory_blob original;
    if (lsf_factory_blob_lookup(port, LSF_PREPAID_NETPORT, &original) == 1)
        lsf_factory_blob_finish(original, LSF_PREPAID_NETPORT);
    else
        lsf_factory_poison(NULL);
    /* Neither port nor head is read after returning its original view. */
}

/* Original cache lock is held and list_del_rcu already removed this node.
 * Outside the protected extent, the exact original kfree_rcu still runs.
 * An unknown in-extent record stays charged and never reaches kfree_rcu. */
static bool lsf_prepaid_netport_retire(struct sel_netport *port)
{
    int owned = lsf_factory_netport_queue(port);
    if (owned == 0)
        return false;
    if (owned == 1)
        call_rcu(&port->rcu, lsf_prepaid_netport_callback);
    return true;
}

void lsf_prepaid_netport_drain(struct lsf_factory_context *context)
{
    struct lsf_prepaid_ticket ticket;
    unsigned int slot, bucket;
    void *address;
    for (slot = 1; slot < LSF_ALLOCATION_SLOTS; ++slot) {
        /* Snapshot pool identity without holding any cache lock. */
        if (lsf_factory_netport_candidate(context, slot, &ticket, &bucket) != 1)
            continue;
        spin_lock_bh(&sel_netport_lock);
        /* Every cache remover queues the birth under this SAME lock. A
         * snapshot which raced eviction/flush is no longer PUBLISHED, so no
         * address is derived or dereferenced after that race. */
        if (lsf_factory_netport_current(context, ticket, bucket, &address)) {
            struct sel_netport *port = address;
            if (sel_netport_hash[bucket].size <= 0) {
                lsf_factory_poison(context);
            } else {
                list_del_rcu(&port->list);
                sel_netport_hash[bucket].size--;
                lsf_prepaid_netport_retire(port);
            }
        }
        spin_unlock_bh(&sel_netport_lock);
    }
    /* No allocation, cache-list walk, retry, grace-period guess or refund.
     * Pending callbacks and possible later genuine child births remain live. */
}
