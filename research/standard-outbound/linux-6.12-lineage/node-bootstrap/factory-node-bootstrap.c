/* SPDX-License-Identifier: GPL-2.0-only */
/* Separate immutable compiled node-bootstrap ABI. Include only in its image,
 * after the unchanged ordinary fops and before the sole miscdevice definition.
 * This file supplies custody only: no IRQ/funding/physical-return approval. */
#ifndef LSF_STREAM_NODE_BOOTSTRAP_IMAGE
#error "node bootstrap requires its separate source-bound image"
#endif

#define LSF_NODE_MAGIC 0x4c534e42u
#define LSF_NODE_VERSION 1u
#define LSF_NODE_ATTACH 1u
#define LSF_NODE_CLOSE_RETAIN 2u
#define LSF_NODE_OPEN_UNATTACHED 1u
#define LSF_NODE_ATTACHED_UNQUALIFIED 2u
#define LSF_NODE_CLOSED_RETAINED 3u
#define LSF_NODE_RETAINED 4u
#define LSF_NODE_PARENT_KIND 0xff00u

struct lsf_node_request {
    __le32 magic, version, operation, reserved;
    __le64 expires_ns, generation;
};
struct lsf_node_reply {
    __le32 magic, version, state, error;
    __le64 expires_ns, generation, native_bytes, alignment, view_bytes, flags;
};
static_assert(sizeof(struct lsf_node_request) == 32);
static_assert(sizeof(struct lsf_node_reply) == 64);

/* Real typed storage, including every retained actor-reference slot, is born
 * inside the one original prepaid order-7 bank. No post-birth device Root or
 * existing OS object is adopted. The header itself uses the SAME record/cursor
 * arrays and cannot be released through an ordinary device-kind callback. */
struct lsf_node_parent {
    struct lsf_prepaid_key owner;
    struct lsf_prepaid_ticket record;
    struct mm_struct *mm;
    struct pid *tgid;
    const struct cred *cred;
    struct net *net;
    u64 expires_ns;
    unsigned int state, reply_pending;
};
static_assert(__alignof__(struct lsf_node_parent) <= 64);
static_assert(sizeof(struct lsf_node_parent) <= LSF_FACTORY_INFRA_BYTES);

/* The returned address is checked BEFORE any field read. This bank is never
 * physically freed by the new route; unknown state retains the original owner. */
static struct lsf_node_parent *lsf_node_parent_for(struct file *file)
{
    struct lsf_node_parent *node;
    struct lsf_prepaid_view *record;
    struct lsf_prepaid_context *owner;
    unsigned long flags;
    unsigned long extent = ALIGN(sizeof(struct lsf_node_parent), 64);
    lockdep_assert_held(&factory_lock);
    if (!factory.pages || !factory.opened || !factory.pool.initialized ||
        factory.device || READ_ONCE(factory.uncertain))
        return NULL;
    node = (void *)((char *)page_address(factory.pages) + LSF_FACTORY_INFRA_OFFSET);
    if (file->private_data != node)
        return NULL;
    spin_lock_irqsave(&pool_lock, flags);
    record = &factory.pool.records[1];
    owner = &factory.pool.contexts[LSF_DEVICE_OWNER_SLOT];
    if (factory.pool.poisoned || record->phase != LSF_PREPAID_LIVE ||
        record->kind != LSF_NODE_PARENT_KIND ||
        record->owner != LSF_DEVICE_OWNER_SLOT || !record->generation ||
        record->owner_generation != owner->generation || !owner->generation || owner->poisoned ||
        record->offset != LSF_FACTORY_INFRA_OFFSET || record->bytes != extent ||
        record->cache_bucket || record->cache_anchor ||
        node->owner.slot != LSF_DEVICE_OWNER_SLOT ||
        node->owner.generation != owner->generation || node->record.slot != 1u ||
        node->record.generation != record->generation)
        node = NULL;
    spin_unlock_irqrestore(&pool_lock, flags);
    return node;
}

static int lsf_node_actor(struct file *file, struct lsf_node_parent *node)
{
    return node && current->nsproxy && node->mm == current->mm &&
        node->tgid == task_tgid(current) && node->cred == current_cred() &&
        file->f_cred == node->cred && node->net == current->nsproxy->net_ns;
}

