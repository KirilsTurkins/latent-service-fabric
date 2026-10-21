/* SPDX-License-Identifier: GPL-2.0-only */
/* Uninstalled builtin candidate. No Kconfig/Makefile or supported profile. */
#include <linux/capability.h>
#include <linux/cred.h>
#include <linux/fs.h>
#include <linux/in.h>
#include <linux/miscdevice.h>
#include <linux/mm.h>
#include <linux/mutex.h>
#include <linux/module.h>
#include <linux/nsproxy.h>
#include <linux/pid.h>
#include <linux/sched/mm.h>
#include <linux/spinlock.h>
#include <linux/uaccess.h>
#include <linux/user_namespace.h>
#include <net/net_namespace.h>
#include "factory-private.h"

#define LSF_FACTORY_MAGIC 0x4c534646u
#define LSF_FACTORY_VERSION 1u
/* Wire is explicit little-endian scalars; no pointer, byte-cost, free ticket,
 * qualification flag, physical-layout certificate or release operation. */
struct lsf_factory_create {
    __le32 magic, version, family, type, protocol, reserved;
    __le64 scope[8], lease;
};
struct lsf_factory_reply { __le64 lease, handle; };
struct lsf_factory_context {
    struct lsf_prepaid_key key;
    struct socket *socket;
    struct net *net;
    lsf_u64 lease;
};
static struct {
    struct lsf_prepaid pool;
    struct lsf_factory_context contexts[LSF_FACTORY_CONTEXTS];
    struct page *pages;
    struct mm_struct *mm;
    struct pid *tgid;
    const struct cred *cred;
    struct net *net;
    struct lsf_factory_reply reply;
    lsf_u64 last_lease;
    unsigned int opened, reply_pending, inflight, uncertain;
} factory;
static DEFINE_MUTEX(factory_lock);
static DEFINE_SPINLOCK(pool_lock);

/* These source assertions cover only the candidate backing + static metadata.
 * They DO NOT prove VFS/LSM/RX/device or full platform costs. Registration stays
 * unavailable until the complete selection is source-authenticated. */
static_assert(PAGE_SIZE == 4096);
static_assert((PAGE_SIZE << LSF_BACKING_ORDER) == LSF_BACKING_BYTES);
static_assert(sizeof(factory) + LSF_BACKING_BYTES < LSF_BOOTSTRAP_CEILING);

static int lsf_factory_actor(struct file *file)
{
    return file->private_data == &factory && factory.mm == current->mm &&
        factory.tgid == task_tgid(current) && factory.cred == current_cred() &&
        file->f_cred == factory.cred && current->nsproxy->net_ns == factory.net;
}

static int lsf_factory_open(struct inode *inode, struct file *file)
{
    int error = -EOPNOTSUPP;
    (void)inode;
    /* Check BEFORE any candidate backing allocation or reference ownership.
     * Root credentials alone cannot assert closure or activate this backend. */
    if (!lsf_factory_selected_consumer())
        return error;
    if (!ns_capable(&init_user_ns, CAP_SYS_ADMIN))
        return -EPERM;
    mutex_lock(&factory_lock);
    if (factory.opened || READ_ONCE(factory.uncertain)) {
        error = -EBUSY;
        goto out;
    }
    /* Never alloc_pages_exact: its transient rounded allocation could exceed
     * the charged extent. No retry, lower-order or generic allocator fallback. */
    factory.pages = alloc_pages(GFP_KERNEL | __GFP_ZERO | __GFP_NORETRY,
                                LSF_BACKING_ORDER);
    if (!factory.pages) {
        error = -ENOMEM;
        goto out;
    }
    if (!lsf_prepaid_initialize(&factory.pool)) {
        WRITE_ONCE(factory.uncertain, 1);
        goto out;
    }
    factory.mm = current->mm;
    mmgrab(factory.mm);
    factory.tgid = get_pid(task_tgid(current));
    factory.cred = get_current_cred();
    factory.net = get_net(current->nsproxy->net_ns);
    factory.opened = 1;
    file->private_data = &factory;
    error = 0;
out:
    mutex_unlock(&factory_lock);
    return error;
}

