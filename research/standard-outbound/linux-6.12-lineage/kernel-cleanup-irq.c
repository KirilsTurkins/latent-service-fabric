/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in maintained kthread.c after the actual prepaid request type.
 * This relay is not a second ownership ledger. It never authorizes a free:
 * process context revalidates the original factory records and VM lineage. */
#if defined(CONFIG_X86_64) && defined(CONFIG_IRQ_WORK) && !defined(CONFIG_PREEMPT_RT)
enum lsf_cleanup_irq_phase {
    LSF_CLEANUP_IRQ_EMPTY,
    LSF_CLEANUP_IRQ_PREPARING,
    LSF_CLEANUP_IRQ_PREPARED,
    LSF_CLEANUP_IRQ_ARMED,
    LSF_CLEANUP_IRQ_QUEUING,
    LSF_CLEANUP_IRQ_READY,
    LSF_CLEANUP_IRQ_SYNCING,
    LSF_CLEANUP_IRQ_CONSUMED
};

/* Permanently allocated, charged before the original backing allocation.
 * Outside callers never follow a pointer into a potentially retiring bank.
 * There is ONE birth, no reset/reuse/ABA, and no current backing-return path.
 * A future physical bank return MUST close this hint before releasing pages;
 * no such return or production installation is claimed by this source layer. */
static struct {
    atomic_t phase;
    atomic_t uncertain;
    struct task_struct *task;
    struct lsf_cleanup_request *request;
    struct lsf_cleanup_task_source source;
    unsigned long bank_base;
} lsf_cleanup_irq_hint = {
    .phase = ATOMIC_INIT(LSF_CLEANUP_IRQ_EMPTY),
    .uncertain = ATOMIC_INIT(0)
};

unsigned long lsf_prepaid_cleanup_irq_bootstrap_bytes(void)
{
    return sizeof(lsf_cleanup_irq_hint);
}

static int lsf_cleanup_irq_source_equal(struct lsf_cleanup_task_source a,
    struct lsf_cleanup_task_source b)
{
    return a.owner.slot == b.owner.slot && a.owner.generation == b.owner.generation &&
        a.root.slot == b.root.slot && a.root.generation == b.root.generation &&
        a.request.slot == b.request.slot && a.request.generation == b.request.generation &&
        a.task.slot == b.task.slot && a.task.generation == b.task.generation;
}

static void lsf_cleanup_irq_notify(struct irq_work *work)
{
    /* The real task reference and original request/bank cover this callback
     * AND irq_work_single's later BUSY-clear/descriptor epilogue. No pool,
     * VM, task-field or ownership return is performed in IRQ context. */
    if (atomic_read_acquire(&lsf_cleanup_irq_hint.phase) != LSF_CLEANUP_IRQ_QUEUING ||
        work != &lsf_cleanup_irq_hint.request->retire_irq ||
        atomic_cmpxchg(&lsf_cleanup_irq_hint.phase, LSF_CLEANUP_IRQ_QUEUING,
            LSF_CLEANUP_IRQ_READY) != LSF_CLEANUP_IRQ_QUEUING) {
        atomic_set(&lsf_cleanup_irq_hint.uncertain, 1);
        return;
    }
    wake_up_process(kthreadd_task);
}

int lsf_prepaid_cleanup_irq_prepare(struct lsf_cleanup_task_source source,
    struct task_struct *task)
{
    struct lsf_cleanup_request *request;
    unsigned long bank_base;
    void *address;
    if (!IS_ENABLED(CONFIG_X86_64) || !IS_ENABLED(CONFIG_IRQ_WORK) ||
        IS_ENABLED(CONFIG_PREEMPT_RT) || !arch_irq_work_has_interrupt() ||
        current != kthreadd_task || in_interrupt() || irqs_disabled() ||
        !lsf_factory_cleanup_irq_hint(source, task, sizeof(*request), &address, &bank_base))
        return -EOPNOTSUPP;
    request = address;
    if (atomic_cmpxchg(&lsf_cleanup_irq_hint.phase, LSF_CLEANUP_IRQ_EMPTY,
            LSF_CLEANUP_IRQ_PREPARING) != LSF_CLEANUP_IRQ_EMPTY)
        return -EIO;
    /* Exact born task/request/root/full generations and range were resolved
     * under the original pool lock BEFORE any request write. sizeof(*request)
     * already included this actual descriptor before admission/memset. */
    request->retire_irq = IRQ_WORK_INIT_HARD(lsf_cleanup_irq_notify);
    lsf_cleanup_irq_hint.task = task;
    lsf_cleanup_irq_hint.request = request;
    lsf_cleanup_irq_hint.source = source;
    lsf_cleanup_irq_hint.bank_base = bank_base;
    atomic_set_release(&lsf_cleanup_irq_hint.phase, LSF_CLEANUP_IRQ_PREPARED);
    return 0;
}

