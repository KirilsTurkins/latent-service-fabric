#include <errno.h>
#include <pthread.h>
#include <stdint.h>
#include <threads.h>

int lsf_c_tls_finish(void);
__attribute__((import_module("$root"), import_name("[context-get-1]")))
unsigned context_get(void);
__attribute__((import_module("control"), import_name("pause")))
void pause_control(unsigned key);

static tss_t key;
static _Thread_local unsigned calls;
static _Thread_local unsigned failures;
static _Thread_local unsigned cyclic;

__attribute__((export_name("context_anchor")))
unsigned context_anchor(void) { return context_get(); }

static void destructor(void *value) {
    ++calls;
    if (tss_get(key) != NULL || lsf_c_tls_finish() != EDEADLK) failures = 1;
    if ((cyclic || calls == 1) && tss_set(key, value) != thrd_success) failures = 1;
}

__attribute__((export_name("child")))
unsigned child(unsigned parent_key) {
    if (errno != 0 || tss_get(parent_key) != NULL) return 1;
    errno = 73;
    return tss_set(parent_key, (void *)(uintptr_t)22) == thrd_success ? 0 : 2;
}

__attribute__((export_name("isolate")))
unsigned isolate(void) {
    if (errno != 0 || tss_create(&key, destructor) != thrd_success) return 1;
    errno = 41;
    if (tss_set(key, (void *)(uintptr_t)11) != thrd_success) return 2;
    pause_control(key);
    if (errno != 41 || tss_get(key) != (void *)(uintptr_t)11) return 3;
    tss_t stale = key;
    tss_delete(key);
    if (calls != 0 || tss_get(stale) != NULL || tss_set(stale, NULL) != thrd_error) return 4;
    if (tss_create(&key, NULL) != thrd_success || key == stale || tss_get(key) != NULL) return 5;
    if (tss_set(key, NULL) != thrd_success || errno != 41) return 6;
    tss_delete(key);
    return 0;
}

__attribute__((export_name("keys_limit")))
unsigned keys_limit(void) {
    tss_t keys[127], extra;
    pthread_key_t pthread_key;
    if (pthread_key_create(&pthread_key, NULL) != 0) return 1;
    for (unsigned i = 0; i < 127; ++i)
        if (tss_create(&keys[i], NULL) != thrd_success) return 2;
    if (tss_create(&extra, NULL) != thrd_error || errno != 41) return 3;
    if (pthread_key_delete(pthread_key) != 0) return 4;
    for (unsigned i = 0; i < 127; ++i) tss_delete(keys[i]);
    if (tss_create(&extra, NULL) != thrd_success) return 5;
    tss_delete(extra);
    return tss_create(NULL, NULL) == thrd_error && errno == 41 ? 0 : 6;
}

__attribute__((export_name("destructors")))
unsigned destructors(unsigned cycle) {
    calls = failures = 0;
    cyclic = cycle;
    if (tss_create(&key, destructor) != thrd_success) return 1;
    if (tss_set(key, (void *)(uintptr_t)33) != thrd_success) return 2;
    int result = lsf_c_tls_finish();
    if (failures) return 3;
    if (cycle) {
        if (result != EBUSY || calls != TSS_DTOR_ITERATIONS || tss_get(key) != (void *)(uintptr_t)33) return 4;
        cyclic = 0;
        if (lsf_c_tls_finish() != 0 || calls != TSS_DTOR_ITERATIONS + 1) return 5;
    } else if (result != 0 || calls != 2) return 6;
    if (tss_get(key) != NULL) return 7;
    tss_delete(key);
    return 0;
}

__attribute__((export_name("child_state")))
unsigned child_state(unsigned deleted_key) {
    if (errno != 73 || tss_get(deleted_key) != NULL) return 1;
    return lsf_c_tls_finish() == 0 && errno == 73 ? 0 : 2;
}
