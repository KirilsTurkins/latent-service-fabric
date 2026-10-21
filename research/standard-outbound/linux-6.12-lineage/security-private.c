/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in authenticated maintained security/security.c, after its original
 * definitions. This routes the actual composite blobs, NOT LSM policy or hook
 * decisions. The original hook loops, error cleanup and RCU callback still run.
 * Unknown active hook/Netlabel allocation closure remains a selection hardgate;
 * this prefix does not make the factory selectable. */
#include "../net/factory-private.h"

static int lsf_prepaid_lsm_inode_alloc(struct inode *inode, gfp_t gfp,
                                       struct lsf_factory_context *context)
{
    if (!context || gfp != GFP_NOFS)
        return -EOPNOTSUPP;
    if (!lsm_inode_cache) {
        inode->i_security = NULL;
        return 0;
    }
    if (blob_sizes.lbs_inode <= 0 || (unsigned int)blob_sizes.lbs_inode > LSF_TCP_BYTES)
        return -EOPNOTSUPP;
    inode->i_security = lsf_factory_blob_allocate(context, blob_sizes.lbs_inode,
                                                  LSF_PREPAID_INODE_BLOB);
    return inode->i_security ? 0 : -ENOMEM;
}

static int lsf_prepaid_lsm_sock_alloc(struct sock *sock, gfp_t gfp,
                                      struct lsf_factory_context *context)
{
    if (!context || gfp != (GFP_KERNEL | __GFP_ZERO))
        return -EOPNOTSUPP;
    if (blob_sizes.lbs_sock == 0) {
        sock->sk_security = NULL;
        return 0;
    }
    if (blob_sizes.lbs_sock < 0 || (unsigned int)blob_sizes.lbs_sock > LSF_TCP_BYTES)
        return -EOPNOTSUPP;
    sock->sk_security = lsf_factory_blob_allocate(context, blob_sizes.lbs_sock,
                                                 LSF_PREPAID_SOCK_BLOB);
    return sock->sk_security ? 0 : -ENOMEM;
}