int lsf_prepaid_cleanup_irq_arm(struct lsf_cleanup_task_source source,
    struct task_struct *task)
{
    unsigned long bank_base;
    void *address;
    if (current != kthreadd_task || in_interrupt() || irqs_disabled() ||
        atomic_read_acquire(&lsf_cleanup_irq_hint.phase) != LSF_CLEANUP_IRQ_PREPARED ||
        !lsf_factory_cleanup_irq_hint(source, task,
            sizeof(struct lsf_cleanup_request), &address, &bank_base) ||
        task != lsf_cleanup_irq_hint.task || address != lsf_cleanup_irq_hint.request ||
        bank_base != lsf_cleanup_irq_hint.bank_base ||
        !lsf_cleanup_irq_source_equal(source, lsf_cleanup_irq_hint.source) ||
        !lsf_factory_cleanup_irq_published(source, task))
        return -EIO;
    /* The original factory already acquired the REAL continuation task ref.
     * This single immutable hint is armed BEFORE actual task visibility. */
    return atomic_cmpxchg(&lsf_cleanup_irq_hint.phase, LSF_CLEANUP_IRQ_PREPARED,
        LSF_CLEANUP_IRQ_ARMED) == LSF_CLEANUP_IRQ_PREPARED ? 0 : -EIO;
}

int lsf_prepaid_cleanup_stack_release(struct task_struct *task)
{
    unsigned long address = (unsigned long)task, base;
    int phase = atomic_read_acquire(&lsf_cleanup_irq_hint.phase);
    /* Before publication no task escapes this private constructor. Ordinary
     * tasks stay on their exact original path. Full unpublished bad-fork
     * ownership is a separate mandatory constructor integration boundary. */
    if (phase == LSF_CLEANUP_IRQ_EMPTY || phase == LSF_CLEANUP_IRQ_PREPARING)
        return 0;
    base = lsf_cleanup_irq_hint.bank_base;
    if (task != lsf_cleanup_irq_hint.task) {
        if (address < base || address - base >= LSF_BACKING_BYTES)
            return 0;
        atomic_set(&lsf_cleanup_irq_hint.uncertain, 1);
        return 1;
    }
    /* Only immutable permanently allocated hint fields are read above.
     * Do NOT inspect task state/refcounts, mutable pool records or VM state,
     * take a lock, acquire a task ref, detach fields, or wake a task here.
     * Local irq_work_queue is the actual maintained NMI-safe primitive. */
    if (phase != LSF_CLEANUP_IRQ_ARMED ||
        atomic_read(&lsf_cleanup_irq_hint.uncertain) ||
        atomic_cmpxchg(&lsf_cleanup_irq_hint.phase, LSF_CLEANUP_IRQ_ARMED,
            LSF_CLEANUP_IRQ_QUEUING) != LSF_CLEANUP_IRQ_ARMED) {
        atomic_set(&lsf_cleanup_irq_hint.uncertain, 1);
        return 1;
    }
    if (!irq_work_queue(&lsf_cleanup_irq_hint.request->retire_irq))
        atomic_set(&lsf_cleanup_irq_hint.uncertain, 1);
    /* LAST request/descriptor access from the queueing caller. There is no
     * remote IPI, retry, CPU-offline completion or ordinary-free fallback. */
    return 1;
}

int lsf_prepaid_cleanup_irq_pending(void)
{
    return atomic_read_acquire(&lsf_cleanup_irq_hint.phase) == LSF_CLEANUP_IRQ_READY;
}

void lsf_prepaid_cleanup_irq_drain(void)
{
    struct lsf_cleanup_task_source source;
    struct task_struct *task;
    if (current != kthreadd_task || in_interrupt() || irqs_disabled())
        return;
    if (atomic_cmpxchg(&lsf_cleanup_irq_hint.phase, LSF_CLEANUP_IRQ_READY,
            LSF_CLEANUP_IRQ_SYNCING) != LSF_CLEANUP_IRQ_READY)
        return;
    /* The callback publishes READY before its actual descriptor epilogue.
     * Synchronize in process context with NO creation/pool/VM/rq lock held.
     * READY proves execution began: an undelivered/offline queue is NOT polled
     * or fabricated as complete. Non-RT + actual APIC was checked at prepare. */
    irq_work_sync(&lsf_cleanup_irq_hint.request->retire_irq);
    source = lsf_cleanup_irq_hint.source;
    task = lsf_cleanup_irq_hint.task;
    atomic_set_release(&lsf_cleanup_irq_hint.phase, LSF_CLEANUP_IRQ_CONSUMED);
    if (atomic_read(&lsf_cleanup_irq_hint.uncertain))
        goto poison;
    /* Original record+actual TASK_DEAD/refcount/VM validation now runs only
     * after synchronization. It authenticates, detaches and queues once. */
    if (!lsf_prepaid_cleanup_stack_capture_deferred(task) ||
        !lsf_factory_cleanup_retire_pending() ||
        atomic_read(&lsf_cleanup_irq_hint.uncertain))
        goto poison;
    lsf_prepaid_cleanup_retire_one(); /* May physically return task: last task use. */
    return;
poison:
    lsf_factory_cleanup_stack_poison(source);
}
#else
unsigned long lsf_prepaid_cleanup_irq_bootstrap_bytes(void) { return 0; }
int lsf_prepaid_cleanup_irq_prepare(struct lsf_cleanup_task_source source,
    struct task_struct *task)
{
    (void)source;
    (void)task;
    return -EOPNOTSUPP;
}
int lsf_prepaid_cleanup_irq_arm(struct lsf_cleanup_task_source source,
    struct task_struct *task)
{
    (void)source;
    (void)task;
    return -EOPNOTSUPP;
}
int lsf_prepaid_cleanup_stack_release(struct task_struct *task) { (void)task; return 0; }
int lsf_prepaid_cleanup_irq_pending(void) { return 0; }
void lsf_prepaid_cleanup_irq_drain(void) { }
#endif
