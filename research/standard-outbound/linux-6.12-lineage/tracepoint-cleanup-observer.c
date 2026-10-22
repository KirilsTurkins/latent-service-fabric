/* SPDX-License-Identifier: GPL-2.0-only */
/* Included at the end of the actual tracepoint TU. Never detaches a callback. */
static void lsf_cleanup_tracepoint_observed(struct tracepoint *tp, void *priv)
{
    int *observed = priv;
    lockdep_assert_held(&tracepoints_mutex);
    if (rcu_dereference_protected(tp->funcs, lockdep_is_held(&tracepoints_mutex)))
        *observed = 1;
}

#ifdef CONFIG_MODULES
static void lsf_cleanup_module_tracepoint_observed(struct tracepoint *tp,
    struct module *mod, void *priv)
{
    (void)mod;
    lsf_cleanup_tracepoint_observed(tp, priv);
}

static int lsf_cleanup_tracepoint_module_check(struct module *mod)
{
    int observed = 0, error = 0;
    /* Actual existing module notification order is module-list -> probes. */
    mutex_lock(&tracepoint_module_list_mutex);
    mutex_lock(&tracepoints_mutex);
    /* The maintained original avoids bad-taint metadata because mismatched
     * module headers can make it unsafe. Never scan it to prove absence. */
    if (trace_module_has_bad_taint(mod)) {
        if (lsf_cleanup_tracepoint_state.sealed)
            error = -EOPNOTSUPP;
        else
            lsf_cleanup_tracepoint_state.uncertain = 1u;
        goto out;
    }
    for_each_tracepoint_in_module(mod, lsf_cleanup_module_tracepoint_observed, &observed);
    if (observed) {
        if (lsf_cleanup_tracepoint_state.sealed)
            error = -EOPNOTSUPP;
        else
            lsf_cleanup_tracepoint_state.uncertain = 1u; /* Not central publication. */
    }
out:
    mutex_unlock(&tracepoints_mutex);
    mutex_unlock(&tracepoint_module_list_mutex);
    return error;
}
#endif

static int lsf_cleanup_tracepoints_observed_locked(void)
{
    int observed = 0;
#ifdef CONFIG_MODULES
    struct tp_module *tp_mod;
    lockdep_assert_held(&tracepoint_module_list_mutex);
#endif
    lockdep_assert_held(&tracepoints_mutex);
    if (lsf_cleanup_tracepoint_state.heads || lsf_cleanup_tracepoint_state.uncertain)
        return 1;
    for_each_kernel_tracepoint(lsf_cleanup_tracepoint_observed, &observed);
#ifdef CONFIG_MODULES
    list_for_each_entry(tp_mod, &tracepoint_module_list, list)
        for_each_tracepoint_in_module(tp_mod->mod,
            lsf_cleanup_module_tracepoint_observed, &observed);
#endif
    return observed;
}

unsigned long lsf_cleanup_tracepoint_seal_bytes(void)
{
    return sizeof(lsf_cleanup_tracepoint_state);
}

int lsf_cleanup_tracepoint_prebirth_seal(void)
{
    int error = -EOPNOTSUPP;
#ifdef CONFIG_MODULES
    mutex_lock(&tracepoint_module_list_mutex);
#endif
    mutex_lock(&tracepoints_mutex);
    if (lsf_cleanup_tracepoint_state.sealed || lsf_cleanup_tracepoints_observed_locked())
        goto first_out;
    lsf_cleanup_tracepoint_state.sealed = 1u; /* Blocks every actual new publisher. */
    error = 0;
first_out:
    mutex_unlock(&tracepoints_mutex);
#ifdef CONFIG_MODULES
    mutex_unlock(&tracepoint_module_list_mutex);
#endif
    if (error)
        return error;
    /* Exact maintained SRCU+RCU unregister synchronization, outside locks. */
    tracepoint_synchronize_unregister();
#ifdef CONFIG_MODULES
    mutex_lock(&tracepoint_module_list_mutex);
#endif
    mutex_lock(&tracepoints_mutex);
    if (lsf_cleanup_tracepoint_state.sealed != 1u || lsf_cleanup_tracepoints_observed_locked()) {
        error = -EOPNOTSUPP;
        lsf_cleanup_tracepoint_state.sealed = 0;
    } else {
        lsf_cleanup_tracepoint_state.sealed = 2u;
    }
    mutex_unlock(&tracepoints_mutex);
#ifdef CONFIG_MODULES
    mutex_unlock(&tracepoint_module_list_mutex);
#endif
    return error;
}

/* Sole caller is the factory's checked pre-bank failure unwind. There is no
 * post-birth unseal or physical/native final-free implementation. */
void lsf_cleanup_tracepoint_prebirth_rollback(void)
{
    mutex_lock(&tracepoints_mutex);
    lsf_cleanup_tracepoint_state.sealed = 0;
    mutex_unlock(&tracepoints_mutex);
}
