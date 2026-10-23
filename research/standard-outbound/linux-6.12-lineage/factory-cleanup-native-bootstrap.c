/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual FD bootstrap protocol. This carries no allocator/free certificate. */
#define LSF_FACTORY_BOOTSTRAP_VERSION 2u
#define LSF_FACTORY_BOOTSTRAP_BEGIN 1u
#define LSF_FACTORY_BOOTSTRAP_WAIT 2u
#define LSF_FACTORY_BOOTSTRAP_CLOSE 3u
#define LSF_FACTORY_BOOTSTRAP_PENDING 1u
#define LSF_FACTORY_BOOTSTRAP_READY 2u
#define LSF_FACTORY_BOOTSTRAP_QUARANTINED 3u
#define LSF_FACTORY_BOOTSTRAP_CLOSED 4u
struct lsf_factory_bootstrap_request {
    __le32 magic, version, operation, reserved;
    __le64 expires_ns;
};
struct lsf_factory_bootstrap_status {
    __le32 magic, version, state, error;
    __le64 expires_ns;
};
/* Read-only observations of the ORIGINAL record array and lifetime fields.
 * These are not a second ledger or final-free/refund certificate. */
struct lsf_factory_bootstrap_diagnostic {
    struct lsf_factory_bootstrap_status status;
    __le64 lifecycle, final_phase, request_users, task_claimed;
    __le64 control_readers, control_retiring, live_records, queued_records;
    __le64 request_returned, flags;
};
static_assert(sizeof(struct lsf_factory_bootstrap_request) == 24);
static_assert(sizeof(struct lsf_factory_bootstrap_status) == 24);
static_assert(sizeof(struct lsf_factory_bootstrap_diagnostic) == 104);

/* Caller holds factory_lock and the original FD reference. The monotonic
 * expiry is fixed BEFORE any private child birth. Floor conversion can only
 * narrow it; every admission also checks the original nanosecond expiry. */
static unsigned long lsf_factory_bootstrap_remaining(u64 expires)
{
    u64 now = ktime_get_ns(), remaining;
    if (expires <= now)
        return 0;
    remaining = nsecs_to_jiffies64(expires - now);
    if (expires - now > 120ULL * NSEC_PER_SEC || !remaining || remaining > MAX_JIFFY_OFFSET)
        return 0;
    return (unsigned long)remaining;
}

