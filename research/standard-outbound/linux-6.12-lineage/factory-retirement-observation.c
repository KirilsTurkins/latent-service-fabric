/* SPDX-License-Identifier: GPL-2.0-only */
/* One outside-bank observation owner, never a native refund certificate.
 * Included after bootstrap helpers and before the original Root collector.
 * All state below uses the ORIGINAL pool_lock. No Root pointer is retained. */
#include <linux/anon_inodes.h>
#include <linux/file.h>
#include <linux/ioctl.h>
#include <linux/poll.h>

#define LSF_RETIREMENT_MINT _IO(0xb7, 1)
#define LSF_RETIREMENT_MAGIC 0x4c534652u
#define LSF_RETIREMENT_VERSION 1u
#define LSF_RETIREMENT_RETURNED_WIRE 1u
enum lsf_retirement_phase {
    LSF_RETIREMENT_UNUSED,
    LSF_RETIREMENT_PREPARING,
    LSF_RETIREMENT_BOUND,
    LSF_RETIREMENT_RETURNED,
    LSF_RETIREMENT_ABANDONED,
    LSF_RETIREMENT_ABANDONED_RETURNED,
    LSF_RETIREMENT_FAILED,
};
struct lsf_retirement_identity {
    struct lsf_prepaid_key owner;
    struct lsf_prepaid_ticket root;
    u64 expires_ns;
};
struct lsf_retirement_actors {
    struct mm_struct *mm;
    struct pid *tgid;
    const struct cred *cred;
    struct net *net;
};
struct lsf_retirement_slot {
    struct lsf_retirement_identity identity;
    struct lsf_retirement_actors actors;
    unsigned int phase;
};
/* By-value scalar identity only. Neither an AckFile nor a Root pointer crosses
 * physical unpublication. Permanent storage permits abandonment at any point. */
struct lsf_retirement_publication {
    struct lsf_retirement_identity identity;
    unsigned int valid;
};
struct lsf_retirement_wire {
    __le32 magic, version, phase, error, owner_slot, root_slot;
    __le64 owner_generation, root_generation, expires_ns;
};
static struct lsf_retirement_slot lsf_retirement;
static DECLARE_WAIT_QUEUE_HEAD(lsf_retirement_wait);
static_assert(LSF_RETIREMENT_MINT == 0xb701);
static_assert(sizeof(struct lsf_retirement_wire) == 48);
static_assert(sizeof(lsf_retirement) + sizeof(lsf_retirement_wait) <= 4096);
static_assert(sizeof(factory) + LSF_BACKING_BYTES + sizeof(lsf_retirement) +
    sizeof(lsf_retirement_wait) < LSF_BOOTSTRAP_CEILING);

static int lsf_retirement_same(struct lsf_retirement_identity a,
    struct lsf_retirement_identity b)
{
    return a.owner.slot == b.owner.slot && a.owner.generation == b.owner.generation &&
        a.root.slot == b.root.slot && a.root.generation == b.root.generation &&
        a.expires_ns == b.expires_ns;
}

static int lsf_retirement_actor_locked(struct file *file)
{
    struct lsf_retirement_actors *actors = &lsf_retirement.actors;
    lockdep_assert_held(&pool_lock);
    return file->private_data == &lsf_retirement &&
        (lsf_retirement.phase == LSF_RETIREMENT_BOUND ||
         lsf_retirement.phase == LSF_RETIREMENT_RETURNED) &&
        actors->mm && actors->tgid && actors->cred && actors->net &&
        current->mm == actors->mm && task_tgid(current) == actors->tgid &&
        current_cred() == actors->cred && file->f_cred == actors->cred &&
        current->nsproxy && current->nsproxy->net_ns == actors->net;
}

static void lsf_retirement_actors_put(struct lsf_retirement_actors actors)
{
    /* Only independently acquired observer references; outside ALL locks.
     * These are never the original Root's four references. */
    if (actors.net)
        put_net(actors.net);
    if (actors.cred)
        put_cred(actors.cred);
    if (actors.tgid)
        put_pid(actors.tgid);
    if (actors.mm)
        mmdrop(actors.mm);
}