static int lsf_node_open(struct inode *inode, struct file *file)
{
    struct lsf_prepaid_context *owner;
    struct lsf_prepaid_view *record;
    struct lsf_node_parent *node;
    struct lsf_prepaid_key key;
    unsigned long flags, extent = ALIGN(sizeof(struct lsf_node_parent), 64);
    int error = -EOPNOTSUPP;
    (void)inode;
    /* Same NULL consumer and closed installation gate. A flag/environment or
     * NODE_ATTACH cannot select these fops or authorize an unqualified image.
     * The trusted Rust installed-image permit MUST precede this syscall. */
    if (!lsf_factory_selected_consumer())
        return error;
    /* A real source-level reference keeps the unchanged ordinary table and
     * its static callbacks live in this alternate image under -Werror. This
     * constant predecessor-shape check is not a profile or funding proof. */
    if (lsf_factory_operations.open != lsf_factory_open ||
        lsf_factory_operations.release != lsf_factory_release)
        return -EOPNOTSUPP;
    if (!ns_capable(&init_user_ns, CAP_SYS_ADMIN))
        return -EPERM;
    if (!current->nsproxy || current->nsproxy->net_ns != &init_net)
        return -EOPNOTSUPP;
    /* This checks the existing fixed bootstrap floor only. It is explicitly
     * NOT a complete Node/IRQ peak, free tail or funding-approval predicate. */
    if (!lsf_cleanup_bootstrap_fits() || extent > LSF_FACTORY_INFRA_BYTES)
        return -EOPNOTSUPP;
    mutex_lock(&factory_lock);
    if (factory.opened || factory.pages || factory.device ||
        READ_ONCE(factory.uncertain)) {
        error = -EBUSY;
        goto out;
    }
    /* Preserve the original observer exclusion and uevent writer fences. The
     * new ABI is not permission to omit pre-bank native caller containment. */
    error = lsf_cleanup_observers_prebank_enter();
    if (error)
        goto out;
    error = lsf_factory_device_uevent_bank_enter();
    if (error) {
        if (lsf_cleanup_observers_prebank_rollback())
            WRITE_ONCE(factory.uncertain, 1);
        goto out;
    }
    /* Before this syscall Rust moved the ONE whole original one-MiB escrow
     * into its armed physical job. No old open, second bank, lower-order,
     * kmalloc or size-selected fallback is called. */
    factory.pages = alloc_pages(GFP_KERNEL | __GFP_ZERO | __GFP_NORETRY,
                                 LSF_BACKING_ORDER);
    if (!factory.pages) {
        lsf_factory_device_uevent_bank_allocation_failed();
        if (lsf_cleanup_observers_prebank_rollback())
            WRITE_ONCE(factory.uncertain, 1);
        error = -ENOMEM;
        goto out;
    }
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_prepaid_initialize(&factory.pool) ||
        !lsf_device_context_create(&factory.pool, &key)) {
        WRITE_ONCE(factory.uncertain, 1);
        error = -EIO;
        spin_unlock_irqrestore(&pool_lock, flags);
        goto out;
    }
    owner = &factory.pool.contexts[key.slot];
    record = &factory.pool.records[1];
    if (owner->cursor || owner->live || owner->continuations ||
        record->phase != LSF_PREPAID_EMPTY || !factory.pool.next_generation ||
        factory.pool.next_generation == (u64)-1) {
        WRITE_ONCE(factory.uncertain, 1);
        error = -EIO;
        spin_unlock_irqrestore(&pool_lock, flags);
        goto out;
    }
    /* Reserve the COMPLETE exact typed header before its first write or actor
     * reference. Same fixed record array, monotonic issuer and original cursor.
     * This private role is not recognized by ordinary device/free allocators. */
    *record = (struct lsf_prepaid_view){
        .generation = factory.pool.next_generation++,
        .owner_generation = key.generation, .offset = LSF_FACTORY_INFRA_OFFSET,
        .bytes = extent, .owner = key.slot, .phase = LSF_PREPAID_LIVE,
        .kind = LSF_NODE_PARENT_KIND
    };
    owner->cursor = extent;
    owner->live = 1;
    node = (void *)((char *)page_address(factory.pages) + record->offset);
    memset(node, 0, sizeof(*node));
    node->owner = key;
    node->record = (struct lsf_prepaid_ticket){1u, record->generation};
    spin_unlock_irqrestore(&pool_lock, flags);
    node->mm = current->mm;
    mmgrab(node->mm);
    node->tgid = get_pid(task_tgid(current));
    node->cred = get_current_cred();
    node->net = get_net(current->nsproxy->net_ns);
    node->state = LSF_NODE_OPEN_UNATTACHED;
    factory.opened = 1u;
    file->private_data = node;
    error = 0;
out:
    mutex_unlock(&factory_lock);
    return error;
}

