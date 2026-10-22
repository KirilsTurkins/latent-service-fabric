/* Ordinary pthread/C11 calls. The declared observe API supplies actual owner
 * witnesses; no private continuation or thread-runtime intrinsic is called. */
#include <time.h>
#include <unistd.h>

static union { pthread_mutex_t pthread; mtx_t c11; } timed_gate;
static union { pthread_cond_t pthread; cnd_t c11; } timed_condition;
static unsigned timed_c11, timed_kind, timed_children_count;
#define timed_sibling fixture_counter_read(2)
#define timed_completed fixture_counter_read(3)
static latent_runtime_activation_observation_t timed_snapshot;

static struct timespec timed_deadline(clockid_t clock, long millis) {
    struct timespec value; require(clock_gettime(clock, &value) == 0);
    value.tv_nsec += millis * 1000000L;
    value.tv_sec += value.tv_nsec / 1000000000L;
    value.tv_nsec %= 1000000000L; return value;
}
static int timed_compare(struct timespec a, struct timespec b) {
    return a.tv_sec > b.tv_sec || (a.tv_sec == b.tv_sec && a.tv_nsec >= b.tv_nsec);
}
static void timed_lock(void) {
    if (timed_c11) require(mtx_lock(&timed_gate.c11) == thrd_success);
    else require(pthread_mutex_lock(&timed_gate.pthread) == 0);
}
static void timed_unlock(void) {
    if (timed_c11) require(mtx_unlock(&timed_gate.c11) == thrd_success);
    else require(pthread_mutex_unlock(&timed_gate.pthread) == 0);
}
static void timed_pause(long millis) {
    struct timespec value = {millis / 1000, (millis % 1000) * 1000000L};
    struct timespec remaining = {91, 92};
    if (timed_c11) require(thrd_sleep(&value, &remaining) == 0);
    else require(nanosleep(&value, &remaining) == 0);
    require(remaining.tv_sec == 0 && remaining.tv_nsec == 0);
}
static void timed_observe(void) {
    latent_runtime_activation_error_t error = 255;
    for (unsigned attempt = 0; attempt < 32; ++attempt) {
        require(latent_runtime_activation_observe(&timed_snapshot, &error));
        require(timed_snapshot.tasks == timed_children_count + 1 && timed_snapshot.results == timed_children_count);
        require(timed_snapshot.native_owners == 2 + 2 * timed_children_count);
        require(timed_snapshot.native_memory_bytes > 0 && timed_snapshot.stale_wakes == 0);
        if (timed_snapshot.timers >= (timed_kind == 5 ? 2u : 1u)
                && timed_snapshot.waits >= timed_children_count
                && timed_snapshot.parked_tasks >= timed_children_count) return;
        /* Admission and clock imports can await before queue publication.
         * An ordinary bounded sleep lets that eligible sibling finish its
         * registration; no scheduling-order assumption fabricates readiness. */
        timed_pause(1);
    }
    __builtin_trap();
}

