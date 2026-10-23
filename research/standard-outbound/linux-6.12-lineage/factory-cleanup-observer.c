/* SPDX-License-Identifier: GPL-2.0-only */
/* Prepared opt-in profile, deliberately NOT called by the current consumer. */
static unsigned long lsf_cleanup_observer_bootstrap_bytes(void)
{
#if defined(CONFIG_TRACEPOINTS) && defined(CONFIG_KPROBES) && defined(CONFIG_PROC_EVENTS)
    return lsf_cleanup_tracepoint_seal_bytes() + lsf_cleanup_kprobe_seal_bytes() +
        lsf_cleanup_connector_seal_bytes();
#else
    return LSF_BOOTSTRAP_CEILING;
#endif
}

static int __maybe_unused lsf_cleanup_observers_prebank_enter(void)
{
#if defined(CONFIG_TRACEPOINTS) && defined(CONFIG_KPROBES) && defined(CONFIG_PROC_EVENTS)
    int error;
    lockdep_assert_held(&factory_lock);
    /* Concrete original bank state, before any subsystem seal is acquired. */
    if (factory.pages || factory.opened || factory.device || READ_ONCE(factory.uncertain))
        return -EOPNOTSUPP;
    error = lsf_cleanup_tracepoint_prebirth_seal();
    if (error)
        return error;
    error = lsf_cleanup_kprobe_prebirth_seal();
    if (error)
        goto tracepoint_rollback;
    error = lsf_cleanup_connector_prebirth_seal();
    if (error)
        goto kprobe_rollback;
    factory.cleanup_observer_prebirth = 1u;
    return 0;
kprobe_rollback:
    lsf_cleanup_kprobe_prebirth_rollback();
tracepoint_rollback:
    lsf_cleanup_tracepoint_prebirth_rollback();
    return error;
#else
    return -EOPNOTSUPP;
#endif
}

static int __maybe_unused lsf_cleanup_observers_prebank_rollback(void)
{
#if defined(CONFIG_TRACEPOINTS) && defined(CONFIG_KPROBES) && defined(CONFIG_PROC_EVENTS)
    lockdep_assert_held(&factory_lock);
    if (!factory.cleanup_observer_prebirth || factory.pages || factory.opened || factory.device)
        return -EOPNOTSUPP; /* No post-birth release API exists. */
    lsf_cleanup_connector_prebirth_rollback();
    lsf_cleanup_kprobe_prebirth_rollback();
    lsf_cleanup_tracepoint_prebirth_rollback();
    factory.cleanup_observer_prebirth = 0;
    return 0;
#else
    return -EOPNOTSUPP;
#endif
}

static int lsf_cleanup_bootstrap_fits(void)
{
    unsigned long fixed = sizeof(factory) + sizeof(lsf_device_uevent_taps) +
        LSF_BACKING_BYTES + 2u * sizeof(void *);
    unsigned long irq = lsf_prepaid_cleanup_irq_bootstrap_bytes();
    unsigned long observers = lsf_cleanup_observer_bootstrap_bytes();
    return fixed <= LSF_BOOTSTRAP_CEILING && irq <= LSF_BOOTSTRAP_CEILING - fixed &&
        observers <= LSF_BOOTSTRAP_CEILING - fixed - irq;
}