static ssize_t lsf_factory_bootstrap_write(struct file *file,
    const char __user *buffer, size_t count)
{
    struct lsf_factory_bootstrap_request request;
    struct lsf_factory_device_state *root;
    unsigned long remaining;
    unsigned int operation;
    u64 expires, now;
    int error, close = 0;
    if (count != sizeof(request) || copy_from_user(&request, buffer, sizeof(request)))
        return -EINVAL;
    operation = le32_to_cpu(request.operation);
    expires = le64_to_cpu(request.expires_ns);
    if (le32_to_cpu(request.magic) != LSF_FACTORY_MAGIC ||
        le32_to_cpu(request.version) != LSF_FACTORY_BOOTSTRAP_VERSION || request.reserved ||
        (operation != LSF_FACTORY_BOOTSTRAP_BEGIN && operation != LSF_FACTORY_BOOTSTRAP_WAIT &&
         operation != LSF_FACTORY_BOOTSTRAP_CLOSE))
        return -EINVAL;
    mutex_lock(&factory_lock);
    error = -EPERM;
    if (!lsf_factory_actor(file) || !factory.device)
        goto out;
    root = factory.device; /* Exact FD and original Root; never caller-supplied. */
    if (root->bootstrap_busy) {
        error = -EBUSY;
        goto out;
    }
    if (operation == LSF_FACTORY_BOOTSTRAP_CLOSE) {
        if (expires != root->bootstrap_expires_ns) {
            error = -EINVAL;
            goto out;
        }
        if (root->bootstrap_state != LSF_FACTORY_BOOTSTRAP_CLOSED) {
            root->bootstrap_state = LSF_FACTORY_BOOTSTRAP_CLOSED;
            lsf_cleanup_admission_close();
            close = 1;
        }
        error = sizeof(request);
        goto out; /* Cleanup is still allowed after the original expiry. */
    }
    if (operation == LSF_FACTORY_BOOTSTRAP_BEGIN) {
        if (root->bootstrap_state || root->bootstrap_expires_ns) {
            error = -EALREADY;
            goto out;
        }
        root->bootstrap_expires_ns = expires; /* Immutable even on refusal. */
        root->bootstrap_state = LSF_FACTORY_BOOTSTRAP_PENDING;
    } else if (root->bootstrap_state != LSF_FACTORY_BOOTSTRAP_PENDING &&
               root->bootstrap_state != LSF_FACTORY_BOOTSTRAP_READY) {
        error = -EOPNOTSUPP;
        goto out;
    }
    now = ktime_get_ns();
    if (operation == LSF_FACTORY_BOOTSTRAP_BEGIN && expires > now &&
        expires - now > 120ULL * NSEC_PER_SEC) {
        error = -EINVAL;
        goto quarantine; /* The original maintenance profile's finite ceiling. */
    }
    if (expires != root->bootstrap_expires_ns) {
        error = -EINVAL; /* No retry can widen the first attempt's expiry. */
        goto out;
    }
    remaining = lsf_factory_bootstrap_remaining(expires);
    if (!remaining || factory.pool.stopped || factory.pool.poisoned || READ_ONCE(factory.uncertain)) {
        error = !remaining ? -ETIMEDOUT : -EIO;
        goto quarantine;
    }
    if (root->bootstrap_state == LSF_FACTORY_BOOTSTRAP_READY) {
        error = sizeof(request);
        goto out;
    }
    /* Publish pending/busy BEFORE releasing this lock. A second caller cannot
     * submit another Task or reset/reuse this bank while the real job runs.
     * file's real syscall reference spans this unlocked complete paid graph. */
    root->bootstrap_busy = 1u;
    mutex_unlock(&factory_lock);
    if (operation == LSF_FACTORY_BOOTSTRAP_BEGIN)
        error = lsf_prepaid_cleanup_provider_create_full(remaining);
    else
        error = lsf_prepaid_cleanup_provider_wait_ready(remaining);
    mutex_lock(&factory_lock);
    if (factory.device != root) {
        WRITE_ONCE(factory.uncertain, 1);
        error = -EIO;
        goto out; /* No unknown Root pointer may be followed or refunded. */
    }
    root->bootstrap_busy = 0;
    if (!lsf_factory_bootstrap_remaining(expires) || factory.pool.stopped ||
        factory.pool.poisoned || READ_ONCE(factory.uncertain)) {
        error = !lsf_factory_bootstrap_remaining(expires) ? -ETIMEDOUT : -EIO;
        goto quarantine;
    }
    if (error == -EINPROGRESS) {
        error = sizeof(request); /* Pending is explicit, never fake READY. */
        goto out;
    }
    if (error)
        goto quarantine;
    root->bootstrap_state = LSF_FACTORY_BOOTSTRAP_READY;
    error = sizeof(request);
    goto out;
quarantine:
    root->bootstrap_state = LSF_FACTORY_BOOTSTRAP_QUARANTINED;
    root->bootstrap_error = -error;
    lsf_cleanup_admission_close();
    close = 1;
out:
    mutex_unlock(&factory_lock);
    if (close)
        lsf_prepaid_cleanup_worker_destroy_full();
    return error;
}