static struct lsf_factory_context *lsf_factory_context_current(
    struct lsf_factory_context *context)
{
    unsigned int i;
    /* Never dereference an arbitrary pointer before proving exact membership. */
    for (i = 0; i < LSF_FACTORY_CONTEXTS; ++i)
        if (context == &factory.contexts[i] &&
            lsf_prepaid_context_for(&factory.pool, context->key))
            return context;
    return NULL;
}

void *lsf_factory_allocate(struct lsf_factory_context *context, unsigned long bytes,
                         struct lsf_prepaid_ticket parent, int descendant,
                         struct lsf_prepaid_ticket *ticket)
{
    lsf_u64 offset;
    unsigned long flags;
    void *result = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    context = lsf_factory_context_current(context);
    if (context && lsf_prepaid_allocate(&factory.pool, context->key, bytes,
                                       descendant, parent, ticket, &offset)) {
        result = (char *)page_address(factory.pages) + offset;
        memset(result, 0, bytes);
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_return(struct lsf_factory_context *context,
                       struct lsf_prepaid_ticket ticket)
{
    int returned = 0;
    unsigned long flags;
    spin_lock_irqsave(&pool_lock, flags);
    context = lsf_factory_context_current(context);
    if (context)
        returned = lsf_prepaid_return(&factory.pool, context->key, ticket);
    spin_unlock_irqrestore(&pool_lock, flags);
    return returned;
}

int lsf_factory_deferred(struct lsf_factory_context *context, int acquire)
{
    int retained = 0;
    unsigned long flags;
    spin_lock_irqsave(&pool_lock, flags);
    context = lsf_factory_context_current(context);
    if (context)
        retained = lsf_prepaid_continuation(&factory.pool, context->key, acquire);
    spin_unlock_irqrestore(&pool_lock, flags);
    return retained;
}

void *lsf_factory_blob_allocate(struct lsf_factory_context *context,
                               unsigned long bytes, unsigned int kind)
{
    struct lsf_prepaid_ticket ticket;
    lsf_u64 offset;
    unsigned long flags;
    void *result = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    context = lsf_factory_context_current(context);
    if (context && lsf_prepaid_blob_allocate(&factory.pool, context->key,
                                            bytes, kind, &ticket, &offset)) {
        result = (char *)page_address(factory.pages) + offset;
        memset(result, 0, bytes);
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void *lsf_factory_child_allocate(struct lsf_factory_blob parent,
                                 unsigned long bytes, unsigned int kind)
{
    struct lsf_factory_context *context;
    struct lsf_prepaid_ticket ticket;
    lsf_u64 offset;
    unsigned long flags;
    void *result = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    context = lsf_factory_context_current(parent.context);
    if (context && lsf_prepaid_child_allocate(&factory.pool, context->key, bytes,
                                               kind, parent.ticket, &ticket, &offset)) {
        result = (char *)page_address(factory.pages) + offset;
        memset(result, 0, bytes);
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Read only the origin established before the original socket was published.
 * An exact live record must ALREADY match that object's actual address. This
 * cannot register an unrelated socket or create a new context/admission. */
int lsf_factory_protocol_parent(const void *address,
    struct lsf_factory_context *context, struct lsf_prepaid_ticket ticket,
    struct lsf_factory_blob *copy)
{
    struct lsf_prepaid_view *record;
    unsigned long flags, base, value = (unsigned long)address;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    context = lsf_factory_context_current(context);
    if (!context || !factory.pages || !ticket.slot ||
        ticket.slot >= LSF_ALLOCATION_SLOTS || !copy)
        goto invalid;
    record = &factory.pool.records[ticket.slot];
    base = (unsigned long)page_address(factory.pages);
    if (value < base || value - base >= LSF_BACKING_BYTES ||
        record->offset != value - base || record->phase != LSF_PREPAID_LIVE ||
        record->kind != LSF_PREPAID_OBJECT || record->deferred ||
        record->generation != ticket.generation || record->owner != context->key.slot ||
        record->owner_generation != context->key.generation)
        goto invalid;
    copy->context = context;
    copy->ticket = ticket;
    result = 1;
    goto out;
invalid:
    factory.pool.poisoned = 1;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Caller holds pool_lock. No dereference of address occurs. Classification
 * outside this single protected extent retains the original normal free path.
 * Exact births INSIDE it are the only valid private returns. Unknown interior
 * addresses fence the pool; they are NEVER passed to a normal allocator. */
static int lsf_factory_blob_lookup_locked(const void *address, unsigned int kind,
                                          struct lsf_factory_blob *copy)
{
    struct lsf_prepaid_key key;
    struct lsf_prepaid_ticket ticket;
    unsigned long base, value = (unsigned long)address;
    if (!factory.pages)
        return 0;
    base = (unsigned long)page_address(factory.pages);
    if (value < base || value - base >= LSF_BACKING_BYTES)
        return 0;
    if (!lsf_prepaid_blob_find(&factory.pool, value - base, kind, &key, &ticket))
        return -1;
    copy->context = &factory.contexts[key.slot];
    copy->ticket = ticket;
    return 1;
}

int lsf_factory_blob_lookup(const void *address, unsigned int kind,
                            struct lsf_factory_blob *copy)
{
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_factory_blob_lookup_locked(address, kind, copy);
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_blob_queue(const void *address)
{
    struct lsf_factory_blob copy;
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_factory_blob_lookup_locked(address, LSF_PREPAID_INODE_BLOB, &copy);
    if (result == 1 && !lsf_prepaid_blob_queue(&factory.pool, copy.context->key,
                                              copy.ticket))
        result = -1;
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_options_publish(const void *address)
{
    struct lsf_factory_blob copy;
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_factory_blob_lookup_locked(address, LSF_PREPAID_IP_OPTIONS, &copy);
    if (result == 1 && !lsf_prepaid_options_publish(&factory.pool, copy.context->key,
                                                  copy.ticket))
        result = -1;
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Owned replacement must not inherit an uncharged normal or other-context
 * option. Ordinary sockets still use their original producers/free paths. */
int lsf_factory_options_owned(const void *address, struct lsf_factory_blob parent)
{
    struct lsf_factory_blob copy;
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_factory_blob_lookup_locked(address, LSF_PREPAID_IP_OPTIONS, &copy);
    if (result != 1 || copy.context != lsf_factory_context_current(parent.context) ||
        factory.pool.records[copy.ticket.slot].deferred != LSF_PREPAID_PUBLISHED) {
        factory.pool.poisoned = 1;
        result = 0;
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_options_queue(const void *address)
{
    struct lsf_factory_blob copy;
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_factory_blob_lookup_locked(address, LSF_PREPAID_IP_OPTIONS, &copy);
    if (result == 1 && !lsf_prepaid_record_queue(&factory.pool, copy.context->key,
                                               copy.ticket, LSF_PREPAID_IP_OPTIONS))
        result = -1;
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_blob_finish(struct lsf_factory_blob copy, unsigned int kind)
{
    struct lsf_factory_context *context;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    context = lsf_factory_context_current(copy.context);
    if (context)
        result = lsf_prepaid_blob_finish(&factory.pool, context->key, copy.ticket, kind);
    if (!result)
        factory.pool.poisoned = 1;
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

void lsf_factory_poison(struct lsf_factory_context *context)
{
    unsigned long flags;
    spin_lock_irqsave(&pool_lock, flags);
    /* Prove exact static membership/current generation before dereferencing
     * this private pointer. Unknown origin still fences the entire factory;
     * it cannot create a release or silently return availability. */
    context = lsf_factory_context_current(context);
    if (context)
        factory.pool.contexts[context->key.slot].poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
    spin_unlock_irqrestore(&pool_lock, flags);
}

static ssize_t lsf_factory_write(struct file *file, const char __user *buffer,
                                 size_t count, loff_t *position)
{
    const struct lsf_factory_consumer *consumer = lsf_factory_selected_consumer();
    struct lsf_factory_create request;
    struct lsf_factory_context *context;
    struct lsf_scope scope;
    struct lsf_prepaid_key key;
    unsigned int i, family, type, protocol;
    unsigned long flags;
    lsf_u64 maximum, lease;
    int error;
    (void)position;
    if (!consumer)
        return -EOPNOTSUPP;
    if (count != sizeof(request) || copy_from_user(&request, buffer, sizeof(request)))
        return -EINVAL;
    family = le32_to_cpu(request.family);
    type = le32_to_cpu(request.type);
    protocol = le32_to_cpu(request.protocol);
    lease = le64_to_cpu(request.lease);
    if (le32_to_cpu(request.magic) != LSF_FACTORY_MAGIC ||
        le32_to_cpu(request.version) != LSF_FACTORY_VERSION || request.reserved ||
        !lease || family != AF_INET ||
        !((type == SOCK_STREAM && protocol == IPPROTO_TCP) ||
          (type == SOCK_DGRAM && protocol == IPPROTO_UDP)))
        return -EOPNOTSUPP;
    for (i = 0; i < 8; ++i)
        scope.identity[i] = le64_to_cpu(request.scope[i]);
    maximum = type == SOCK_STREAM ? LSF_TCP_BYTES : LSF_DNS_BYTES;
    mutex_lock(&factory_lock);
    if (!lsf_factory_actor(file) || READ_ONCE(factory.uncertain) || factory.reply_pending ||
        factory.inflight || lease <= factory.last_lease) {
        error = -EPERM;
        goto out;
    }
    /* Context exists before the consumer may enter ANY outer allocation/LSM.
     * No sock_create_kern fallback, socket lookup or later attestation exists. */
    spin_lock_irqsave(&pool_lock, flags);
    error = lsf_prepaid_context_create(&factory.pool, scope, maximum, &key);
    spin_unlock_irqrestore(&pool_lock, flags);
    if (!error) {
        error = -ENOBUFS;
        goto out;
    }
    context = &factory.contexts[key.slot];
    context->key = key;
    context->net = factory.net;
    context->lease = lease;
    factory.last_lease = lease;
    factory.inflight = 1;
    /* A native caller must retain this original lease after possible entry,
     * even when copy-out fails, the fd closes, or create reports uncertainty. */
    mutex_unlock(&factory_lock);
    error = consumer->create(factory.net, family, type, protocol, context, &context->socket);
    mutex_lock(&factory_lock);
    factory.inflight = 0;
    if (error || !context->socket || factory.pool.stopped) {
        WRITE_ONCE(factory.uncertain, 1);
        error = error < 0 ? error : -EIO;
        goto out;
    }
    factory.reply.lease = cpu_to_le64(lease);
    factory.reply.handle = cpu_to_le64(key.generation);
    factory.reply_pending = 1;
    error = sizeof(request);
out:
    mutex_unlock(&factory_lock);
    return error;
}

static ssize_t lsf_factory_read(struct file *file, char __user *buffer,
                                size_t count, loff_t *position)
{
    int error = -EINVAL;
    (void)position;
    mutex_lock(&factory_lock);
    if (!lsf_factory_actor(file))
        error = -EPERM;
    else if (count == sizeof(factory.reply) && factory.reply_pending) {
        if (copy_to_user(buffer, &factory.reply, sizeof(factory.reply))) {
            WRITE_ONCE(factory.uncertain, 1);
            error = -EFAULT;
        } else {
            factory.reply_pending = 0;
            error = sizeof(factory.reply);
        }
    }
    mutex_unlock(&factory_lock);
    return error;
}

static int lsf_factory_release(struct inode *inode, struct file *file)
{
    unsigned int i;
    unsigned long flags;
    (void)inode;
    (void)file;
    mutex_lock(&factory_lock);
    spin_lock_irqsave(&pool_lock, flags);
    factory.pool.stopped = 1;
    WRITE_ONCE(factory.uncertain, 1);
    for (i = 0; i < LSF_FACTORY_CONTEXTS; ++i)
        factory.pool.contexts[i].closed = 1;
    spin_unlock_irqrestore(&pool_lock, flags);
    /* Closing a descriptor is not final-free. No __free_pages, object release,
     * owner recycling, reference refund or reopen is justified here. Original
     * node backing and occupancy must stay in bounded native quarantine. */
    mutex_unlock(&factory_lock);
    return 0;
}

static const struct file_operations lsf_factory_operations = {
    .owner = THIS_MODULE,
    .open = lsf_factory_open,
    .read = lsf_factory_read,
    .write = lsf_factory_write,
    .release = lsf_factory_release,
    .llseek = no_llseek,
};
static struct miscdevice lsf_factory_device = {
    .minor = MISC_DYNAMIC_MINOR,
    .name = "lsf-stream-factory",
    .mode = 0600,
    .fops = &lsf_factory_operations,
};

/* Future builtin entry; deliberately no initcall/Kconfig/Makefile today.
 * Even manually invoking this function cannot register an incomplete backend. */
int lsf_factory_register(void)
{
    if (!lsf_factory_selected_consumer())
        return -EOPNOTSUPP;
    return misc_register(&lsf_factory_device);
}
