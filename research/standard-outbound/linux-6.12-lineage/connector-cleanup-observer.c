/* SPDX-License-Identifier: GPL-2.0-only */
unsigned long lsf_cleanup_connector_seal_bytes(void)
{
    return sizeof(lsf_cleanup_connector_state);
}

int lsf_cleanup_connector_prebirth_seal(void)
{
    int error = -EOPNOTSUPP;
    mutex_lock(&lsf_cleanup_connector_state.mutex);
    /* Exact zero; an invalid negative count is never certified as absence. */
    if (!lsf_cleanup_connector_state.sealed && !atomic_read(&proc_event_num_listeners)) {
        lsf_cleanup_connector_state.sealed = 2u;
        error = 0;
    }
    mutex_unlock(&lsf_cleanup_connector_state.mutex);
    return error;
}

void lsf_cleanup_connector_prebirth_rollback(void)
{
    mutex_lock(&lsf_cleanup_connector_state.mutex);
    lsf_cleanup_connector_state.sealed = 0;
    mutex_unlock(&lsf_cleanup_connector_state.mutex);
}
