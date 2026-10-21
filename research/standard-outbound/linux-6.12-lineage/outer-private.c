/* SPDX-License-Identifier: GPL-2.0-only */
/* Included only in the authenticated net/socket.c derived translation unit.
 * Real VFS inode/socket initialization stays in the derived upstream helpers.
 * No function here manufactures an inode, security decision or final-free fact. */
#include "factory-private.h"
#include <linux/err.h>
#include <linux/in.h>
#include <net/lsf_stream_outer.h>

bool lsf_outer_superblock_supported(struct super_block *sb)
{
    return !IS_ERR_OR_NULL(sock_mnt) && sb == sock_mnt->mnt_sb &&
        sb->s_op == &sockfs_ops;
}

/* These fields are written at the actual prepaid constructor before any
 * publication. Ordinary sock_alloc_inode explicitly clears the context. They
 * are never populated from a lookup table, object address or caller proof. */
static struct socket_alloc *lsf_outer_allocation(struct inode *inode)
{
    struct socket_alloc *allocation;
    if (!lsf_outer_superblock_supported(inode->i_sb))
        return NULL;
    allocation = container_of(inode, struct socket_alloc, vfs_inode);
    return allocation->lsf_factory ? allocation : NULL;
}

void lsf_outer_inode_queue(struct inode *inode)
{
    struct socket_alloc *allocation = lsf_outer_allocation(inode);
    if (!allocation)
        return;
    if (allocation->lsf_rcu_owned ||
        !lsf_factory_deferred(allocation->lsf_factory, 1)) {
        lsf_factory_poison(allocation->lsf_factory);
        return;
    }
    allocation->lsf_rcu_owned = true;
}

/* Called by the original sockfs free_inode after the real VFS RCU callback,
 * or by the original synchronous initializer-failure i_callback. All identity
 * and callback-ownership fields are copied before returning the backing view.
 * This never frees backing pages or reports physical backing retirement. */
static bool lsf_outer_inode_return(struct socket_alloc *allocation)
{
    struct lsf_factory_context *context = allocation->lsf_factory;
    struct lsf_prepaid_ticket ticket = {
        .slot = allocation->lsf_view_slot,
        .generation = allocation->lsf_view_generation,
    };
    bool deferred = allocation->lsf_rcu_owned;
    if (!context)
        return false;
    if (!lsf_factory_return(context, ticket))
        lsf_factory_poison(context);
    if (deferred && !lsf_factory_deferred(context, 0))
        lsf_factory_poison(context);
    return true;
}

/* This prepares ONLY the real outer object; it is not a successful protocol
 * create. A selected complete consumer must still create the actual protocol
 * socket from this same private context, then call the real post-create hook.
 * No ordinary sock_create_kern/global allocation fallback is permitted. */
int lsf_outer_socket_begin(int family, int type, int protocol,
                           struct lsf_factory_context *context,
                           struct socket **result)
{
    int error;
    *result = NULL;
    if (!context || !lsf_outer_security_supported() || IS_ERR_OR_NULL(sock_mnt) ||
        !lsf_outer_superblock_supported(sock_mnt->mnt_sb))
        return -EOPNOTSUPP;
#if defined(CONFIG_LOCKDEP) || defined(CONFIG_DEBUG_LOCK_ALLOC)
    return -EOPNOTSUPP;
#endif
    if (family != PF_INET || type != SOCK_STREAM ||
        (protocol != 0 && protocol != IPPROTO_TCP))
        return -EPROTONOSUPPORT;
    error = security_socket_create(family, type, protocol, 1);
    if (error)
        return error;
    *result = lsf_outer_sock_alloc(context);
    if (!*result)
        return -ENOMEM;
    (*result)->type = type;
    return 0;
}

int lsf_outer_socket_post_create(struct socket *socket, int family, int type,
                                 int protocol, struct lsf_factory_context *context)
{
    struct socket_alloc *allocation;
    if (!socket || !socket->sk || !socket->ops || family != PF_INET ||
        type != SOCK_STREAM || socket->type != type ||
        socket->sk->sk_family != family || socket->sk->sk_protocol != IPPROTO_TCP ||
        (protocol != 0 && protocol != IPPROTO_TCP))
        return -EOPNOTSUPP;
    allocation = lsf_outer_allocation(SOCK_INODE(socket));
    if (!allocation || allocation->lsf_factory != context)
        return -EOPNOTSUPP;
    return security_socket_post_create(socket, family, type, protocol, 1);
}
