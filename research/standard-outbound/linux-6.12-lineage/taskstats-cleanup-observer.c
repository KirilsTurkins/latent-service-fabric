/* SPDX-License-Identifier: GPL-2.0-only */
/* Included after listener_array; every REGISTER producer enters this mutex
 * before its first allocation and leaves only after original error unwind. */
static struct {
    struct mutex mutex;
    unsigned int sealed, preparing, uncertain;
} lsf_cleanup_taskstats_state = {
    .mutex = __MUTEX_INITIALIZER(lsf_cleanup_taskstats_state.mutex),
};

static int lsf_cleanup_taskstats_prepare_begin(void)
{
    int error = -EOPNOTSUPP;
    mutex_lock(&lsf_cleanup_taskstats_state.mutex);
    if (!lsf_cleanup_taskstats_state.sealed && !lsf_cleanup_taskstats_state.uncertain) {
        if (lsf_cleanup_taskstats_state.preparing == ~0u) {
            lsf_cleanup_taskstats_state.uncertain = 1u;
            error = -EOVERFLOW;
        } else {
            lsf_cleanup_taskstats_state.preparing++;
            error = 0;
        }
    }
    mutex_unlock(&lsf_cleanup_taskstats_state.mutex);
    return error;
}

static void lsf_cleanup_taskstats_prepare_end(void)
{
    mutex_lock(&lsf_cleanup_taskstats_state.mutex);
    if (lsf_cleanup_taskstats_state.preparing)
        lsf_cleanup_taskstats_state.preparing--;
    else
        lsf_cleanup_taskstats_state.uncertain = 1u;
    mutex_unlock(&lsf_cleanup_taskstats_state.mutex);
}

unsigned long lsf_cleanup_taskstats_seal_bytes(void)
{
    return sizeof(lsf_cleanup_taskstats_state);
}

int lsf_cleanup_taskstats_prebirth_seal(void)
{
    struct listener_list *listeners;
    unsigned int cpu;
    int empty, error = -EOPNOTSUPP;
    mutex_lock(&lsf_cleanup_taskstats_state.mutex);
    if (lsf_cleanup_taskstats_state.sealed || lsf_cleanup_taskstats_state.preparing ||
        lsf_cleanup_taskstats_state.uncertain || !READ_ONCE(family_registered))
        goto out;
    /* All possible CPUs, including offline CPUs. Early list initialization
     * precedes successful family registration; no uninitialized head is read. */
    for_each_possible_cpu(cpu) {
        listeners = &per_cpu(listener_array, cpu);
        down_write(&listeners->sem);
        empty = list_empty(&listeners->list);
        up_write(&listeners->sem);
        if (!empty)
            goto out;
    }
    lsf_cleanup_taskstats_state.sealed = 1u;
    error = 0;
out:
    mutex_unlock(&lsf_cleanup_taskstats_state.mutex);
    return error;
}

void lsf_cleanup_taskstats_prebirth_rollback(void)
{
    mutex_lock(&lsf_cleanup_taskstats_state.mutex);
    lsf_cleanup_taskstats_state.sealed = 0;
    mutex_unlock(&lsf_cleanup_taskstats_state.mutex);
}
