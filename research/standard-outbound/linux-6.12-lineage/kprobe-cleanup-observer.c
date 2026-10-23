/* SPDX-License-Identifier: GPL-2.0-only */
/* Original mutex serializes both actual registration and the absence seal. */
static int lsf_cleanup_kretprobe_prepare_begin(void)
{
    int error = 0;
    mutex_lock(&kprobe_mutex);
    if (lsf_cleanup_kprobe_observers.sealed || lsf_cleanup_kprobe_observers.uncertain ||
        lsf_cleanup_kprobe_observers.preparing == ~0u)
        error = -EOPNOTSUPP;
    else
        lsf_cleanup_kprobe_observers.preparing++;
    mutex_unlock(&kprobe_mutex);
    return error;
}

static void lsf_cleanup_kretprobe_prepare_end(void)
{
    mutex_lock(&kprobe_mutex);
    if (!lsf_cleanup_kprobe_observers.preparing)
        lsf_cleanup_kprobe_observers.uncertain = 1u;
    else
        lsf_cleanup_kprobe_observers.preparing--;
    mutex_unlock(&kprobe_mutex);
}

static int lsf_cleanup_kprobe_retire_begin(void)
{
    int tracked = 0;
    mutex_lock(&kprobe_mutex);
    if (lsf_cleanup_kprobe_observers.retiring == ~0u)
        lsf_cleanup_kprobe_observers.uncertain = 1u;
    else {
        lsf_cleanup_kprobe_observers.retiring++;
        tracked = 1;
    }
    mutex_unlock(&kprobe_mutex);
    return tracked;
}

static void lsf_cleanup_kprobe_retire_end(void)
{
    mutex_lock(&kprobe_mutex);
    if (!lsf_cleanup_kprobe_observers.retiring)
        lsf_cleanup_kprobe_observers.uncertain = 1u;
    else
        lsf_cleanup_kprobe_observers.retiring--;
    mutex_unlock(&kprobe_mutex);
}

static int lsf_cleanup_kprobes_observed_locked(void)
{
    unsigned int i;
    lockdep_assert_held(&kprobe_mutex);
    if (lsf_cleanup_kprobe_observers.preparing || lsf_cleanup_kprobe_observers.retiring ||
        lsf_cleanup_kprobe_observers.uncertain)
        return 1;
    for (i = 0; i < KPROBE_TABLE_SIZE; ++i)
        if (!hlist_empty(&kprobe_table[i]))
            return 1; /* Disabled/GONE registrations are still registrations. */
    return 0;
}

unsigned long lsf_cleanup_kprobe_seal_bytes(void)
{
    return sizeof(lsf_cleanup_kprobe_observers);
}

int lsf_cleanup_kprobe_prebirth_seal(void)
{
    int error = -EOPNOTSUPP;
    mutex_lock(&kprobe_mutex);
    if (lsf_cleanup_kprobe_observers.sealed || lsf_cleanup_kprobes_observed_locked())
        goto first_out;
    lsf_cleanup_kprobe_observers.sealed = 1u;
    error = 0;
first_out:
    mutex_unlock(&kprobe_mutex);
    if (error)
        return error;
    /* Selected OPTPROBES includes real deferred text unoptimization, task-RCU
     * grace, arch instruction return and optimizer epilogue. Never wait while
     * holding its mutex. No new registration can start during these drains. */
    wait_for_kprobe_optimizer();
#ifdef CONFIG_OPTPROBES
    flush_delayed_work(&optimizing_work);
#endif
    synchronize_rcu();
    /* Complete queued rethook_free_rcu -> actual objpool_fini too. Old Tasks
     * can still hold stopped (handler-NULL) pool nodes; their physical storage
     * remains original NodeFixed state, never a private Root refund. */
    rcu_barrier();
    mutex_lock(&kprobe_mutex);
    if (lsf_cleanup_kprobe_observers.sealed != 1u || lsf_cleanup_kprobes_observed_locked()
#ifdef CONFIG_OPTPROBES
        || !list_empty(&optimizing_list) || !list_empty(&unoptimizing_list) ||
        !list_empty(&freeing_list)
#endif
       ) {
        error = -EOPNOTSUPP;
        lsf_cleanup_kprobe_observers.sealed = 0;
    } else {
        lsf_cleanup_kprobe_observers.sealed = 2u;
    }
    mutex_unlock(&kprobe_mutex);
    return error;
}

void lsf_cleanup_kprobe_prebirth_rollback(void)
{
    mutex_lock(&kprobe_mutex);
    lsf_cleanup_kprobe_observers.sealed = 0;
    mutex_unlock(&kprobe_mutex);
}
