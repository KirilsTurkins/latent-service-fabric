/* SPDX-License-Identifier: GPL-2.0-only */
/* Included after the original Node record helpers. One real native page is
 * charged before allocation/zeroing; each nonoverlapping typed view takes an
 * immutable ORIGINAL record before its native ctor or first field write.
 * Pages and consumed views are never refunded, reused, reparented or SLUB-freed.
 */
void *lsf_node_capacity_small_take(struct lsf_node_capacity *owner,
    enum lsf_node_capacity_role role, unsigned long bytes, unsigned long alignment)
{
    struct lsf_node_parent *node;
    struct lsf_node_capacity *actual;
    struct lsf_prepaid_view *page_record, *record, *prior;
    struct lsf_prepaid_context *context;
    unsigned long flags, stride, offset, at, end;
    unsigned int page_slot, slot, scan;
    void *page = NULL, *address = NULL;
    int allocating = 0;

    if (!lsf_node_small_role(role) || !in_task() || in_atomic() || irqs_disabled())
        return NULL;
    spin_lock_irqsave(&pool_lock, flags);
    node = lsf_node_capacity_parent_locked(owner);
    if (!lsf_node_capacity_open_locked(node) || !owner->started ||
        bytes != owner->extent[role].bytes || alignment != owner->extent[role].alignment ||
        !bytes || bytes > PAGE_SIZE || !is_power_of_2(alignment) || alignment > 64 ||
        (owner->small_allocating & (1ull << role)))
        goto out;
    stride = ALIGN(bytes, 64);
    if (!stride || stride > PAGE_SIZE || stride % alignment ||
        owner->small_used[role] > PAGE_SIZE || owner->small_used[role] % 64)
        goto poison;
    owner->small_allocating |= 1ull << role;
    allocating = 1;
    if (!owner->small_pages[role] || stride > PAGE_SIZE - owner->small_used[role]) {
        spin_unlock_irqrestore(&pool_lock, flags);
        page = lsf_node_capacity_take(owner, LSF_NODE_SMALL_PAGE, PAGE_SIZE, PAGE_SIZE);
        spin_lock_irqsave(&pool_lock, flags);
        /* capacity_take already captured the real allocator output in the
         * original physical record before any post-effect admission check.
         * Never dereference this owner if its complete parent no longer binds.
         */
        node = lsf_node_capacity_parent_locked(owner);
        if (!node)
            goto poison;
        if (!page)
            goto out;
        if (lsf_node_capacity_record_locked(page, LSF_NODE_SMALL_PAGE,
                &actual, &page_record) != 1 || actual != owner ||
            page_record->deferred != LSF_PREPAID_PRIVATE)
            goto poison;
        owner->small_pages[role] = page;
        owner->small_used[role] = 0;
    }
    if (!lsf_node_capacity_open_locked(node) ||
        !(owner->small_allocating & (1ull << role)) ||
        !factory.pool.next_generation || factory.pool.next_generation == (u64)-1 ||
        lsf_node_capacity_record_locked(owner->small_pages[role], LSF_NODE_SMALL_PAGE,
            &actual, &page_record) != 1 || actual != owner ||
        page_record->deferred != LSF_PREPAID_PRIVATE)
        goto out;
    offset = owner->small_used[role];
    if (offset > PAGE_SIZE || stride > PAGE_SIZE - offset)
        goto poison;
    at = (unsigned long)owner->small_pages[role] + offset;
    if (at > ULONG_MAX - stride)
        goto poison;
    end = at + stride;
    page_slot = page_record - factory.pool.records;
    /* Even a damaged cursor cannot alias an earlier returned view. Physical
     * and logical records overlap intentionally, so inspect ALL typed views
     * rather than accepting the earlier physical page as the object record.
     */
    for (scan = 2; scan < LSF_ALLOCATION_SLOTS; ++scan) {
        prior = &factory.pool.records[scan];
        if (prior->phase == LSF_PREPAID_EMPTY ||
            prior->kind <= LSF_NODE_CAPACITY_KIND_BASE ||
            prior->kind >= LSF_NODE_CAPACITY_KIND_BASE + LSF_NODE_CAPACITY_ROLES ||
            prior->cache_bucket != page_slot || prior->cache_anchor != page_record->generation)
            continue;
        if (prior->offset < page_record->offset || prior->bytes > PAGE_SIZE ||
            prior->offset - page_record->offset > PAGE_SIZE - prior->bytes)
            goto poison;
        if (prior->offset < end && at < prior->offset + prior->bytes)
            goto poison;
    }
    context = &factory.pool.contexts[node->owner.slot];
    for (slot = 2; slot < LSF_ALLOCATION_SLOTS; ++slot) {
        record = &factory.pool.records[slot];
        if (record->phase != LSF_PREPAID_EMPTY)
            continue;
        address = (void *)at;
        *record = (struct lsf_prepaid_view){
            .generation = factory.pool.next_generation++,
            .owner_generation = node->owner.generation,
            .offset = at, .bytes = stride, .owner = node->owner.slot,
            .phase = LSF_PREPAID_LIVE, .kind = LSF_NODE_CAPACITY_KIND_BASE + role,
            .deferred = LSF_PREPAID_PRIVATE,
            .cache_bucket = page_slot, .cache_anchor = page_record->generation,
        };
        context->live++;
        owner->small_used[role] = offset + stride;
        break;
    }
    goto out;
poison:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
out:
    if (allocating && lsf_node_capacity_parent_locked(owner))
        owner->small_allocating &= ~(1ull << role);
    spin_unlock_irqrestore(&pool_lock, flags);
    return address;
}
