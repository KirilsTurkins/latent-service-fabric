/* Ordinary public pthread/C11 source. The bounded yields coordinate this
 * qualification fixture; they do not claim automatic CPU-loop fairness. */
#include "probe.h"
#include <pthread.h>
#include <stdint.h>
#include <string.h>
#include <threads.h>

_Static_assert(_Generic((pthread_once_t *)0, once_flag *: 1, default: 0), "pinned once ABI");
static pthread_once_t control = PTHREAD_ONCE_INIT;
static pthread_mutex_t gate = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t condition = PTHREAD_COND_INITIALIZER;
static unsigned initialized, ready, waiter_entering, release_init, published, completed, witnessed;
static latent_runtime_activation_observation_t witness;

static void require(int value) { if (!value) __builtin_trap(); }
static void lock_gate(void) { require(pthread_mutex_lock(&gate) == 0); }
static void unlock_gate(void) { require(pthread_mutex_unlock(&gate) == 0); }

static void initialize(void) {
    lock_gate();
    ++initialized;
    ready = 1;
    require(pthread_cond_broadcast(&condition) == 0);
    while (!release_init) require(pthread_cond_wait(&condition, &gate) == 0);
    published = 42;
    unlock_gate();
}

static void *initializer(void *unused) {
    (void)unused;
    require(pthread_once(&control, initialize) == 0);
    lock_gate();
    require(published == 42);
    ++completed;
    unlock_gate();
    return NULL;
}

static int contender(void *unused) {
    (void)unused;
    lock_gate();
    while (!ready) require(pthread_cond_wait(&condition, &gate) == 0);
    waiter_entering = 1;
    unlock_gate();
    call_once((once_flag *)&control, initialize);
    lock_gate();
    require(published == 42);
    ++completed;
    unlock_gate();
    return 0;
}

static void *controller(void *unused) {
    (void)unused;
    for (unsigned attempt = 0; attempt < 128; ++attempt) {
        lock_gate();
        unsigned entering = waiter_entering;
        unlock_gate();
        if (entering) {
            latent_runtime_activation_observation_t row;
            latent_runtime_activation_error_t error = 255;
            require(latent_runtime_activation_observe(&row, &error));
            /* Root join, initializer condition, and the once contender own
             * the three parked Waits. This is not a Poll::Pending witness. */
            if (row.waits == 3 && row.parked_tasks == 3 && row.tasks == 4 &&
                row.results == 3 && row.native_owners == 8) {
                require(row.native_memory_bytes > 0 && row.stale_wakes == 0);
                witness = row;
                lock_gate();
                require(!release_init && waiter_entering && initialized == 1 && completed == 0);
                witnessed = 1;
                release_init = 1;
                require(pthread_cond_broadcast(&condition) == 0);
                unlock_gate();
                return NULL;
            }
        }
        thrd_yield();
    }
    __builtin_trap();
}

static void number(char **output, uint64_t value) {
    char digits[20]; unsigned count = 0;
    do { digits[count++] = (char)('0' + value % 10); value /= 10; } while (value);
    while (count) *(*output)++ = digits[--count];
}

bool exports_examples_c_thread_runtime_api_greet(probe_string_t *input,
                                                probe_string_t *result, probe_string_t *error) {
    if (input->len != 4 || memcmp(input->ptr, "once", 4) != 0) {
        probe_string_dup(error, "unknown-mode"); probe_string_free(input); return false;
    }
    pthread_t first, third;
    thrd_t second;
    require(pthread_create(&first, NULL, initializer, NULL) == 0);
    require(thrd_create(&second, contender, NULL) == thrd_success);
    require(pthread_create(&third, NULL, controller, NULL) == 0);
    require(pthread_join(first, NULL) == 0);
    int second_result = -1;
    require(thrd_join(second, &second_result) == thrd_success && second_result == 0);
    require(pthread_join(third, NULL) == 0);
    require(initialized == 1 && published == 42 && completed == 2 && witnessed == 1);
    require(pthread_cond_destroy(&condition) == 0 && pthread_mutex_destroy(&gate) == 0);
    char output[160], *cursor = output;
    memcpy(cursor, "once:1:2:", 9); cursor += 9;
    number(&cursor, witness.waits); *cursor++ = ':';
    number(&cursor, witness.parked_tasks); *cursor++ = ':';
    number(&cursor, witness.tasks); *cursor++ = ':';
    number(&cursor, witness.results); *cursor++ = ':';
    number(&cursor, witness.native_owners); *cursor++ = ':';
    number(&cursor, witness.native_memory_bytes); *cursor = 0;
    probe_string_dup(result, output); probe_string_free(input); return true;
}
