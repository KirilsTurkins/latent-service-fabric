/* SPDX-License-Identifier: GPL-2.0-only */
/* Fixed normal-Node observer, SAME original one-slot/actor/precharge owner.
 * Constructor ioctl1/read/magic/fops stay exact. This does not select a
 * consumer, certify physical cost, or turn observation bytes into authority. */
#define LSF_STREAM_RETIREMENT_MINT _IO(0xb7, 2)
#define LSF_STREAM_RETIREMENT_MAGIC 0x4c53464eu
static_assert(LSF_STREAM_RETIREMENT_MINT == 0xb702);

static ssize_t lsf_stream_retirement_read(struct file *file, char __user *buffer,
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
    wire = (struct lsf_retirement_wire){cpu_to_le32(LSF_STREAM_RETIREMENT_MAGIC),
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

static const struct file_operations lsf_stream_retirement_operations = {
    .owner = THIS_MODULE,
    .read = lsf_stream_retirement_read,
    .poll = lsf_retirement_poll,
    .release = lsf_retirement_release,
    .llseek = NULL,
};

static long lsf_factory_stream_retirement_ioctl(struct file *file, unsigned int command,
    unsigned long argument)
{
    struct lsf_retirement_actors failed_actors = {0};
    struct file *observation;
    struct lsf_stream_rx_state *state;
    unsigned long flags;
    int result = -EPERM, descriptor;
    /* No host pointer/flags, cost, alternate FD or supplied retirement claim. */
    if (command != LSF_STREAM_RETIREMENT_MINT || argument)
        return -ENOTTY;
    if (lsf_factory_constructor_qualification() || !lsf_factory_selected_consumer())
        return -EOPNOTSUPP;
    mutex_lock(&factory_lock);
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    if (!state || state->closing || state->stopped ||
        state->geometry.computed != LSF_STREAM_GEOMETRY_ALL ||
        !state->pci || !state->virtio || factory.device->pci_attempted != 1u)
        goto unlock_pool;
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
    observation = anon_inode_create_getfile("lsf-node-root-retirement",
        &lsf_stream_retirement_operations, &lsf_retirement, O_RDONLY | O_NONBLOCK,
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

static long lsf_factory_stream_ioctl(struct file *file, unsigned int command,
    unsigned long argument)
{
    if (command == LSF_STREAM_RETIREMENT_MINT)
        return lsf_factory_stream_retirement_ioctl(file, command, argument);
    return lsf_factory_retirement_ioctl(file, command, argument);
}
