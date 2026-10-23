/* SPDX-License-Identifier: GPL-2.0-only */
/* Included with the actual request in kthread.c. Remaining observer/bootstrap
 * closure keeps the existing pending consumer disconnected from this caller. */
int lsf_prepaid_cleanup_clone_args_current(struct lsf_cleanup_task_source source,
    const struct kernel_clone_args *args)
{
    struct lsf_cleanup_task_source actual;
    struct lsf_cleanup_request *owned;
    void *address;
    static_assert(offsetof(struct lsf_cleanup_request, create) == 0);
    if (!args || !args->fn_arg || current != kthreadd_task || current->mm)
        return 0;
    /* The maintained create is the first member; offsetof is asserted rather
     * than trusting a caller-supplied cast as allocation authority. */
    address = args->fn_arg;
    if (!lsf_factory_cleanup_constructor_request(address, sizeof(*owned), &actual) ||
        !lsf_cleanup_irq_source_equal(actual, source))
        return 0;
    owned = address; /* First request access follows the exact original birth. */
    return lsf_cleanup_irq_source_equal(owned->source, actual) &&
        args->fn == lsf_prepaid_cleanup_kthread_entry && args->fn_arg == &owned->create &&
        args->name == owned->name && owned->create.full_name == owned->name &&
        !memcmp(owned->name, "lsf/firmware-cleanup", sizeof(owned->name)) &&
        owned->create.threadfn == kthread_worker_fn && owned->create.data == &owned->worker &&
        owned->create.node == NUMA_NO_NODE && args->kthread &&
        args->flags == LSF_CLEANUP_CLONE_FLAGS && args->exit_signal == SIGCHLD &&
        !args->user_worker && !args->io_thread && !args->no_files &&
        !args->stack && !args->stack_size && !args->tls && !args->set_tid && !args->set_tid_size &&
        !args->pidfd && !args->parent_tid && !args->child_tid &&
        !args->cgroup && !args->cgrp && !args->cset && !args->kill_seq && !args->idle;
}
