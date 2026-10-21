/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in exact maintained avc.c. This graph walk is bounded by the SAME
 * 256 birth records. It validates the complete graph before any return; no
 * object owns a second quota, pin table, fallback allocator or new executor. */
struct lsf_avc_walk {
    struct lsf_factory_context *context;
    lsf_u64 seen[(LSF_ALLOCATION_SLOTS + 63u) / 64u];
};

static bool lsf_prepaid_avc_member(struct lsf_avc_walk *walk,
    const void *address, unsigned int kind, unsigned long bytes,
    struct lsf_factory_blob *copy)
{
    unsigned int word, bit;
    if (lsf_factory_avc_member(address, kind, bytes, copy) != 1 ||
        copy->context != walk->context || !copy->ticket.slot ||
        copy->ticket.slot >= LSF_ALLOCATION_SLOTS)
        return false;
    word = copy->ticket.slot / 64u;
    bit = copy->ticket.slot % 64u;
    if (walk->seen[word] & ((lsf_u64)1u << bit))
        return false;
    walk->seen[word] |= (lsf_u64)1u << bit;
    return true;
}

static bool lsf_prepaid_avc_decision_graph(struct avc_xperms_decision_node *node,
    struct lsf_avc_walk *walk)
{
    struct lsf_factory_blob copy;
    if (!lsf_prepaid_avc_member(walk, node, LSF_PREPAID_AVC_DECISION,
                               sizeof(*node), &copy))
        return false;
    /* Allocation failures can leave nonnull children before used is assigned.
     * The original destructor follows these pointers, not the used mask. */
    if (node->xpd.allowed && !lsf_prepaid_avc_member(walk, node->xpd.allowed,
        LSF_PREPAID_AVC_DATA, sizeof(*node->xpd.allowed), &copy))
        return false;
    if (node->xpd.auditallow && !lsf_prepaid_avc_member(walk, node->xpd.auditallow,
        LSF_PREPAID_AVC_DATA, sizeof(*node->xpd.auditallow), &copy))
        return false;
    if (node->xpd.dontaudit && !lsf_prepaid_avc_member(walk, node->xpd.dontaudit,
        LSF_PREPAID_AVC_DATA, sizeof(*node->xpd.dontaudit), &copy))
        return false;
    return true;
}

static bool lsf_prepaid_avc_xperms_graph(struct avc_xperms_node *node,
    struct lsf_avc_walk *walk)
{
    struct lsf_factory_blob copy;
    struct list_head *cursor, *previous;
    if (!node)
        return true;
    if (!lsf_prepaid_avc_member(walk, node, LSF_PREPAID_AVC_XPERMS,
                               sizeof(*node), &copy))
        return false;
    cursor = node->xpd_head.next;
    previous = &node->xpd_head;
    while (cursor != &node->xpd_head) {
        struct avc_xperms_decision_node *decision;
        if (!cursor)
            return false;
        decision = list_entry(cursor, struct avc_xperms_decision_node, xpd_list);
        /* Validate its original birth BEFORE reading any linked-list fields.
         * The fixed seen set rejects aliases, non-head cycles and long lists. */
        if (!lsf_prepaid_avc_decision_graph(decision, walk) ||
            decision->xpd_list.prev != previous)
            return false;
        previous = cursor;
        cursor = decision->xpd_list.next;
    }
    return node->xpd_head.prev == previous;
}

static int lsf_prepaid_avc_node_graph(struct avc_node *node,
    struct lsf_factory_blob *copy)
{
    struct lsf_avc_walk walk = {0};
    int owned = lsf_factory_avc_member(node, LSF_PREPAID_AVC_NODE,
                                       sizeof(*node), copy);
    if (owned != 1)
        return owned;
    walk.context = copy->context;
    walk.seen[copy->ticket.slot / 64u] |=
        (lsf_u64)1u << (copy->ticket.slot % 64u);
    if (!lsf_prepaid_avc_xperms_graph(node->ae.xp_node, &walk)) {
        lsf_factory_poison(copy->context);
        return -1;
    }
    return 1;
}

/* All addresses below have passed the complete, same-context graph walk.
 * Copy the original ticket before returning each child; never read it again
 * after finish. Backing/cursor is not reused or refunded here. */
static void lsf_prepaid_avc_finish(const void *address, unsigned int kind)
{
    struct lsf_factory_blob copy;
    if (lsf_factory_blob_lookup(address, kind, &copy) != 1 ||
        !lsf_factory_blob_finish(copy, kind))
        lsf_factory_poison(NULL);
}

static void lsf_prepaid_avc_decision_finish(struct avc_xperms_decision_node *node)
{
    if (node->xpd.allowed)
        lsf_prepaid_avc_finish(node->xpd.allowed, LSF_PREPAID_AVC_DATA);
    if (node->xpd.auditallow)
        lsf_prepaid_avc_finish(node->xpd.auditallow, LSF_PREPAID_AVC_DATA);
    if (node->xpd.dontaudit)
        lsf_prepaid_avc_finish(node->xpd.dontaudit, LSF_PREPAID_AVC_DATA);
    lsf_prepaid_avc_finish(node, LSF_PREPAID_AVC_DECISION);
}

