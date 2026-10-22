/* Ordinary source. The selected maintained compiler owns the thread PAL. */
#if LSF_C_TIMED_CLOCK
#define _POSIX_C_SOURCE 200809L
#include <stdatomic.h>
#endif
#include "probe.h"
#include <errno.h>
#include <pthread.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <threads.h>

static _Thread_local unsigned local = 7;
static pthread_key_t key;
static pthread_t root_id;
static uintptr_t root_stack_address;
#if LSF_C_TIMED_CLOCK
static _Atomic unsigned entered, destructed;
static volatile unsigned hold, callback_trap;
#else
static volatile unsigned entered, destructed, hold, callback_trap;
#endif
static volatile uint32_t spin;
static latent_runtime_activation_observation_t snapshots[3];

struct argument { pthread_t identity; unsigned slot, api; uint8_t *drain_result; };
static struct argument arguments[3];

static void require(int predicate) { if (!predicate) __builtin_trap(); }
static void destructor(void *value) {
    require(value == (void *)(uintptr_t)1 && local >= 8);
    require(!pthread_equal(pthread_self(), root_id));
    require(errno == 37 || errno == 41);
    ++destructed;
}

static void *worker(void *opaque) {
    struct argument *argument = opaque;
    volatile unsigned frame = 0x1744;
    require(local == 7 && (uintptr_t)&frame != root_stack_address);
    require(pthread_equal(pthread_self(), argument->identity));
    require(!pthread_equal(pthread_self(), root_id));
    require(pthread_getspecific(key) == NULL);
    local += argument->slot + 1;
    errno = argument->api == 1 ? 37 : 41;
    require(pthread_setspecific(key, (void *)(uintptr_t)1) == 0);
    require(pthread_join(pthread_self(), NULL) == EDEADLK);
    require(thrd_join(thrd_current(), NULL) == thrd_error);
    ++entered;
    latent_runtime_activation_error_t error = 255;
    require(latent_runtime_activation_observe(&snapshots[argument->slot], &error));
    const latent_runtime_activation_observation_t *observed = &snapshots[argument->slot];
    /* This runs in the child while the actual parent join owns a Wait and
       parks its Task. It is not a timer/wait-for Poll::Pending observation. */
    require(observed->waits == 1 && observed->parked_tasks == 1);
    require(observed->tasks >= 2 && observed->tasks <= 4);
    require(observed->results >= 1 && observed->results <= 3);
    require(observed->native_owners >= 4 && observed->native_owners <= 8);
    require(observed->native_memory_bytes > 0 && observed->stale_wakes == 0);
    require(frame == 0x1744 && local == 8 + argument->slot);
    if (callback_trap) __builtin_trap();
    while (hold) spin = spin * 1664525u + 1013904223u;
    if (argument->drain_result != NULL) argument->drain_result[6] = '1';
    return (void *)(uintptr_t)(local + (unsigned)errno);
}

static int c11_worker(void *argument) { return (int)(uintptr_t)worker(argument); }

static void create_pthread(unsigned slot) {
    arguments[slot].slot = slot;
    arguments[slot].api = 1;
    require(pthread_create(&arguments[slot].identity, NULL, worker, &arguments[slot]) == 0);
    require(errno == 23 && entered == 0);
    require(!pthread_equal(arguments[slot].identity, root_id));
}

static void create_c11(unsigned slot) {
    thrd_t child;
    arguments[slot].slot = slot;
    arguments[slot].api = 2;
    require(thrd_create(&child, c11_worker, &arguments[slot]) == thrd_success);
    arguments[slot].identity = (pthread_t)child;
    require(errno == 23 && entered == 0);
    require(!thrd_equal(child, thrd_current()));
}

static void join_pthread(unsigned slot) {
    void *result = NULL;
    require(pthread_join(arguments[slot].identity, &result) == 0);
    require((uintptr_t)result == 45 + slot && errno == 23 && local == 70);
}

static void join_c11(unsigned slot) {
    int result = 0;
    require(thrd_join((thrd_t)arguments[slot].identity, &result) == thrd_success);
    require(result == (int)(49 + slot) && errno == 23 && local == 70);
}

static int mode(probe_string_t *input, const char *text) {
    size_t size = strlen(text);
    return input->len == size && memcmp(input->ptr, text, size) == 0;
}

static void number(char **output, uint64_t value) {
    char digits[20]; unsigned count = 0;
    do { digits[count++] = (char)('0' + value % 10); value /= 10; } while (value);
    while (count) *(*output)++ = digits[--count];
}

