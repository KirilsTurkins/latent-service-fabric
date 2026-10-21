/* SPDX-License-Identifier: GPL-2.0-only */
/* Supplemental actual-derived-outer control with explicit VFS/LSM/type doubles.
 * No Linux, kernel layout, original VFS initializer body or physical free runs. */
#include "reference-io.h"
#include <stdbool.h>
#include <stddef.h>
#include "prepaid.h"

#define CONFIG_LSF_STREAM_FACTORY 1
#define CONFIG_SECURITY 1
#define unlikely(value) (value)
#define IS_ERR_OR_NULL(value) (!(value))
#define container_of(ptr, type, member) ((type *)((char *)(ptr) - offsetof(type, member)))
#define PF_INET 2
#define PF_INET6 10
#define SOCK_STREAM 1
#define IPPROTO_TCP 6
#define EOPNOTSUPP 95
#define EPROTONOSUPPORT 93
#define ENOMEM 12
#define GFP_KERNEL 0
#define SS_UNCONNECTED 0
#define S_IFSOCK 0140000
#define S_IRWXUGO 0777
#define BUG_ON(value) assert(!(value))

struct inode;
struct super_block;
struct rcu_head { unsigned int marker; };
struct super_operations {
    struct inode *(*alloc_inode)(struct super_block *);
    void (*free_inode)(struct inode *);
    void (*destroy_inode)(struct inode *);
};
struct super_block { const struct super_operations *s_op; };
struct inode {
    struct super_block *i_sb;
    unsigned int i_ino, i_mode, i_uid, i_gid, i_lru;
    void *i_op;
    void (*free_inode)(struct inode *);
    struct rcu_head i_rcu;
};
struct sock { int sk_family, sk_protocol; };
struct socket {
    struct { unsigned int wait, flags; void *fasync_list; } wq;
    unsigned int state;
    unsigned long flags;
    short type;
    void *ops, *file;
    struct sock *sk;
};
struct lsf_factory_context { struct lsf_prepaid_key key; };
struct socket_alloc {
    struct socket socket;
    struct inode vfs_inode;
    struct lsf_factory_context *lsf_factory;
    uint64_t lsf_view_generation;
    unsigned int lsf_view_slot;
    bool lsf_rcu_owned;
};
#define SOCKET_I(inode) (&container_of(inode, struct socket_alloc, vfs_inode)->socket)
#define SOCK_INODE(socket) (&container_of(socket, struct socket_alloc, socket)->vfs_inode)
static struct { struct super_block *mnt_sb; } mount;
static __typeof__(mount) *sock_mnt = &mount;
static int sock_inode_cachep, inode_cachep, sockfs_inode_ops;
static struct socket_alloc normal;
static struct super_block sb, foreign_sb;
static struct lsf_prepaid pool;
static struct lsf_factory_context context;
static _Alignas(64) unsigned char backing[LSF_BACKING_BYTES];
static unsigned int normal_allocated, normal_freed, initialized_once, initialized_always,
    returned, deferred_started, deferred_stopped, destroyed, poisoned, socket_security,
    post_security, allocation_fail, initializer_fail;
static struct rcu_head *pending;
static void (*callback)(struct rcu_head *);