static ssize_t lsf_retirement_read(struct file *file, char __user *buffer,
    size_t count, loff_t *position)
{
    struct lsf_retirement_wire wire;
    unsigned long flags;
    int error = -EPERM;
    (void)position;
    if (count != sizeof(wire))
        return -EINVAL;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_retirement_actor_locked(file))
        goto out;
    error = -EAGAIN;
    if (lsf_retirement.phase != LSF_RETIREMENT_RETURNED)
        goto out;
    wire = (struct lsf_retirement_wire){cpu_to_le32(LSF_RETIREMENT_MAGIC),
        cpu_to_le32(LSF_RETIREMENT_VERSION), cpu_to_le32(LSF_RETIREMENT_RETURNED_WIRE), 0,
        cpu_to_le32(lsf_retirement.identity.owner.slot),
        cpu_to_le32(lsf_retirement.identity.root.slot),
        cpu_to_le64(lsf_retirement.identity.owner.generation),
        cpu_to_le64(lsf_retirement.identity.root.generation),
        cpu_to_le64(lsf_retirement.identity.expires_ns)};
    spin_unlock_irqrestore(&pool_lock, flags);
    /* VFS still owns this File/its actor references. Never hold pool_lock
     * across a user fault; copy only the fixed stack-local scalar record. */
    return copy_to_user(buffer, &wire, sizeof(wire)) ? -EFAULT : sizeof(wire);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return error;
}

