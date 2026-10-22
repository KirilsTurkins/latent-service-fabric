/* SPDX-License-Identifier: GPL-2.0-only */
/* The original acct_on_mutex serializes all real init_pid_ns installs. The
 * preparation count extends that exclusion across getname/open/unwind. */
static struct { unsigned int sealed, preparing, uncertain; } lsf_cleanup_acct_state;

static int lsf_cleanup_acct_prepare_begin(void)
{
    int error = -EOPNOTSUPP;
    mutex_lock(&acct_on_mutex);
    if (!lsf_cleanup_acct_state.sealed && !lsf_cleanup_acct_state.uncertain) {
        if (lsf_cleanup_acct_state.preparing == ~0u) {
            lsf_cleanup_acct_state.uncertain = 1u;
            error = -EOVERFLOW;
        } else {
            lsf_cleanup_acct_state.preparing++;
            error = 0;
        }
    }
    mutex_unlock(&acct_on_mutex);
    return error;
}

static void lsf_cleanup_acct_prepare_end(void)
{
    mutex_lock(&acct_on_mutex);
    if (lsf_cleanup_acct_state.preparing)
        lsf_cleanup_acct_state.preparing--;
    else
        lsf_cleanup_acct_state.uncertain = 1u;
    mutex_unlock(&acct_on_mutex);
}

unsigned long lsf_cleanup_acct_seal_bytes(void)
{
    return sizeof(lsf_cleanup_acct_state);
}

int lsf_cleanup_acct_prebirth_seal(void)
{
    int error = -EOPNOTSUPP;
    mutex_lock(&acct_on_mutex);
    if (!lsf_cleanup_acct_state.sealed && !lsf_cleanup_acct_state.preparing &&
        !lsf_cleanup_acct_state.uncertain && !READ_ONCE(init_pid_ns.bacct)) {
        lsf_cleanup_acct_state.sealed = 1u;
        error = 0;
    }
    mutex_unlock(&acct_on_mutex);
    return error;
}

void lsf_cleanup_acct_prebirth_rollback(void)
{
    mutex_lock(&acct_on_mutex);
    lsf_cleanup_acct_state.sealed = 0;
    mutex_unlock(&acct_on_mutex);
}
