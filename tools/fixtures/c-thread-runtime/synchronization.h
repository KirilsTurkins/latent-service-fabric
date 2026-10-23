/* Ordinary application source for the C synchronization qualification fixture.
 * Uses only public pthread/C11 synchronization and the declared observation
 * interface. No private canonical/thread PAL operation is called here.
 */
static union { pthread_mutex_t pthread; mtx_t c11; } sync_gate, sync_recursive;
static union { pthread_cond_t pthread; cnd_t c11; } sync_started, sync_done;
static unsigned sync_c11, sync_consumer_waiting, sync_finished;

static void sync_gate_lock(void) {
    if (sync_c11) require(mtx_lock(&sync_gate.c11) == thrd_success);
    else require(pthread_mutex_lock(&sync_gate.pthread) == 0);
}
static void sync_gate_unlock(void) {
    if (sync_c11) require(mtx_unlock(&sync_gate.c11) == thrd_success);
    else require(pthread_mutex_unlock(&sync_gate.pthread) == 0);
}
static void sync_wait_started(void) {
    if (sync_c11) require(cnd_wait(&sync_started.c11, &sync_gate.c11) == thrd_success);
    else require(pthread_cond_wait(&sync_started.pthread, &sync_gate.pthread) == 0);
}
static void sync_wait_done(void) {
    if (sync_c11) require(cnd_wait(&sync_done.c11, &sync_gate.c11) == thrd_success);
    else require(pthread_cond_wait(&sync_done.pthread, &sync_gate.pthread) == 0);
}
static void sync_signal_started(void) {
    if (sync_c11) require(cnd_signal(&sync_started.c11) == thrd_success);
    else require(pthread_cond_signal(&sync_started.pthread) == 0);
}
static void sync_broadcast_done(void) {
    if (sync_c11) require(cnd_broadcast(&sync_done.c11) == thrd_success);
    else require(pthread_cond_broadcast(&sync_done.pthread) == 0);
}
static void sync_destructor(void *value) {
    sync_gate_lock(); destructor(value); sync_gate_unlock();
}
static void *sync_worker(void *opaque) {
    struct argument *argument = opaque;
    volatile unsigned frame = 0x5274;
    require(local == 7 && (uintptr_t)&frame != root_stack_address);
    require(pthread_equal(pthread_self(), argument->identity));
    require(!pthread_equal(pthread_self(), root_id) && pthread_getspecific(key) == NULL);
    local += argument->slot + 1; errno = argument->api == 1 ? 37 : 41;
    require(pthread_setspecific(key, (void *)(uintptr_t)1) == 0);
    sync_gate_lock();
    FIXTURE_ENTER();
    if (argument->slot == 0) {
        sync_consumer_waiting = 1; sync_signal_started();
        while (!sync_finished) sync_wait_done();
    } else {
        require(argument->slot == 1);
        while (!sync_consumer_waiting) sync_wait_started();
        /* Root joins the consumer while the consumer waits on the condition.
         * The producer must remain eligible independently of that join target.
         */
        latent_runtime_activation_error_t error = 255;
        require(latent_runtime_activation_observe(&snapshots[0], &error));
        const latent_runtime_activation_observation_t *row = &snapshots[0];
        require(row->waits == 2 && row->parked_tasks == 2 && row->tasks == 3);
        require(row->results == 2 && row->native_owners == 6);
        require(row->native_memory_bytes > 0 && row->stale_wakes == 0);
        /* The recursively locked mutex still belongs to the root. */
        if (sync_c11) require(mtx_unlock(&sync_recursive.c11) == thrd_error);
        else require(pthread_mutex_unlock(&sync_recursive.pthread) == EPERM);
        sync_finished = 1; sync_broadcast_done();
    }
    sync_gate_unlock();
    require(frame == 0x5274 && local == 8 + argument->slot);
    require(errno == (argument->api == 1 ? 37 : 41));
    return (void *)(uintptr_t)(local + (unsigned)errno);
}
static int sync_c11_worker(void *opaque) { return (int)(uintptr_t)sync_worker(opaque); }

static void synchronized_children(int mixed) {
    sync_c11 = mixed; sync_consumer_waiting = sync_finished = 0;
    require(pthread_setspecific(key, NULL) == 0 && pthread_key_delete(key) == 0);
    require(pthread_key_create(&key, sync_destructor) == 0);
    require(pthread_setspecific(key, (void *)(uintptr_t)77) == 0);
    if (mixed) {
        require(mtx_init(&sync_gate.c11, mtx_plain) == thrd_success);
        require(mtx_init(&sync_recursive.c11, mtx_recursive) == thrd_success);
        require(cnd_init(&sync_started.c11) == thrd_success && cnd_init(&sync_done.c11) == thrd_success);
        require(mtx_lock(&sync_recursive.c11) == thrd_success && mtx_lock(&sync_recursive.c11) == thrd_success);
    } else {
        pthread_mutexattr_t attribute;
        require(pthread_mutexattr_init(&attribute) == 0);
        require(pthread_mutexattr_settype(&attribute, PTHREAD_MUTEX_RECURSIVE) == 0);
        require(pthread_mutex_init(&sync_recursive.pthread, &attribute) == 0);
        require(pthread_mutexattr_destroy(&attribute) == 0);
        require(pthread_mutex_init(&sync_gate.pthread, NULL) == 0);
        require(pthread_cond_init(&sync_started.pthread, NULL) == 0 && pthread_cond_init(&sync_done.pthread, NULL) == 0);
        require(pthread_mutex_lock(&sync_recursive.pthread) == 0 && pthread_mutex_lock(&sync_recursive.pthread) == 0);
    }
    for (unsigned slot = 0; slot < 2; ++slot) {
        struct argument *argument = &arguments[slot];
        argument->slot = slot; argument->api = mixed && slot == 1 ? 2 : 1;
        if (argument->api == 1) require(pthread_create(&argument->identity, NULL, sync_worker, argument) == 0);
        else {
            thrd_t child; require(thrd_create(&child, sync_c11_worker, argument) == thrd_success);
            argument->identity = (pthread_t)child;
        }
        require(entered == 0 && errno == 23);
    }
    join_pthread(0);
    if (mixed) join_c11(1); else join_pthread(1);
    require(entered == 2 && destructed == 2 && sync_finished == 1);
    if (mixed) {
        require(mtx_unlock(&sync_recursive.c11) == thrd_success && mtx_unlock(&sync_recursive.c11) == thrd_success);
        mtx_destroy(&sync_recursive.c11); mtx_destroy(&sync_gate.c11);
        cnd_destroy(&sync_started.c11); cnd_destroy(&sync_done.c11);
    } else {
        require(pthread_mutex_unlock(&sync_recursive.pthread) == 0 && pthread_mutex_unlock(&sync_recursive.pthread) == 0);
        require(pthread_mutex_destroy(&sync_recursive.pthread) == 0 && pthread_mutex_destroy(&sync_gate.pthread) == 0);
        require(pthread_cond_destroy(&sync_started.pthread) == 0 && pthread_cond_destroy(&sync_done.pthread) == 0);
    }
    require(errno == 23 && local == 70);
}