static void lsf_prepaid_avc_xperms_finish(struct avc_xperms_node *node)
{
    struct avc_xperms_decision_node *decision, *next;
    if (!node)
        return;
    list_for_each_entry_safe(decision, next, &node->xpd_head, xpd_list) {
        list_del(&decision->xpd_list);
        lsf_prepaid_avc_decision_finish(decision);
    }
    lsf_prepaid_avc_finish(node, LSF_PREPAID_AVC_XPERMS);
}

static bool lsf_prepaid_avc_decision_free(struct avc_xperms_decision_node *node)
{
    struct lsf_factory_blob copy;
    struct lsf_avc_walk walk = {0};
    int owned = lsf_factory_avc_member(node, LSF_PREPAID_AVC_DECISION,
                                       sizeof(*node), &copy);
    if (!owned)
        return false;
    if (owned == 1) {
        walk.context = copy.context;
        if (lsf_prepaid_avc_decision_graph(node, &walk))
            lsf_prepaid_avc_decision_finish(node);
        else
            lsf_factory_poison(copy.context);
    }
    return true;
}

static bool lsf_prepaid_avc_xperms_free(struct avc_xperms_node *node)
{
    struct lsf_factory_blob copy;
    struct lsf_avc_walk walk = {0};
    int owned;
    if (!node)
        return false;
    owned = lsf_factory_avc_member(node, LSF_PREPAID_AVC_XPERMS,
                                   sizeof(*node), &copy);
    if (!owned)
        return false;
    if (owned == 1) {
        walk.context = copy.context;
        if (lsf_prepaid_avc_xperms_graph(node, &walk))
            lsf_prepaid_avc_xperms_finish(node);
        else
            lsf_factory_poison(copy.context);
    }
    return true;
}

static bool lsf_prepaid_avc_node_free(struct avc_node *node, bool callback)
{
    struct lsf_factory_blob copy;
    int owned = lsf_prepaid_avc_node_graph(node, &copy);
    if (!owned)
        return false;
    if (owned == 1 && lsf_factory_avc_phase(copy,
        callback ? LSF_PREPAID_QUEUED : LSF_PREPAID_PRIVATE)) {
        lsf_prepaid_avc_xperms_finish(node->ae.xp_node);
        lsf_factory_blob_finish(copy, LSF_PREPAID_AVC_NODE);
    } else {
        lsf_factory_poison(NULL);
    }
    return true;
}

static int lsf_prepaid_avc_node_queue(struct avc_node *node)
{
    struct lsf_factory_blob copy;
    int owned = lsf_prepaid_avc_node_graph(node, &copy);
    if (owned == 1)
        owned = lsf_factory_avc_queue(node);
    return owned;
}

static int lsf_prepaid_avc_node_publish(struct avc_node *node, unsigned int bucket,
    const struct lsf_factory_blob *source)
{
    struct lsf_factory_blob copy;
    if (!source || lsf_prepaid_avc_node_graph(node, &copy) != 1 ||
        copy.context != source->context ||
        lsf_factory_avc_publish(node, bucket) != 1)
        return -EOPNOTSUPP;
    return 0;
}

static int lsf_prepaid_avc_node_replace(struct avc_node *node, struct avc_node *old,
    unsigned int bucket, const struct lsf_factory_blob *source)
{
    struct lsf_factory_blob copy, prior;
    int owned;
    if (!source || lsf_prepaid_avc_node_graph(node, &copy) != 1 ||
        copy.context != source->context)
        return -EOPNOTSUPP;
    owned = lsf_prepaid_avc_node_graph(old, &prior);
    if (owned < 0 || lsf_factory_avc_replace(node, old, bucket) != 1)
        return -EOPNOTSUPP;
    hlist_replace_rcu(&old->list, &node->list);
    call_rcu(&old->rhead, avc_node_free);
    atomic_dec(&selinux_avc.avc_cache.active_nodes);
    return 0;
}

void lsf_prepaid_avc_drain(struct lsf_factory_context *context)
{
    struct lsf_prepaid_ticket ticket;
    unsigned int slot, bucket;
    unsigned long flags;
    void *address;
    for (slot = 1; slot < LSF_ALLOCATION_SLOTS; ++slot) {
        if (lsf_factory_avc_candidate(context, slot, &ticket, &bucket) != 1)
            continue;
        spin_lock_irqsave(&selinux_avc.avc_cache.slots_lock[bucket], flags);
        if (lsf_factory_avc_current(context, ticket, bucket, &address))
            avc_node_delete(address);
        spin_unlock_irqrestore(&selinux_avc.avc_cache.slots_lock[bucket], flags);
    }
    /* A finite detach is not an RCU grace period or final-free certificate.
     * Late genuine descendants and all uncertain births remain charged. */
}