static __poll_t lsf_retirement_poll(struct file *file, poll_table *wait)
{
    unsigned long flags;
    __poll_t result = EPOLLERR;
    int actor;
    spin_lock_irqsave(&pool_lock, flags);
    actor = lsf_retirement_actor_locked(file);
    spin_unlock_irqrestore(&pool_lock, flags);
    if (!actor)
        return result;
    /* The static wait head outlives every poll entry. Pinned __pollwait owns
     * a File reference; free_poll_entry removes the entry BEFORE its fput. */
    poll_wait(file, &lsf_retirement_wait, wait);
    spin_lock_irqsave(&pool_lock, flags);
    if (lsf_retirement_actor_locked(file))
        result = lsf_retirement.phase == LSF_RETIREMENT_RETURNED ?
            EPOLLIN | EPOLLRDNORM : 0;
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

static int lsf_retirement_release(struct inode *inode, struct file *file)
{
    struct lsf_retirement_actors actors = {0};
    unsigned long flags;
    (void)inode;
    spin_lock_irqsave(&pool_lock, flags);
    if (file->private_data == &lsf_retirement) {
        actors = lsf_retirement.actors;
        lsf_retirement.actors = (struct lsf_retirement_actors){0};
        lsf_retirement.phase = lsf_retirement.phase == LSF_RETIREMENT_RETURNED ?
            LSF_RETIREMENT_ABANDONED_RETURNED : LSF_RETIREMENT_ABANDONED;
        file->private_data = NULL;
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    lsf_retirement_actors_put(actors);
    /* No factory poison, Root guard change, callback, retry, reset or refund. */
    return 0;
}

static const struct file_operations lsf_retirement_operations = {
    .owner = THIS_MODULE,
    .read = lsf_retirement_read,
    .poll = lsf_retirement_poll,
    .release = lsf_retirement_release,
    .llseek = NULL,
};

static long lsf_factory_retirement_ioctl(struct file *file, unsigned int command,
    unsigned long argument)
{
    struct lsf_retirement_actors failed_actors = {0};
    struct file *observation;
    unsigned long flags;
    int result = -EPERM, descriptor;
    /* No host pointer/flags, cost, alternate FD or supplied retirement claim. */
    if (command != LSF_RETIREMENT_MINT || argument)
        return -ENOTTY;
    if (!lsf_factory_constructor_qualification() || lsf_factory_selected_consumer())
        return -EOPNOTSUPP;
    mutex_lock(&factory_lock);
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_factory_actor(file) || factory.opened != 1u || !factory.pages || !factory.device ||
        !factory.mm || !factory.tgid || !factory.cred || !factory.net ||
        factory.device->bootstrap_state != LSF_FACTORY_BOOTSTRAP_READY ||
        factory.device->bootstrap_busy || factory.device->bootstrap_error ||
        !factory.device->bootstrap_expires_ns || READ_ONCE(factory.uncertain) ||
        factory.pool.poisoned || lsf_retirement.phase != LSF_RETIREMENT_UNUSED ||
        factory.device->key.slot != LSF_DEVICE_OWNER_SLOT || factory.device->key.generation != 1u ||
        factory.device->root.slot != 1u || factory.device->root.generation != 2u ||
        !lsf_device_record(&factory.pool, factory.device->key,
            factory.device->root, LSF_DEVICE_ROOT))
        goto unlock_pool;
    lsf_retirement.phase = LSF_RETIREMENT_PREPARING;
    lsf_retirement.identity = (struct lsf_retirement_identity){factory.device->key,
        factory.device->root, factory.device->bootstrap_expires_ns};
    lsf_retirement.actors = (struct lsf_retirement_actors){factory.mm,
        get_pid(factory.tgid), get_cred(factory.cred), get_net(factory.net)};
    mmgrab(lsf_retirement.actors.mm);
    spin_unlock_irqrestore(&pool_lock, flags);
    /* Same caller and original ioctl File reference preserve actor/Root
     * custody. Sleeping VFS/LSM allocation NEVER holds pool_lock. */
    descriptor = get_unused_fd_flags(O_CLOEXEC);
    if (descriptor < 0) {
        result = descriptor;
        goto failed;
    }
    observation = anon_inode_create_getfile("lsf-root-retirement",
        &lsf_retirement_operations, &lsf_retirement, O_RDONLY | O_NONBLOCK,
        file_inode(file));
    if (IS_ERR(observation)) {
        result = PTR_ERR(observation);
        put_unused_fd(descriptor);
        goto failed;
    }
    /* The private File is not yet installed or visible. Publish ALL binding
     * before fd_install; no post-install File/slot/reference access is legal. */
    spin_lock_irqsave(&pool_lock, flags);
    lsf_retirement.phase = LSF_RETIREMENT_BOUND;
    spin_unlock_irqrestore(&pool_lock, flags);
    mutex_unlock(&factory_lock);
    fd_install(descriptor, observation); /* LAST owning File access. */
    return descriptor;
failed:
    spin_lock_irqsave(&pool_lock, flags);
    failed_actors = lsf_retirement.actors;
    lsf_retirement.actors = (struct lsf_retirement_actors){0};
    lsf_retirement.phase = LSF_RETIREMENT_FAILED;
unlock_pool:
    spin_unlock_irqrestore(&pool_lock, flags);
    mutex_unlock(&factory_lock);
    lsf_retirement_actors_put(failed_actors);
    return result;
}

static struct lsf_retirement_publication lsf_retirement_capture_locked(
    struct lsf_cleanup_task_source source, u64 expires_ns)
{
    struct lsf_retirement_identity identity = {source.owner, source.root, expires_ns};
    struct lsf_retirement_publication result = {0};
    lockdep_assert_held(&pool_lock);
    /* Observe only; no Ack state is a Root eligibility/free condition. */
    if ((lsf_retirement.phase == LSF_RETIREMENT_BOUND ||
         lsf_retirement.phase == LSF_RETIREMENT_ABANDONED) &&
        lsf_retirement_same(lsf_retirement.identity, identity))
        result = (struct lsf_retirement_publication){identity, 1u};
    return result;
}

static void lsf_retirement_publish_after_physical(struct lsf_retirement_publication publication)
{
    unsigned long flags;
    int wake = 0;
    if (!publication.valid)
        return;
    spin_lock_irqsave(&pool_lock, flags);
    if (lsf_retirement_same(lsf_retirement.identity, publication.identity)) {
        if (lsf_retirement.phase == LSF_RETIREMENT_BOUND) {
            lsf_retirement.phase = LSF_RETIREMENT_RETURNED;
            wake = 1;
        } else if (lsf_retirement.phase == LSF_RETIREMENT_ABANDONED)
            lsf_retirement.phase = LSF_RETIREMENT_ABANDONED_RETURNED;
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    if (wake)
        wake_up_interruptible_poll(&lsf_retirement_wait, EPOLLIN | EPOLLRDNORM);
}
