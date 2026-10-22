/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in maintained mm/vmalloc.c after its original allocation helpers.
 * This is not the ordinary vmap/vunmap allocator. No node pool, page-table
 * allocator, split-node preload, cache, lazy list or workqueue is used here. */
#if defined(CONFIG_X86_64) && defined(CONFIG_VMAP_STACK)
struct lsf_cleanup_stack {
    struct lsf_cleanup_task_source source;
    struct vm_struct vm;
    struct vmap_area area;
    struct page *pages[THREAD_SIZE / PAGE_SIZE];
    pte_t *entries[THREAD_SIZE / PAGE_SIZE + 1];
    void *payload;
    unsigned int carved, busy, mapped, retained;
};

/* Sole pointer, included in the ORIGINAL bootstrap metadata size assertion.
 * The actual free_vmap_area_lock protects publication, extent and removal.
 * A live pointer keeps the entire bank record alive, including its payload. */
static struct lsf_cleanup_stack *lsf_cleanup_stack_live;

int lsf_prepaid_cleanup_stack_geometry(unsigned long *bytes)
{
    if (!bytes || !IS_ENABLED(CONFIG_X86_64) || !IS_ENABLED(CONFIG_VMAP_STACK) ||
        IS_ENABLED(CONFIG_KASAN) || IS_ENABLED(CONFIG_KMSAN) ||
        IS_ENABLED(CONFIG_MEMCG) || IS_ENABLED(CONFIG_DEBUG_PAGEALLOC) ||
        IS_ENABLED(CONFIG_DEBUG_KMEMLEAK) || IS_ENABLED(CONFIG_PAGE_TABLE_CHECK) ||
        PAGE_SIZE != 4096u || THREAD_SIZE != 4u * PAGE_SIZE || THREAD_ALIGN != THREAD_SIZE ||
        sizeof(struct lsf_cleanup_stack) + PAGE_SIZE - 1u + THREAD_SIZE >
            LSF_FACTORY_INFRA_BYTES)
        return -EOPNOTSUPP;
    *bytes = sizeof(struct lsf_cleanup_stack) + PAGE_SIZE - 1u + THREAD_SIZE;
    return 0;
}

static pte_t *lsf_cleanup_existing_pte(unsigned long address)
{
    pgd_t *pgd = pgd_offset_k(address);
    p4d_t *p4d;
    pud_t *pud;
    pmd_t *pmd;
    if (pgd_none(*pgd) || pgd_bad(*pgd))
        return NULL;
    p4d = p4d_offset(pgd, address);
    if (p4d_none(*p4d) || p4d_bad(*p4d) || p4d_leaf(*p4d))
        return NULL;
    pud = pud_offset(p4d, address);
    if (pud_none(*pud) || pud_bad(*pud) || pud_leaf(*pud))
        return NULL;
    pmd = pmd_offset(pud, address);
    if (pmd_none(*pmd) || pmd_bad(*pmd) || pmd_leaf(*pmd))
        return NULL;
    /* This never calls pte_alloc_kernel_track or any upper-level allocator.
     * Existing shared kernel table ownership is unchanged, not adopted. */
    return pte_offset_kernel(pmd, address);
}

static int lsf_cleanup_stack_carve(struct lsf_cleanup_stack *stack)
{
    struct vmap_area *free;
    unsigned long flags, start, size = THREAD_SIZE + PAGE_SIZE;
    int result = -EOPNOTSUPP;
    spin_lock_irqsave(&free_vmap_area_lock, flags);
    if (!vmap_initialized || lsf_cleanup_stack_live ||
        list_empty(&free_vmap_area_list))
        goto out;
    /* Exactly ONE real free extent; no global scan, retry, purge or notifier.
     * Only a left edge may be shortened. No extra split metadata can be born. */
    free = list_first_entry(&free_vmap_area_list, struct vmap_area, list);
    start = free->va_start;
    if (!IS_ALIGNED(start, THREAD_ALIGN) || start < VMALLOC_START ||
        free->va_end > VMALLOC_END || free->va_end <= start ||
        free->va_end - start <= size)
        goto out;
    stack->area.va_start = start;
    stack->area.va_end = start + size;
    stack->area.vm = &stack->vm;
    stack->vm.addr = (void *)start;
    stack->vm.size = size;
    free->va_start += size;
    augment_tree_propagate_from(free);
    stack->carved = 1u;
    lsf_cleanup_stack_live = stack;
    result = 0;
out:
    spin_unlock_irqrestore(&free_vmap_area_lock, flags);
    return result;
}

static void lsf_cleanup_stack_busy(struct lsf_cleanup_stack *stack, int insert)
{
    struct vmap_node *node = addr_to_node(stack->area.va_start);
    spin_lock(&node->busy.lock);
    if (insert)
        insert_vmap_area(&stack->area, &node->busy.root, &node->busy.head);
    else
        unlink_va(&stack->area, &node->busy.root);
    stack->busy = insert;
    spin_unlock(&node->busy.lock);
}