static void observed_result(probe_string_t *result, unsigned children) {
    char output[160], *cursor = output;
    const latent_runtime_activation_observation_t *row = &snapshots[0];
    memcpy(cursor, "joined:", 7); cursor += 7;
    number(&cursor, children); *cursor++ = ':';
    number(&cursor, entered); *cursor++ = ':';
    number(&cursor, destructed); *cursor++ = ':';
    number(&cursor, row->waits); *cursor++ = ':';
    number(&cursor, row->parked_tasks); *cursor++ = ':';
    number(&cursor, row->tasks); *cursor++ = ':';
    number(&cursor, row->results); *cursor++ = ':';
    number(&cursor, row->native_owners); *cursor++ = ':';
    number(&cursor, row->native_memory_bytes); *cursor = 0;
    probe_string_dup(result, output);
}

#include "synchronization.h"
#if LSF_C_TIMED_CLOCK
#include "timing.h"
#endif

bool exports_examples_c_thread_runtime_api_greet(probe_string_t *input,
                                                probe_string_t *result, probe_string_t *error) {
    volatile unsigned root_frame = 0x744;
    require(local == 7 && entered == 0 && destructed == 0);
    root_id = pthread_self(); root_stack_address = (uintptr_t)&root_frame;
    require(pthread_equal(root_id, pthread_self()) && thrd_equal(thrd_current(), thrd_current()));
    require(pthread_key_create(&key, destructor) == 0);
    require(pthread_setspecific(key, (void *)(uintptr_t)77) == 0);
    local = 70; errno = 23;
#if LSF_C_TIMED_CLOCK
    if (input->len >= 6 && memcmp(input->ptr, "timed-", 6) == 0) {
        timed_children(input, result); require(root_frame == 0x744); return true;
    }
#endif
    unsigned children = 1;
    if (mode(input, "sync-pthread") || mode(input, "sync-mixed")) {
        children = 2;
        synchronized_children(mode(input, "sync-mixed"));
    } else if (mode(input, "pthread") || mode(input, "cancel") || mode(input, "deadline")
            || mode(input, "callback-trap") || mode(input, "root-trap") || mode(input, "invalid")) {
        hold = mode(input, "cancel") || mode(input, "deadline");
        callback_trap = mode(input, "callback-trap");
        if (mode(input, "invalid")) {
            pthread_attr_t attribute = {0}; pthread_t untouched = root_id;
            require(pthread_create(&untouched, &attribute, worker, &arguments[0]) == ENOTSUP);
            require(untouched == root_id && errno == 23);
            require(pthread_create(NULL, NULL, worker, NULL) == EINVAL);
            require(pthread_create(&untouched, NULL, NULL, NULL) == EINVAL);
            require(pthread_join((pthread_t)(uintptr_t)1, NULL) == ESRCH);
            require(pthread_join(root_id, NULL) == EDEADLK && errno == 23);
            require(thrd_create(NULL, c11_worker, NULL) == thrd_error);
        }
        create_pthread(0);
        if (mode(input, "root-trap")) __builtin_trap();
        if (mode(input, "invalid")) require(thrd_join((thrd_t)arguments[0].identity, NULL) == thrd_error);
        join_pthread(0);
        if (mode(input, "invalid")) require(pthread_join(arguments[0].identity, NULL) == EINVAL && errno == 23);
    } else if (mode(input, "c11")) {
        create_c11(0);
        require(pthread_join(arguments[0].identity, NULL) == EINVAL && errno == 23);
        join_c11(0);
        require(thrd_join((thrd_t)arguments[0].identity, NULL) == thrd_error);
    } else if (mode(input, "mixed")) {
        children = 2; create_pthread(0); create_c11(1);
        join_pthread(0); join_c11(1);
    } else if (mode(input, "pressure")) {
        children = 3; create_pthread(0); create_pthread(1); create_pthread(2);
        pthread_t untouched = root_id;
        require(pthread_create(&untouched, NULL, worker, &arguments[0]) == EAGAIN);
        require(untouched == root_id && entered == 0 && errno == 23);
        for (unsigned slot = 0; slot < children; ++slot) join_pthread(slot);
        require(snapshots[0].admission_failures > 0);
    } else if (mode(input, "root-return")) {
        probe_string_dup(result, "drain-0");
        arguments[0].drain_result = result->ptr;
        create_pthread(0);
        require(pthread_setspecific(key, NULL) == 0);
        probe_string_free(input);
        /* Callback arguments and the output are in original Store-owned global
           and heap storage. No pointer to the exited C frame escapes. */
        return true;
    } else {
        require(pthread_setspecific(key, NULL) == 0 && pthread_key_delete(key) == 0);
        probe_string_dup(error, mode(input, "application-error") ? "application-error" : "unknown-mode");
        probe_string_free(input); return false;
    }
    require(root_frame == 0x744 && local == 70 && errno == 23);
    require(entered == children && destructed == children);
    require(pthread_getspecific(key) == (void *)(uintptr_t)77);
    require(pthread_setspecific(key, NULL) == 0 && pthread_key_delete(key) == 0);
    observed_result(result, children); probe_string_free(input); return true;
}