static ssize_t lsf_node_write(struct file *file, const char __user *buffer, size_t count, loff_t *position)
{
    struct lsf_node_request request;
    struct lsf_node_parent *node;
    u64 expires, generation, now;
    unsigned long flags;
    unsigned int operation;
    int error = -EINVAL;
    if (count != sizeof(request) || copy_from_user(&request, buffer, sizeof(request)))
        return -EINVAL;
    if (le32_to_cpu(request.magic) != LSF_NODE_MAGIC ||
        le32_to_cpu(request.version) != LSF_NODE_VERSION || request.reserved)
        return -EINVAL;
    operation = le32_to_cpu(request.operation);
    expires = le64_to_cpu(request.expires_ns);
    generation = le64_to_cpu(request.generation);
    mutex_lock(&factory_lock);
    node = lsf_node_parent_for(file);
    if (!lsf_node_actor(file, node)) {
        error = -EPERM;
        goto out;
    }
    if (node->reply_pending) {
        error = -EBUSY;
        goto out;
    }
    if (operation == LSF_NODE_ATTACH) {
        if (node->state != LSF_NODE_OPEN_UNATTACHED || node->expires_ns ||
            generation || !expires || factory.pool.stopped ||
            factory.pool.contexts[node->owner.slot].closed) {
            error = -EALREADY;
            goto out;
        }
        now = ktime_get_ns();
        if (expires <= now || expires - now > 120ULL * NSEC_PER_SEC) {
            node->state = LSF_NODE_RETAINED;
            error = -ETIMEDOUT;
            goto out;
        }
        node->expires_ns = expires;
        node->state = LSF_NODE_ATTACHED_UNQUALIFIED;
    } else if (operation == LSF_NODE_CLOSE_RETAIN) {
        if ((node->state != LSF_NODE_ATTACHED_UNQUALIFIED &&
             node->state != LSF_NODE_CLOSED_RETAINED) ||
            expires != node->expires_ns || generation != node->record.generation)
            goto out;
        node->state = LSF_NODE_CLOSED_RETAINED;
        spin_lock_irqsave(&pool_lock, flags);
        factory.pool.stopped = 1u;
        factory.pool.contexts[node->owner.slot].closed = 1u;
        spin_unlock_irqrestore(&pool_lock, flags);
    } else {
        goto out; /* Old BEGIN/WAIT/CREATE cannot fall through into this ABI. */
    }
    node->reply_pending = 1u;
    error = sizeof(request);
out:
    mutex_unlock(&factory_lock);
    return error;
}

static ssize_t lsf_node_read(struct file *file, char __user *buffer, size_t count, loff_t *position)
{
    struct lsf_node_reply reply;
    struct lsf_node_parent *node;
    int error = -EPERM;
    mutex_lock(&factory_lock);
    node = lsf_node_parent_for(file);
    if (!lsf_node_actor(file, node))
        goto out;
    if (count != sizeof(reply) || !node->reply_pending) {
        error = -EINVAL;
        goto out;
    }
    reply = (struct lsf_node_reply){
        cpu_to_le32(LSF_NODE_MAGIC), cpu_to_le32(LSF_NODE_VERSION),
        cpu_to_le32(node->state), 0, cpu_to_le64(node->expires_ns),
        cpu_to_le64(node->record.generation),
        cpu_to_le64(sizeof(struct lsf_node_parent)),
        cpu_to_le64(__alignof__(struct lsf_node_parent)),
        cpu_to_le64(ALIGN(sizeof(struct lsf_node_parent), 64)), 0
    };
    if (copy_to_user(buffer, &reply, sizeof(reply))) {
        error = -EFAULT;
        goto out;
    }
    node->reply_pending = 0;
    error = sizeof(reply);
out:
    mutex_unlock(&factory_lock);
    return error;
}

static int lsf_node_release(struct inode *inode, struct file *file)
{
    struct lsf_node_parent *node;
    unsigned long flags;
    (void)inode;
    mutex_lock(&factory_lock);
    node = lsf_node_parent_for(file);
    if (node) {
        node->state = LSF_NODE_RETAINED;
        spin_lock_irqsave(&pool_lock, flags);
        factory.pool.stopped = 1u;
        factory.pool.contexts[node->owner.slot].closed = 1u;
        spin_unlock_irqrestore(&pool_lock, flags);
    } else {
        WRITE_ONCE(factory.uncertain, 1);
    }
    /* No native Node retirement producer exists. Do not put actor references,
     * return the header/record, reset identity/cursor, free the bank or treat
     * the old constructor/bank receipt as permission. Custody stays retained. */
    mutex_unlock(&factory_lock);
    return 0;
}

static const struct file_operations lsf_factory_node_operations = {
    .owner = THIS_MODULE, .open = lsf_node_open,
    .read = lsf_node_read, .write = lsf_node_write,
    .release = lsf_node_release, .llseek = NULL,
};
/* No positive node-growth, NodeFunding or NodeRetired function is defined. */