static ssize_t lsf_factory_bootstrap_diagnostic_read(struct file *file,
    char __user *buffer, size_t count)
{
    struct lsf_factory_bootstrap_diagnostic snapshot;
    struct lsf_factory_device_state *root;
    unsigned long flags;
    unsigned int i;
    u64 live = 0, queued = 0;
    int error = -EPERM;
    mutex_lock(&factory_lock);
    if (!lsf_factory_actor(file) || !factory.device)
        goto out;
    spin_lock_irqsave(&pool_lock, flags);
    root = factory.device;
    for (i = 0; i < LSF_ALLOCATION_SLOTS; ++i) {
        if (factory.pool.records[i].phase != LSF_PREPAID_LIVE)
            continue;
        live++;
        queued += factory.pool.records[i].deferred == LSF_PREPAID_QUEUED;
    }
    snapshot = (struct lsf_factory_bootstrap_diagnostic){
        {cpu_to_le32(LSF_FACTORY_MAGIC), cpu_to_le32(LSF_FACTORY_BOOTSTRAP_VERSION),
         cpu_to_le32(root->bootstrap_state), cpu_to_le32(root->bootstrap_error),
         cpu_to_le64(root->bootstrap_expires_ns)},
        cpu_to_le64(root->cleanup_lifecycle), cpu_to_le64(root->cleanup_final_phase),
        cpu_to_le64(root->cleanup_request_users), cpu_to_le64(root->cleanup_task_claimed),
        cpu_to_le64(root->cleanup_provider_control_readers),
        cpu_to_le64(root->cleanup_provider_control_retiring),
        cpu_to_le64(live), cpu_to_le64(queued),
        cpu_to_le64(root->cleanup_request_returned),
        cpu_to_le64((factory.pool.stopped ? 1u : 0u) |
            (factory.pool.poisoned ? 2u : 0u) | (READ_ONCE(factory.uncertain) ? 4u : 0u) |
            (factory.pool.contexts[root->key.slot].poisoned ? 8u : 0u))};
    spin_unlock_irqrestore(&pool_lock, flags);
    error = count == sizeof(snapshot) && !copy_to_user(buffer, &snapshot, sizeof(snapshot)) ?
        sizeof(snapshot) : -EFAULT;
out:
    mutex_unlock(&factory_lock);
    return error;
}

static ssize_t lsf_factory_bootstrap_read(struct file *file,
    char __user *buffer, size_t count)
{
    struct lsf_factory_bootstrap_status status;
    unsigned long flags;
    int error = -EPERM;
    mutex_lock(&factory_lock);
    if (!lsf_factory_actor(file) || !factory.device)
        goto out;
    spin_lock_irqsave(&pool_lock, flags);
    status = (struct lsf_factory_bootstrap_status){
        cpu_to_le32(LSF_FACTORY_MAGIC), cpu_to_le32(LSF_FACTORY_BOOTSTRAP_VERSION),
        cpu_to_le32(factory.device->bootstrap_state),
        cpu_to_le32(factory.device->bootstrap_error),
        cpu_to_le64(factory.device->bootstrap_expires_ns)};
    spin_unlock_irqrestore(&pool_lock, flags);
    error = count == sizeof(status) && !copy_to_user(buffer, &status, sizeof(status)) ?
        sizeof(status) : -EFAULT;
out:
    mutex_unlock(&factory_lock);
    return error;
}

/* The original provider role, request birth and real kthreadd caller precede
 * any request-field read. No name, global bank or supplied function authorizes
 * an ordinary request to take the full private constructor. */
int lsf_factory_cleanup_provider_creator_request(const void *address, unsigned long bytes,
    struct lsf_cleanup_task_source *source)
{
    struct lsf_cleanup_task_source actual;
    unsigned long flags;
    int result = 0;
    if (current != kthreadd_task || !source ||
        !lsf_factory_cleanup_constructor_request(address, bytes, &actual))
        return 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (factory.device && factory.device->cleanup_physical_role == LSF_CLEANUP_PHYSICAL_PROVIDER &&
        factory.device->cleanup_provider_submitted &&
        lsf_cleanup_provider_same_task_source(actual,
            (struct lsf_cleanup_task_source){factory.device->key, factory.device->root,
                factory.device->cleanup_request, factory.device->cleanup_task}) &&
        lsf_cleanup_provider_held_record_locked(actual, actual.request,
            LSF_DEVICE_CLEANUP_REQUEST, actual.root)) {
        *source = actual;
        result = 1;
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Built-in init is inert in committed normal source. The owning VM programme
 * records the exact isolated source projection selecting ONLY constructors. */
static int __init lsf_factory_constructor_qualification_register(void)
{
    if (!lsf_factory_constructor_qualification())
        return 0;
    return lsf_factory_register();
}
late_initcall(lsf_factory_constructor_qualification_register);
