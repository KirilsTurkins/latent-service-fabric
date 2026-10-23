/* SPDX-License-Identifier: GPL-2.0-only */
/* Included after the existing private VM implementation, in the same TU.
 * The ordinary stack cache/RCU/lazy allocator and return remain unchanged. */
#if defined(CONFIG_X86_64) && defined(CONFIG_VMAP_STACK)
static int lsf_cleanup_stack_source_equal(struct lsf_cleanup_task_source left,
    struct lsf_cleanup_task_source right)
{
    return left.owner.slot == right.owner.slot &&
        left.owner.generation == right.owner.generation &&
        left.root.slot == right.root.slot && left.root.generation == right.root.generation &&
        left.request.slot == right.request.slot &&
        left.request.generation == right.request.generation &&
        left.task.slot == right.task.slot && left.task.generation == right.task.generation;
}

static int lsf_cleanup_stack_release_match(struct lsf_cleanup_stack *stack,
    struct lsf_cleanup_task_source source, struct task_struct *task)
{
    /* The factory resolved this exact born task and stack address BEFORE the
     * first task/stack field read. The LIVE child prevents bank destruction. */
    return stack == lsf_cleanup_stack_live &&
        lsf_cleanup_stack_source_equal(stack->source, source) &&
        stack->carved && stack->busy && stack->mapped && !stack->retained &&
        task != current && READ_ONCE(task->__state) == TASK_DEAD &&
        refcount_read(&task->stack_refcount) == 0 &&
        task->stack == stack->vm.addr && task->stack_vm_area == &stack->vm;
}

int lsf_prepaid_cleanup_stack_publish(struct lsf_cleanup_task_source source,
    struct task_struct *task)
{
    struct lsf_cleanup_task_source actual;
    struct lsf_cleanup_stack *stack;
    unsigned long flags;
    void *address;
    int valid;
    if (current != kthreadd_task || in_interrupt() ||
        lsf_factory_cleanup_lifecycle_source(task, &actual, &address) != 1 || !address ||
        !lsf_cleanup_stack_source_equal(actual, source))
        goto poison;
    stack = address;
    spin_lock_irqsave(&free_vmap_area_lock, flags);
    valid = stack == lsf_cleanup_stack_live &&
        lsf_cleanup_stack_source_equal(stack->source, source) &&
        stack->carved && stack->busy && stack->mapped && !stack->retained &&
        task->stack == stack->vm.addr && task->stack_vm_area == &stack->vm &&
        READ_ONCE(task->__state) == TASK_NEW && refcount_read(&task->stack_refcount) == 1;
    spin_unlock_irqrestore(&free_vmap_area_lock, flags);
    if (valid && lsf_factory_cleanup_task_publish(source, task))
        return 0;
poison:
    lsf_factory_cleanup_stack_poison(source);
    return -EIO;
}

int lsf_prepaid_cleanup_stack_release(struct task_struct *task)
{
    struct lsf_cleanup_task_source source;
    struct lsf_cleanup_stack *stack;
    unsigned long flags;
    void *address;
    int owned = lsf_factory_cleanup_lifecycle_source(task, &source, &address);
    if (!owned)
        return 0; /* Genuinely outside: original Linux path is unchanged. */
    if (owned < 0 || !address)
        return 1; /* Unknown/consumed bank address can never reach normal free. */
    stack = address;
    spin_lock_irqsave(&free_vmap_area_lock, flags);
    owned = lsf_cleanup_stack_release_match(stack, source, task);
    spin_unlock_irqrestore(&free_vmap_area_lock, flags);
    if (!owned || !lsf_factory_cleanup_stack_capture(source, task, stack))
        goto poison;
    /* The REAL pre-publication task reference spans scheduler/RCU, external
     * stack readers, detachment and VA return. No lock nests inside VM lock. */
    spin_lock_irqsave(&free_vmap_area_lock, flags);
    if (!lsf_cleanup_stack_release_match(stack, source, task)) {
        spin_unlock_irqrestore(&free_vmap_area_lock, flags);
        goto poison;
    }
    task->stack = NULL;
    task->stack_vm_area = NULL;
    spin_unlock_irqrestore(&free_vmap_area_lock, flags);
    if (!lsf_factory_cleanup_stack_enqueue(source, task))
        goto poison;
    /* Potential scheduler/IRQ caller: never take kthread_create_lock here.
     * Both original locks are released before the original wakeup primitive. */
    wake_up_process(kthreadd_task);
    return 1;
poison:
    lsf_factory_cleanup_stack_poison(source);
    return 1;
}

int lsf_prepaid_cleanup_stack_retire(struct lsf_cleanup_task_source source,
    struct task_struct *task)
{
    struct lsf_cleanup_task_source actual;
    struct lsf_cleanup_stack *stack;
    unsigned long flags;
    void *address;
    int valid, error;
    if (current != kthreadd_task || in_interrupt())
        return -EOPNOTSUPP;
    if (lsf_factory_cleanup_lifecycle_source(task, &actual, &address) != 1 || !address ||
        !lsf_cleanup_stack_source_equal(actual, source))
        goto poison;
    stack = address;
    spin_lock_irqsave(&free_vmap_area_lock, flags);
    valid = stack == lsf_cleanup_stack_live &&
        lsf_cleanup_stack_source_equal(stack->source, source) &&
        stack->carved && stack->busy && stack->mapped && !stack->retained &&
        task != current && READ_ONCE(task->__state) == TASK_DEAD &&
        refcount_read(&task->stack_refcount) == 0 &&
        !task->stack && !task->stack_vm_area;
    spin_unlock_irqrestore(&free_vmap_area_lock, flags);
    if (!valid)
        goto poison;
    /* This is the existing real synchronous PTE/cache/target-TLB and original
     * adjacent-VA restoration. It runs only in the original control context. */
    error = lsf_cleanup_stack_unmap(stack);
    if (error) {
        stack->retained = 1u;
        goto poison;
    }
    /* Last stack descriptor access. A failed finish retains the real task
     * reference and original request/bank; the consumer must not put it. */
    return lsf_factory_cleanup_stack_returned(source, task, stack) ? 0 : -EIO;
poison:
    lsf_factory_cleanup_stack_poison(source);
    return -EIO;
}
#else
int lsf_prepaid_cleanup_stack_publish(struct lsf_cleanup_task_source source,
    struct task_struct *task)
{
    (void)source;
    (void)task;
    return -EOPNOTSUPP;
}
int lsf_prepaid_cleanup_stack_release(struct task_struct *task)
{
    (void)task;
    return 0;
}
int lsf_prepaid_cleanup_stack_retire(struct lsf_cleanup_task_source source,
    struct task_struct *task)
{
    (void)source;
    (void)task;
    return -EOPNOTSUPP;
}
#endif
