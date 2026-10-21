/* SPDX-License-Identifier: GPL-2.0-only */
/* Included only inside the authenticated security/security.c translation unit.
 * Reject an unclosed active hook/blob path, rather than disable or skip it.
 * This source prefix does not qualify socket security, RX or protocol closure. */
bool lsf_outer_security_supported(void)
{
    struct lsm_static_call *scall;
    if (lsm_inode_cache || blob_sizes.lbs_inode)
        return false;
    lsm_for_each_hook(scall, inode_alloc_security) { return false; }
    lsm_for_each_hook(scall, inode_free_security) { return false; }
    lsm_for_each_hook(scall, inode_free_security_rcu) { return false; }
    lsm_for_each_hook(scall, socket_create) { return false; }
    lsm_for_each_hook(scall, socket_post_create) { return false; }
    return true;
}