static void *timed_worker(void *opaque) {
    struct argument *argument = opaque;
    volatile unsigned frame = 0x7194;
    require(local == 7 && (uintptr_t)&frame != root_stack_address);
    require(pthread_equal(pthread_self(), argument->identity));
    require(!pthread_equal(pthread_self(), root_id) && pthread_getspecific(key) == NULL);
    local += argument->slot + 1; errno = argument->api == 1 ? 37 : 41;
    require(pthread_setspecific(key, (void *)(uintptr_t)1) == 0); FIXTURE_ENTER();
    if (timed_kind == 0) { /* Sleep parks one child while its sibling runs. */
        if (argument->slot == 0) { timed_pause(200); require(timed_sibling == 1); }
        else { timed_observe(); fixture_counter_set(2, 1); }
    } else if (timed_kind == 1) { /* Root holds mutex throughout timeout. */
        if (argument->slot == 0) {
            struct timespec deadline = timed_deadline(CLOCK_REALTIME, 200), now;
            if (timed_c11) require(mtx_timedlock(&timed_gate.c11, &deadline) == thrd_timedout);
            else require(pthread_mutex_timedlock(&timed_gate.pthread, &deadline) == ETIMEDOUT);
            require(clock_gettime(CLOCK_REALTIME, &now) == 0 && timed_compare(now, deadline));
            require(timed_sibling == 1); fixture_counter_add(3);
        } else { timed_observe(); fixture_counter_set(2, 1); }
    } else if (timed_kind == 2) { /* Mutex handoff closes the waiter's Timer. */
        if (argument->slot == 0) {
            timed_lock(); timed_pause(200); timed_observe();
            fixture_counter_set(2, 1); timed_unlock();
        } else {
            struct timespec deadline = timed_deadline(CLOCK_REALTIME, 1000);
            if (timed_c11) require(mtx_timedlock(&timed_gate.c11, &deadline) == thrd_success);
            else require(pthread_mutex_timedlock(&timed_gate.pthread, &deadline) == 0);
            require(timed_sibling == 1); fixture_counter_add(3); timed_unlock();
        }
    } else if (timed_kind == 5) { /* Two timed consumers and a broadcaster. */
        if (argument->slot < 2) {
            timed_lock(); struct timespec deadline = timed_deadline(CLOCK_REALTIME, 1000);
            if (timed_c11) require(cnd_timedwait(&timed_condition.c11, &timed_gate.c11, &deadline) == thrd_success);
            else require(pthread_cond_timedwait(&timed_condition.pthread, &timed_gate.pthread, &deadline) == 0);
            require(timed_sibling == 1); fixture_counter_add(3); timed_unlock();
        } else {
            timed_observe(); timed_lock();
            if (timed_c11) require(cnd_broadcast(&timed_condition.c11) == thrd_success);
            else require(pthread_cond_broadcast(&timed_condition.pthread) == 0);
            timed_pause(200); require(timed_completed == 0);
            fixture_counter_set(2, 1); timed_unlock();
        }
    } else { /* Condition notification/expiry must reacquire the SAME mutex. */
        if (argument->slot == 0) {
            timed_lock();
            struct timespec deadline = timed_deadline(CLOCK_REALTIME, timed_kind == 3 ? 1000 : 200);
            int code = timed_c11 ? cnd_timedwait(&timed_condition.c11, &timed_gate.c11, &deadline)
                : pthread_cond_timedwait(&timed_condition.pthread, &timed_gate.pthread, &deadline);
            require(code == (timed_kind == 3 ? (timed_c11 ? thrd_success : 0)
                : (timed_c11 ? thrd_timedout : ETIMEDOUT)));
            require(timed_sibling == 1); fixture_counter_add(3);
            /* Only the owner can unlock; returning unlocked must fail here. */
            timed_unlock();
        } else {
            timed_observe(); timed_lock();
            if (timed_kind == 3) {
                if (timed_c11) require(cnd_signal(&timed_condition.c11) == thrd_success);
                else require(pthread_cond_signal(&timed_condition.pthread) == 0);
            }
            /* Keep the mutex through signal and timeout. The consumer must
             * remain blocked until actual reacquisition becomes possible. */
            timed_pause(timed_kind == 3 ? 200 : 400);
            require(timed_completed == 0); fixture_counter_set(2, 1); timed_unlock();
        }
    }
    require(frame == 0x7194 && local == 8 + argument->slot);
    require(errno == (argument->api == 1 ? 37 : 41));
    return (void *)(uintptr_t)(local + (unsigned)errno);
}
static int timed_c11_worker(void *opaque) { return (int)(uintptr_t)timed_worker(opaque); }

static unsigned timed_validation(void) {
    struct timespec zero = {0}, bad = {0, 1000000000L}, remaining = {91, 92};
    latent_runtime_activation_observation_t before, after;
    latent_runtime_activation_error_t error = 255;
    /* Keep the declared bounded entropy import in the real linked component.
     * Exact public import/surface validation must not accept a dead declaration. */
    unsigned char entropy[8];
    if (!(getentropy(entropy, sizeof(entropy)) == 0 && errno == 23)) return 1;
    if (!(latent_runtime_activation_observe(&before, &error))) return 2;
    if (!(nanosleep(&zero, &remaining) == 0 && errno == 23)) return 3;
    if (!(remaining.tv_sec == 0 && remaining.tv_nsec == 0)) return 4;
    remaining = (struct timespec){91, 92};
    if (!(nanosleep(&bad, &remaining) == -1 && errno == EINVAL)) return 5;
    if (!(remaining.tv_sec == 91 && remaining.tv_nsec == 92)) return 6; errno = 23;
    if (!(thrd_sleep(&bad, &remaining) == -2 && errno == 23)) return 7;
    if (!(remaining.tv_sec == 91 && remaining.tv_nsec == 92)) return 8;
    if (!(thrd_sleep(&zero, &remaining) == 0 && errno == 23)) return 9;
    if (!(remaining.tv_sec == 0 && remaining.tv_nsec == 0)) return 10;
    if (!(latent_runtime_activation_observe(&after, &error))) return 11;
    if (!(before.tasks == after.tasks && before.waits == after.waits && before.timers == after.timers)) return 12;
    if (!(before.results == after.results && before.native_owners == after.native_owners)) return 13;
    if (!(before.native_memory_bytes == after.native_memory_bytes && before.admission_failures == after.admission_failures)) return 14;
    return 0;
}