/* No owned metadata is ever inserted into the global FREE tree: that would
 * allow an unrelated future va_clip/merge to free bank storage through SLUB.
 * Absorb only into actual adjacent normal free nodes under their original lock.
 * If neither neighbour is free, keep the reservation and original bank alive.
 * There is no lazy-list publication, hidden retry or deferred cleanup work. */
static int lsf_cleanup_stack_restore(struct lsf_cleanup_stack *stack)
{
    struct rb_node *parent;
    struct rb_node **link;
    struct list_head *next;
    struct vmap_area *left = NULL, *right = NULL;
    unsigned long flags;
    int result = -EBUSY;
    if (stack->busy)
        lsf_cleanup_stack_busy(stack, 0);
    spin_lock_irqsave(&free_vmap_area_lock, flags);
    if (lsf_cleanup_stack_live != stack)
        goto out;
    link = find_va_links(&stack->area, &free_vmap_area_root, NULL, &parent);
    if (!link)
        goto out;
    next = get_va_next_sibling(parent, link);
    if (!next)
        goto out;
    if (next != &free_vmap_area_list) {
        right = list_entry(next, struct vmap_area, list);
        if (right->va_start != stack->area.va_end)
            right = NULL;
    }
    if (next->prev != &free_vmap_area_list) {
        left = list_entry(next->prev, struct vmap_area, list);
        if (left->va_end != stack->area.va_start)
            left = NULL;
    }
    if (!left && !right)
        goto out;
    if (left && right) {
        /* Same unlink-before-augment ordering as the maintained merge helper.
         * Only the original NORMAL node is sent to its original cache. */
        __unlink_va(right, &free_vmap_area_root, true);
        left->va_end = right->va_end;
        kmem_cache_free(vmap_area_cachep, right);
        augment_tree_propagate_from(left);
    } else if (left) {
        left->va_end = stack->area.va_end;
        augment_tree_propagate_from(left);
    } else {
        right->va_start = stack->area.va_start;
        augment_tree_propagate_from(right);
    }
    stack->carved = 0;
    lsf_cleanup_stack_live = NULL;
    result = 0;
out:
    spin_unlock_irqrestore(&free_vmap_area_lock, flags);
    if (result)
        lsf_cleanup_stack_busy(stack, 1);
    return result;
}

int lsf_prepaid_cleanup_stack_foreign_unmap(const void *address)
{
    struct lsf_cleanup_task_source source = {0};
    struct lsf_cleanup_stack *stack;
    unsigned long flags, value = (unsigned long)address;
    int private = 0;
    spin_lock_irqsave(&free_vmap_area_lock, flags);
    stack = lsf_cleanup_stack_live;
    if (stack && value >= stack->area.va_start && value < stack->area.va_end) {
        source = stack->source;
        private = 1;
    }
    spin_unlock_irqrestore(&free_vmap_area_lock, flags);
    if (private)
        lsf_factory_cleanup_stack_poison(source);
    return private;
}

static int lsf_cleanup_stack_unmap(struct lsf_cleanup_stack *stack)
{
    unsigned int i;
    unsigned long address = stack->area.va_start;
    if (stack->mapped) {
        /* Exclusive VA reservation and constructor extent remain live. Check
         * the ACTUAL complete mapping and unmapped guard before any clear. */
        for (i = 0; i <= ARRAY_SIZE(stack->pages); ++i) {
            pte_t *entry = lsf_cleanup_existing_pte(address + i * PAGE_SIZE);
            if (!entry || entry != stack->entries[i] ||
                (i == ARRAY_SIZE(stack->pages) ? !pte_none(ptep_get(entry)) :
                 !pte_same(pte_mkold(pte_mkclean(ptep_get(entry))),
                    pte_mkold(pte_mkclean(mk_pte(stack->pages[i], pgprot_nx(PAGE_KERNEL)))))))
                return -EIO;
        }
        /* Actual maintained synchronous target-range helper: cache, PTE clear,
         * architecture mapping sync and TLB flush complete BEFORE any return.
         * It does not enter free_vmap_area_noflush or a deferred workqueue. */
        vunmap_range(address, address + THREAD_SIZE);
        stack->mapped = 0;
    }
    return lsf_cleanup_stack_restore(stack);
}