static void inode_init_once(struct inode *inode)
{
    memset(inode, 0, sizeof(*inode));
    initialized_once++;
}
static int inode_init_always(struct super_block *super, struct inode *inode)
{
    inode->i_sb = super;
    initialized_always++;
    return (int)initializer_fail;
}
static void *alloc_inode_sb(struct super_block *super, int cache, int flags)
{
    (void)super; (void)cache; (void)flags;
    normal_allocated++;
    inode_init_once(&normal.vfs_inode);
    return &normal;
}
static void kmem_cache_free(int cache, void *value)
{
    (void)cache;
    assert(value == &normal);
    normal_freed++;
}
static void init_waitqueue_head(unsigned int *wait) { *wait = 17; }
static unsigned int get_next_ino(void) { return 23; }
static unsigned int current_fsuid(void) { return 29; }
static unsigned int current_fsgid(void) { return 31; }
static int list_empty(unsigned int *list) { return !*list; }
static void __destroy_inode(struct inode *inode) { (void)inode; destroyed++; }
static void free_inode_nonrcu(struct inode *inode) { (void)inode; assert(0); }
static void call_rcu(struct rcu_head *head, void (*fn)(struct rcu_head *))
{
    assert(!pending); pending = head; callback = fn;
}
static void *lsf_factory_allocate(struct lsf_factory_context *owner, unsigned long bytes,
    struct lsf_prepaid_ticket parent, int descendant, struct lsf_prepaid_ticket *ticket)
{
    lsf_u64 offset;
    assert(owner == &context);
    if (allocation_fail || !lsf_prepaid_allocate(&pool, owner->key, bytes, descendant, parent, ticket, &offset))
        return NULL;
    memset(backing + offset, 0, bytes);
    return backing + offset;
}
static int lsf_factory_return(struct lsf_factory_context *owner, struct lsf_prepaid_ticket ticket)
{
    assert(owner == &context);
    if (!lsf_prepaid_return(&pool, owner->key, ticket)) return 0;
    returned++;
    return 1;
}
static int lsf_factory_deferred(struct lsf_factory_context *owner, int acquire)
{
    assert(owner == &context);
    if (!lsf_prepaid_continuation(&pool, owner->key, acquire)) return 0;
    if (acquire) deferred_started++; else deferred_stopped++;
    return 1;
}
static void lsf_factory_poison(struct lsf_factory_context *owner)
{
    assert(owner == &context);
    poisoned++;
    pool.contexts[owner->key.slot].poisoned = 1;
}
static int security_socket_create(int family, int type, int protocol, int kernel)
{
    assert(family == PF_INET && type == SOCK_STREAM && protocol == IPPROTO_TCP && kernel == 1);
    socket_security++;
    return 0;
}
static int security_socket_post_create(struct socket *socket, int family, int type, int protocol, int kernel)
{
    assert(socket && family == PF_INET && type == SOCK_STREAM && protocol == IPPROTO_TCP && kernel == 1);
    post_security++;
    return 0;
}
struct active_key { unsigned int key; };
struct lsm_static_call { struct active_key *active; };
static struct active_key hook_keys[10];
static struct {
    struct lsm_static_call inode_alloc_security[2], inode_free_security[2],
        inode_free_security_rcu[2], socket_create[2], socket_post_create[2];
} static_calls_table;
static void *lsm_inode_cache;
static struct { unsigned int lbs_inode; } blob_sizes;
#define MAX_LSM_COUNT 2
#define static_key_enabled(key) (*(key))
#define lsm_for_each_hook(scall, NAME) \
    for (scall = static_calls_table.NAME; scall - static_calls_table.NAME < MAX_LSM_COUNT; scall++) \
        if (static_key_enabled(&scall->active->key))
static bool lsf_outer_inode_return(struct socket_alloc *);
static bool lsf_outer_security_supported(void);
static bool lsf_outer_superblock_supported(struct super_block *);
static struct inode *lsf_outer_alloc_inode(struct super_block *, struct lsf_factory_context *);
static struct inode *lsf_prepaid_new_inode(struct super_block *, struct lsf_factory_context *);
static struct socket *lsf_outer_sock_alloc(struct lsf_factory_context *);
static void lsf_outer_inode_queue(struct inode *);
/* The generated header contains exact source-derived function bodies. Only
 * linkage/header plumbing is adapted to these explicit single-TU doubles. */
#include "outer-derived-reference.h"