static bool timed_children(probe_string_t *input, probe_string_t *result, probe_string_t *error) {
    timed_c11 = mode(input, "timed-sleep-c11") || mode(input, "timed-mutex-timeout-c11")
        || mode(input, "timed-mutex-notify-c11") || mode(input, "timed-condition-notify-c11")
        || mode(input, "timed-condition-timeout-c11") || mode(input, "timed-condition-broadcast-c11");
    timed_kind = mode(input, "timed-sleep") || mode(input, "timed-sleep-c11") ? 0
        : mode(input, "timed-mutex-timeout") || mode(input, "timed-mutex-timeout-c11") ? 1
        : mode(input, "timed-mutex-notify") || mode(input, "timed-mutex-notify-c11") ? 2
        : mode(input, "timed-condition-notify") || mode(input, "timed-condition-notify-c11") ? 3
        : mode(input, "timed-condition-broadcast") || mode(input, "timed-condition-broadcast-c11") ? 5 : 4;
    timed_children_count = timed_kind == 5 ? 3 : 2;
    unsigned failure = timed_validation();
    if (failure) {
        char output[96], *cursor = output;
        memcpy(cursor, "timed-validation:", 17); cursor += 17;
        number(&cursor, failure); *cursor++ = ':'; number(&cursor, (unsigned)errno); *cursor = 0;
        probe_string_dup(error, output); probe_string_free(input); return false;
    }
    if (timed_c11) {
        require(mtx_init(&timed_gate.c11, mtx_timed) == thrd_success);
        require(cnd_init(&timed_condition.c11) == thrd_success);
    } else {
        require(pthread_mutex_init(&timed_gate.pthread, NULL) == 0);
        require(pthread_cond_init(&timed_condition.pthread, NULL) == 0);
    }
    if (timed_kind == 1) timed_lock();
    for (unsigned slot = 0; slot < timed_children_count; ++slot) {
        struct argument *argument = &arguments[slot]; argument->slot = slot;
        argument->api = timed_c11 ? 2 : 1;
        if (timed_c11) {
            thrd_t child; require(thrd_create(&child, timed_c11_worker, argument) == thrd_success);
            argument->identity = (pthread_t)child;
        } else require(pthread_create(&argument->identity, NULL, timed_worker, argument) == 0);
        require(entered == 0 && errno == 23);
    }
    /* Handoff mode must join the waiter, leaving the holder independently
     * eligible. All other modes first join the actual timed consumer. */
    unsigned first = timed_kind == 2 ? 1 : 0;
    if (timed_c11) { join_c11(first); join_c11(1 - first); }
    else { join_pthread(first); join_pthread(1 - first); }
    if (timed_children_count == 3) {
        if (timed_c11) join_c11(2); else join_pthread(2);
    }
    if (timed_kind == 1) timed_unlock();
    require(entered == timed_children_count && destructed == timed_children_count && timed_sibling == 1);
    require(timed_completed == (timed_kind == 0 ? 0u : timed_kind == 5 ? 2u : 1u));
    if (timed_c11) { mtx_destroy(&timed_gate.c11); cnd_destroy(&timed_condition.c11); }
    else {
        require(pthread_mutex_destroy(&timed_gate.pthread) == 0);
        require(pthread_cond_destroy(&timed_condition.pthread) == 0);
    }
    require(local == 70 && errno == 23 && pthread_getspecific(key) == (void *)(uintptr_t)77);
    require(pthread_setspecific(key, NULL) == 0 && pthread_key_delete(key) == 0);
    char output[160], *cursor = output;
    memcpy(cursor, "timed:", 6); cursor += 6;
    memcpy(cursor, input->ptr, input->len); cursor += input->len; *cursor++ = ':';
    number(&cursor, timed_snapshot.timers); *cursor++ = ':';
    number(&cursor, timed_snapshot.waits); *cursor++ = ':';
    number(&cursor, timed_snapshot.parked_tasks); *cursor++ = ':';
    number(&cursor, timed_snapshot.native_memory_bytes); *cursor = 0;
    probe_string_dup(result, output); probe_string_free(input); return true;
}
