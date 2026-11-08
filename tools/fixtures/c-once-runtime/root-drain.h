#ifndef LSF_C_ROOT_DRAIN_DIAGNOSTIC_H
#define LSF_C_ROOT_DRAIN_DIAGNOSTIC_H
/* Diagnostic ordinary pthread fixture. Host observations are barriers, not
 * a claim of CPU-loop fairness, native final-free or full C qualification. */
#include "probe.h"
#include <pthread.h>
#include <stdint.h>
#include <string.h>
#include <threads.h>

static pthread_mutex_t rd_gate = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t rd_target_condition = PTHREAD_COND_INITIALIZER;
static pthread_cond_t rd_join_condition = PTHREAD_COND_INITIALIZER;
static pthread_cond_t rd_controller_condition = PTHREAD_COND_INITIALIZER;
static pthread_t rd_target;
static unsigned rd_allow_target, rd_allow_join, rd_allow_controller, rd_later_join;
static unsigned rd_ready, rd_target_waiting, rd_join_waiting, rd_join_entering;
static unsigned rd_root_returning, rd_target_finished, rd_controller_waiting;
static unsigned char *rd_witness;
static size_t rd_witness_length;

static void rd_require(int value) { if (!value) __builtin_trap(); }
static void rd_lock_gate(void) { rd_require(pthread_mutex_lock(&rd_gate) == 0); }
static void rd_unlock_gate(void) { rd_require(pthread_mutex_unlock(&rd_gate) == 0); }

/* Each flag is protected by the same ordinary cooperative pthread mutex.
 * Release it before querying host counters, joining, yielding, or returning. */
static unsigned rd_load(const unsigned *flag) {
    rd_lock_gate();
    unsigned value = *flag;
    rd_unlock_gate();
    return value;
}
static void rd_store(unsigned *flag) {
    rd_lock_gate();
    *flag = 1;
    rd_unlock_gate();
}

static int rd_observed(unsigned waits) {
    latent_runtime_activation_observation_t row;
    latent_runtime_activation_error_t error = 255;
    rd_require(latent_runtime_activation_observe(&row, &error));
    rd_require(row.tasks == 4 && row.results == 3 && row.native_owners == 8);
    rd_require(row.native_memory_bytes > 0 && row.stale_wakes == 0);
    return row.waits == waits && row.parked_tasks == waits;
}

static void rd_wait_for_ready(void) {
    for (unsigned attempt = 0; attempt < 256; ++attempt) {
        if (rd_load(&rd_ready)) return;
        thrd_yield();
    }
    __builtin_trap();
}

static void *rd_target_main(void *unused) {
    (void)unused;
    rd_lock_gate();
    rd_target_waiting = 1;
    while (!rd_allow_target) rd_require(pthread_cond_wait(&rd_target_condition, &rd_gate) == 0);
    rd_unlock_gate();
    rd_store(&rd_target_finished);
    return (void *)(uintptr_t)0x1234;
}

static void *rd_joiner_main(void *unused) {
    (void)unused;
    rd_wait_for_ready();
    if (rd_later_join) {
        rd_lock_gate();
        rd_join_waiting = 1;
        while (!rd_allow_join) rd_require(pthread_cond_wait(&rd_join_condition, &rd_gate) == 0);
        rd_unlock_gate();
    }
    rd_store(&rd_join_entering);
    void *value = NULL;
    rd_require(pthread_join(rd_target, &value) == 0);
    rd_require(value == (void *)(uintptr_t)0x1234 && rd_load(&rd_target_finished) == 1);
    rd_witness[rd_witness_length - 1] = '1';
    return NULL;
}

static void *rd_controller_main(void *unused) {
    (void)unused;
    rd_wait_for_ready();
    /* Publish a dedicated, non-join Wait before the root's first snapshot.
     * cond_wait settles this Wait before it returns and before observe below. */
    rd_lock_gate();
    rd_controller_waiting = 1;
    while (!rd_allow_controller) rd_require(pthread_cond_wait(&rd_controller_condition, &rd_gate) == 0);
    rd_require(rd_root_returning);
    rd_unlock_gate();
    for (unsigned attempt = 0; attempt < 256; ++attempt) {
        if (rd_observed(3)) {
            rd_require(rd_load(&rd_target_waiting) && !rd_load(&rd_target_finished));
            rd_require(rd_witness[rd_witness_length - 7] == '3' && rd_witness[rd_witness_length - 1] == '0');
            if (rd_later_join) rd_require(rd_load(&rd_join_waiting) && !rd_load(&rd_join_entering));
            else rd_require(rd_load(&rd_join_entering));
            rd_witness[rd_witness_length - 5] = '3';
            if (rd_later_join) {
                rd_lock_gate();
                rd_allow_join = 1;
                rd_require(pthread_cond_signal(&rd_join_condition) == 0);
                rd_unlock_gate();
                unsigned joined_wait = 0;
                for (unsigned n = 0; n < 256; ++n) {
                    if (rd_load(&rd_join_entering) && rd_observed(3)) { joined_wait = 1; break; }
                    thrd_yield();
                }
                rd_require(joined_wait && !rd_load(&rd_target_finished));
            }
            rd_witness[rd_witness_length - 3] = '3';
            rd_lock_gate();
            rd_allow_target = 1;
            rd_require(pthread_cond_signal(&rd_target_condition) == 0);
            rd_unlock_gate();
            return NULL;
        }
        thrd_yield();
    }
    __builtin_trap();
}

static bool root_drain_greet(probe_string_t *input,
                             probe_string_t *result, probe_string_t *error) {
    if (input->len == 3 && memcmp(input->ptr, "pre", 3) == 0) rd_later_join = 0;
    else if (input->len == 4 && memcmp(input->ptr, "late", 4) == 0) rd_later_join = 1;
    else { probe_string_dup(error, "unknown-mode"); probe_string_free(input); return false; }
    probe_string_dup(result, rd_later_join ? "late:3:0:0:0" : "pre:3:0:0:0");
    rd_require(result->ptr != NULL && result->len >= 7);
    rd_witness = result->ptr;
    rd_witness_length = result->len;

    /* Insert the target last, so the old root's first exclusive join conflicts
     * with the application's join in both selected orderings. */
    pthread_t controller, joiner;
    rd_require(pthread_create(&controller, NULL, rd_controller_main, NULL) == 0);
    rd_require(pthread_create(&joiner, NULL, rd_joiner_main, NULL) == 0);
    rd_require(pthread_create(&rd_target, NULL, rd_target_main, NULL) == 0);
    rd_store(&rd_ready);
    for (unsigned attempt = 0; attempt < 256; ++attempt) {
        if (rd_load(&rd_target_waiting) && rd_load(&rd_controller_waiting) &&
            (rd_later_join ? rd_load(&rd_join_waiting) && !rd_load(&rd_join_entering)
                        : rd_load(&rd_join_entering)) && rd_observed(3)) {
            rd_require(!rd_load(&rd_target_finished) && rd_witness[rd_witness_length - 1] == '0');
            probe_string_free(input);
            /* The three parked children are target, joiner, controller. The
             * root performs no more blocking operation after this signal. */
            rd_lock_gate();
            rd_root_returning = rd_allow_controller = 1;
            rd_require(pthread_cond_signal(&rd_controller_condition) == 0);
            rd_unlock_gate();
            return true;
        }
        thrd_yield();
    }
    __builtin_trap();
}

#endif