int lsf_prepaid_cleanup_stack_create(struct lsf_cleanup_task_source source,
    struct task_struct *task)
{
    struct lsf_cleanup_stack *stack;
    unsigned long start, bytes;
    unsigned int i;
    void *address;
    int error;
    if (current != kthreadd_task || in_interrupt() || !task ||
        lsf_prepaid_cleanup_stack_geometry(&bytes))
        return -EOPNOTSUPP;
    /* Real sizeof, one alignment slack, four real bank pages. Nothing is
     * borrowed from cached_stacks or a different allocation record. */
    error = lsf_factory_cleanup_stack_reserve(source, task, bytes, &address);
    if (error)
        return error;
    stack = address;
    stack->source = source;
    stack->payload = (void *)ALIGN((unsigned long)(stack + 1), PAGE_SIZE);
    for (i = 0; i < ARRAY_SIZE(stack->pages); ++i)
        stack->pages[i] = virt_to_page((char *)stack->payload + i * PAGE_SIZE);
    stack->vm.flags = VM_MAP;
    stack->vm.pages = stack->pages;
    stack->vm.nr_pages = ARRAY_SIZE(stack->pages);
    stack->vm.requested_size = THREAD_SIZE;
    error = lsf_cleanup_stack_carve(stack);
    /* Preserve the real original trace invocation outside the VA lock.
     * Callback admission/ownership is still a whole-profile installation
     * prerequisite; a racy tracepoint-enabled read is NOT an absence fence. */
    trace_alloc_vmap_area(error ? VMALLOC_END : stack->area.va_start,
        THREAD_SIZE + PAGE_SIZE, THREAD_ALIGN, VMALLOC_START, VMALLOC_END, !!error);
    if (error)
        goto finish;
    start = stack->area.va_start;
    /* Preflight EVERY leaf and the full guard before the FIRST PTE write.
     * Missing/huge/shared nonempty entries refuse without table allocation. */
    for (i = 0; i <= ARRAY_SIZE(stack->pages); ++i) {
        stack->entries[i] = lsf_cleanup_existing_pte(start + i * PAGE_SIZE);
        if (!stack->entries[i] || !pte_none(ptep_get(stack->entries[i]))) {
            error = -EOPNOTSUPP;
            goto restore;
        }
    }
    for (i = 0; i < ARRAY_SIZE(stack->pages); ++i)
        set_pte_at(&init_mm, start + i * PAGE_SIZE, stack->entries[i],
            mk_pte(stack->pages[i], pgprot_nx(PAGE_KERNEL)));
    if (PGTBL_PTE_MODIFIED & ARCH_PAGE_TABLE_SYNC_MASK)
        arch_sync_kernel_mappings(start, start + THREAD_SIZE);
    flush_cache_vmap(start, start + THREAD_SIZE);
    stack->mapped = 1u;
    lsf_cleanup_stack_busy(stack, 1);
    task->stack_vm_area = &stack->vm;
    task->stack = stack->vm.addr;
    return 0;
restore:
    if (lsf_cleanup_stack_unmap(stack)) {
        stack->retained = 1u;
        lsf_factory_cleanup_stack_poison(source);
        return -EIO;
    }
finish:
    if (!lsf_factory_cleanup_stack_finish(source, stack))
        return -EIO;
    return error;
}

int lsf_prepaid_cleanup_stack_abort_unpublished(struct lsf_cleanup_task_source source,
    struct task_struct *task)
{
    struct lsf_cleanup_stack *stack;
    unsigned long flags;
    int error;
    if (current != kthreadd_task || in_interrupt() || !task)
        return -EOPNOTSUPP;
    /* Validate the actual born task ADDRESS before reading any supplied task
     * fields. Copying valid stack/VM pointers into a foreign task is not an
     * affine owner, even for a private kernel caller. */
    stack = lsf_factory_cleanup_stack_current(source, task);
    if (!stack) {
        lsf_factory_cleanup_stack_poison(source);
        return -EIO;
    }
    spin_lock_irqsave(&free_vmap_area_lock, flags);
    if (stack != lsf_cleanup_stack_live || stack->vm.addr != task->stack ||
        &stack->vm != task->stack_vm_area ||
        stack->source.owner.slot != source.owner.slot ||
        stack->source.owner.generation != source.owner.generation ||
        stack->source.root.slot != source.root.slot ||
        stack->source.root.generation != source.root.generation ||
        stack->source.request.slot != source.request.slot ||
        stack->source.request.generation != source.request.generation ||
        stack->source.task.slot != source.task.slot ||
        stack->source.task.generation != source.task.generation || stack->retained) {
        spin_unlock_irqrestore(&free_vmap_area_lock, flags);
        lsf_factory_cleanup_stack_poison(source);
        return -EIO;
    }
    spin_unlock_irqrestore(&free_vmap_area_lock, flags);
    error = lsf_cleanup_stack_unmap(stack);
    if (error) {
        stack->retained = 1u;
        lsf_factory_cleanup_stack_poison(source);
        return error;
    }
    task->stack = NULL;
    task->stack_vm_area = NULL;
    /* Last descriptor access occurs before finish can return this child view.
     * Cursor, request, bank and original bootstrap reservation stay charged. */
    return lsf_factory_cleanup_stack_finish(source, stack) ? 0 : -EIO;
}
#else
/* Unselected layouts keep the original VM allocator and have no private live
 * alias. Do not reference conditional task fields or invent an unguarded stack. */
int lsf_prepaid_cleanup_stack_geometry(unsigned long *bytes)
{
    (void)bytes;
    return -EOPNOTSUPP;
}
int lsf_prepaid_cleanup_stack_create(struct lsf_cleanup_task_source source,
    struct task_struct *task)
{
    (void)source;
    (void)task;
    return -EOPNOTSUPP;
}
int lsf_prepaid_cleanup_stack_abort_unpublished(struct lsf_cleanup_task_source source,
    struct task_struct *task)
{
    (void)source;
    (void)task;
    return -EOPNOTSUPP;
}
int lsf_prepaid_cleanup_stack_foreign_unmap(const void *address)
{
    (void)address;
    return 0;
}
#endif