static void reset(void)
{
    struct lsf_scope scope = {{1,2,3,4,5,6,7,8}};
    unsigned int i;
    memset(&pool, 0, sizeof(pool)); memset(backing, 0, sizeof(backing));
    memset(&normal, 0, sizeof(normal)); memset(hook_keys, 0, sizeof(hook_keys));
    assert(lsf_prepaid_initialize(&pool));
    assert(lsf_prepaid_context_create(&pool, scope, LSF_TCP_BYTES, &context.key));
    for (i = 0; i < 2; ++i) {
        static_calls_table.inode_alloc_security[i].active = &hook_keys[i];
        static_calls_table.inode_free_security[i].active = &hook_keys[i + 2];
        static_calls_table.inode_free_security_rcu[i].active = &hook_keys[i + 4];
        static_calls_table.socket_create[i].active = &hook_keys[i + 6];
        static_calls_table.socket_post_create[i].active = &hook_keys[i + 8];
    }
    sb.s_op = &sockfs_ops; foreign_sb.s_op = &sockfs_ops;
    mount.mnt_sb = &sb; sock_mnt = &mount; lsm_inode_cache = NULL; blob_sizes.lbs_inode = 0;
    normal_allocated = normal_freed = initialized_once = initialized_always = returned =
        deferred_started = deferred_stopped = destroyed = poisoned = socket_security =
        post_security = allocation_fail = initializer_fail = 0;
    pending = NULL; callback = NULL;
}
static void passed(const char *label)
{
    lsf_ref_write("OUTER_CONTROL ", 14);
    lsf_ref_write(label, lsf_ref_length(label));
    lsf_ref_write(" PASS\n", 6);
}
int main(void)
{
    struct socket *socket;
    struct inode *inode;
    struct sock protocol = {PF_INET, IPPROTO_TCP};
    unsigned int i;
    (void)inode_cachep;
    reset();
#ifdef LSF_OLD_OUTER
    socket = sock_alloc();
    if (socket && normal_allocated == 1 && pool.contexts[context.key.slot].live == 0) {
        const char *label = "OUTER_OLD uncharged-general-outer RED\n";
        lsf_ref_write(label, lsf_ref_length(label));
        return 2;
    }
    return 3;
#endif
    assert(lsf_outer_socket_begin(PF_INET, SOCK_STREAM, IPPROTO_TCP, &context, &socket) == 0);
    inode = SOCK_INODE(socket);
    assert(normal_allocated == 0 && initialized_once == 1 && initialized_always == 1);
    assert(pool.contexts[context.key.slot].live == 1 && socket_security == 1);
    assert(inode->i_ino == 23 && inode->i_uid == 29 && inode->i_gid == 31);
    assert(socket->type == SOCK_STREAM && socket->wq.wait == 17);
    passed("actual-private-clones-retain-original-initializer-and-metadata");
    assert(lsf_outer_socket_post_create(socket, PF_INET, SOCK_STREAM, IPPROTO_TCP, &context) == -EOPNOTSUPP);
    assert(!post_security);
    passed("outer-only-success-is-not-protocol-success");
    socket->sk = &protocol; socket->ops = &sockfs_inode_ops;
    assert(lsf_outer_socket_post_create(socket, PF_INET, SOCK_STREAM, IPPROTO_TCP, &context) == 0);
    assert(post_security == 1);
    passed("actual-post-hook-requires-initialized-protocol-and-original-context");
    destroy_inode(inode);
    assert(pending && deferred_started == 1 && returned == 0 && destroyed == 1);
    assert(pool.contexts[context.key.slot].live == 1 && pool.contexts[context.key.slot].continuations == 1);
    passed("actual-destroy-queues-rcu-with-both-view-and-deferred-ownership");
    callback(pending); pending = NULL;
    assert(returned == 1 && deferred_stopped == 1 && !normal_freed && !poisoned);
    assert(pool.records[0].phase == LSF_PREPAID_LIVE && pool.contexts[context.key.slot].live == 0);
    passed("real-callback-copies-tokens-before-view-return-backing-remains-live");

    reset(); initializer_fail = 1;
    assert(lsf_outer_socket_begin(PF_INET, SOCK_STREAM, IPPROTO_TCP, &context, &socket) == -ENOMEM);
    assert(!socket && returned == 1 && !pending && !deferred_started && !normal_freed);
    assert(pool.records[0].phase == LSF_PREPAID_LIVE);
    passed("original-initializer-failure-uses-actual-synchronous-callback");

    reset(); allocation_fail = 1;
    assert(lsf_outer_socket_begin(PF_INET, SOCK_STREAM, IPPROTO_TCP, &context, &socket) == -ENOMEM);
    assert(!socket && !normal_allocated && !initialized_once && !returned);
    passed("prepaid-allocation-refusal-never-falls-back");

    reset();
    for (i = 0; i < 10; ++i) {
        hook_keys[i].key = 1;
        assert(lsf_outer_socket_begin(PF_INET, SOCK_STREAM, IPPROTO_TCP, &context, &socket) == -EOPNOTSUPP);
        assert(!socket && !normal_allocated && !socket_security && !pool.contexts[context.key.slot].live);
        hook_keys[i].key = 0;
    }
    passed("every-active-security-hook-refuses-before-security-or-allocation");
    blob_sizes.lbs_inode = 1;
    assert(!lsf_outer_security_supported()); blob_sizes.lbs_inode = 0;
    lsm_inode_cache = &normal;
    assert(!lsf_outer_security_supported());
    passed("unclosed-security-blob-and-cache-refuse");

    reset(); sock_mnt = NULL;
    assert(!lsf_outer_superblock_supported(&sb));
    assert(lsf_outer_socket_begin(PF_INET, SOCK_STREAM, IPPROTO_TCP, &context, &socket) == -EOPNOTSUPP);
    sock_mnt = &mount;
    assert(!lsf_outer_superblock_supported(&foreign_sb));
    assert(!lsf_outer_alloc_inode(&foreign_sb, &context));
    passed("uninitialized-or-foreign-sockfs-refuses-before-allocation");

    reset(); normal.lsf_factory = &context;
    socket = sock_alloc();
    assert(socket && normal_allocated == 1 && !normal.lsf_factory);
    sock_free_inode(SOCK_INODE(socket));
    assert(normal_freed == 1 && !returned && !deferred_started);
    passed("ordinary-host-socket-keeps-original-allocator-and-free");

    reset();
    assert(lsf_outer_socket_begin(PF_INET, SOCK_STREAM, IPPROTO_TCP, &context, &socket) == 0);
    inode = SOCK_INODE(socket);
    lsf_outer_inode_queue(inode);
    lsf_outer_inode_queue(inode);
    assert(poisoned == 1 && pool.contexts[context.key.slot].live == 1);
    assert(pool.contexts[context.key.slot].continuations == 1);
    passed("duplicate-deferred-notification-poisons-without-refund");
    return 0;
}
