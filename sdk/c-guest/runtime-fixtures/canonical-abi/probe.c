/* Ordinary source: the maintained generator owns every canonical ABI wrapper. */
#include "probe.h"
#include <errno.h>
#include <pthread.h>
#include <stdint.h>
#include <string.h>
#include <threads.h>

static _Thread_local unsigned local = 7;
static void require(int predicate) { if (!predicate) __builtin_trap(); }
static void *pthread_worker(void *argument) {
    require(local == 7);
    local += (unsigned)(uintptr_t)argument;
    errno = 37;
    return (void *)(uintptr_t)(local + (unsigned)errno);
}
static int c11_worker(void *argument) {
    require(local == 7);
    local += (unsigned)(uintptr_t)argument;
    errno = 41;
    return (int)local + errno;
}

bool exports_examples_threading_api_greet(probe_string_t *name,
                                         probe_string_t *ret, probe_string_t *err) {
    require(local == 7);
    errno = 23;
    if (name->len == 7 && memcmp(name->ptr, "pthread", 7) == 0) {
        pthread_t child;
        void *result = NULL;
        require(pthread_create(&child, NULL, pthread_worker, (void *)(uintptr_t)5) == 0);
        require(!pthread_equal(child, pthread_self()));
        require(pthread_join(child, &result) == 0 && (uintptr_t)result == 49);
    } else if (name->len == 3 && memcmp(name->ptr, "c11", 3) == 0) {
        thrd_t child;
        int result = 0;
        require(thrd_create(&child, c11_worker, (void *)(uintptr_t)9) == thrd_success);
        require(!thrd_equal(child, thrd_current()));
        require(thrd_join(child, &result) == thrd_success && result == 57);
    } else {
        probe_string_dup(err, "unknown-thread-kind");
        probe_string_free(name);
        return false;
    }
    require(local == 7 && errno == 23);
    probe_string_dup(ret, "thread-ok");
    probe_string_free(name);
    return true;
}
