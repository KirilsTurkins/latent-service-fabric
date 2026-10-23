/* SPDX-License-Identifier: GPL-2.0-only */
/* Included with the actual original request and permanent hint definition.
 * Only validated factory birth/commit/abort call sites use these helpers. */
#if defined(CONFIG_X86_64) && defined(CONFIG_IRQ_WORK) && !defined(CONFIG_PREEMPT_RT)
int lsf_prepaid_cleanup_irq_birth_locked(struct lsf_cleanup_task_source source,
    struct task_struct *task, void *address, unsigned long bank_base)
{
    struct lsf_cleanup_request *request = address;
    if (in_interrupt() || !task || !request || !bank_base || !arch_irq_work_has_interrupt() ||
        atomic_cmpxchg(&lsf_cleanup_irq_hint.phase, LSF_CLEANUP_IRQ_EMPTY,
            LSF_CLEANUP_IRQ_PREPARING) != LSF_CLEANUP_IRQ_EMPTY)
        return -EOPNOTSUPP;
    /* Both real records were admitted under the original actor/pool checks.
     * The complete actual request, including this descriptor, was charged and
     * zeroed before this call. No task storage or fields are read here. */
    request->retire_irq = IRQ_WORK_INIT_HARD(lsf_cleanup_irq_notify);
    lsf_cleanup_irq_hint.task = task;
    lsf_cleanup_irq_hint.request = request;
    lsf_cleanup_irq_hint.source = source;
    lsf_cleanup_irq_hint.bank_base = bank_base;
    atomic_set_release(&lsf_cleanup_irq_hint.phase, LSF_CLEANUP_IRQ_BORN);
    return 0;
}

int lsf_prepaid_cleanup_irq_abort_locked(struct lsf_cleanup_task_source source,
    struct task_struct *task)
{
    int phase = atomic_read_acquire(&lsf_cleanup_irq_hint.phase);
    if (current != kthreadd_task || in_interrupt() || task != lsf_cleanup_irq_hint.task ||
        !lsf_cleanup_irq_source_equal(source, lsf_cleanup_irq_hint.source) ||
        atomic_read(&lsf_cleanup_irq_hint.uncertain) ||
        (phase != LSF_CLEANUP_IRQ_BORN && phase != LSF_CLEANUP_IRQ_PREPARED))
        return -EIO;
    /* Neither state has ever been queued or armed. Never cancel a possibly
     * executing descriptor or fabricate an IRQ/offline completion. */
    return atomic_cmpxchg(&lsf_cleanup_irq_hint.phase, phase,
        LSF_CLEANUP_IRQ_ABORTED) == phase ? 0 : -EIO;
}

int lsf_prepaid_cleanup_irq_commit(struct lsf_cleanup_task_source source,
    struct task_struct *task)
{
    if (current != kthreadd_task || in_interrupt() || !irqs_disabled() ||
        task != lsf_cleanup_irq_hint.task ||
        !lsf_cleanup_irq_source_equal(source, lsf_cleanup_irq_hint.source) ||
        atomic_read(&lsf_cleanup_irq_hint.uncertain))
        return -EIO;
    /* The factory holds its original pool lock and has just acquired the REAL
     * task continuation. The sole caller is the actual tasklist/sighand-locked
     * publication point, before any task becomes externally visible. */
    lockdep_assert_held(&tasklist_lock);
    return atomic_cmpxchg(&lsf_cleanup_irq_hint.phase, LSF_CLEANUP_IRQ_PREPARED,
        LSF_CLEANUP_IRQ_ARMED) == LSF_CLEANUP_IRQ_PREPARED ? 0 : -EIO;
}
#else
int lsf_prepaid_cleanup_irq_birth_locked(struct lsf_cleanup_task_source source,
    struct task_struct *task, void *address, unsigned long bank_base)
{
    (void)source; (void)task; (void)address; (void)bank_base;
    return -EOPNOTSUPP;
}
int lsf_prepaid_cleanup_irq_abort_locked(struct lsf_cleanup_task_source source,
    struct task_struct *task)
{
    (void)source; (void)task;
    return -EOPNOTSUPP;
}
int lsf_prepaid_cleanup_irq_commit(struct lsf_cleanup_task_source source,
    struct task_struct *task)
{
    (void)source; (void)task;
    return -EOPNOTSUPP;
}
#endif

int lsf_prepaid_cleanup_request_geometry(unsigned long *bytes)
{
    if (!bytes)
        return -EINVAL;
    *bytes = sizeof(struct lsf_cleanup_request);
    return 0;
}

int lsf_prepaid_cleanup_kthread_prepare(struct lsf_cleanup_task_source source,
    struct task_struct *task)
{
    return lsf_cleanup_kthread_prepare(source, task);
}
