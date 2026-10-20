#include <errno.h>
#include <pthread.h>
#include <stddef.h>
#include <stdint.h>

int lsf_c_tls_finish(void);
int *__errno_location(void);
__attribute__((import_module("$root"), import_name("[context-get-1]")))
unsigned context_get(void);
__attribute__((import_module("control"), import_name("pause")))
void pause_control(unsigned key);

static pthread_key_t key;
static _Thread_local unsigned initial_value = 7;
static _Thread_local unsigned destructor_calls;
static _Thread_local unsigned destructor_error;
static _Thread_local unsigned cycle;

__attribute__((export_name("context_anchor")))
unsigned context_anchor(void) { return context_get(); }

static void destructor(void *value) {
    ++destructor_calls;
    if (pthread_getspecific(key) != NULL || lsf_c_tls_finish() != EDEADLK)
        destructor_error = 1;
    if (cycle || destructor_calls == 1)
        if (pthread_setspecific(key, value) != 0) destructor_error = 1;
}

__attribute__((export_name("child")))
unsigned child(unsigned parent_key) {
    if (errno != 0 || initial_value != 7 || pthread_getspecific(parent_key) != NULL) return 1;
    errno = 73;
    if (pthread_setspecific(parent_key, (void *)(uintptr_t)22) != 0) return 2;
    return 0;
}

__attribute__((export_name("isolate")))
unsigned isolate(void) {
    if (errno != 0 || initial_value != 7 || __errno_location() != &errno) return 1;
    errno = 41;
    initial_value = 9;
    if (pthread_key_create(&key, NULL) != 0) return 2;
    if (pthread_setspecific(key, (void *)(uintptr_t)11) != 0) return 3;
    pause_control(key);
    if (errno != 41 || initial_value != 9 || pthread_getspecific(key) != (void *)(uintptr_t)11) return 4;
    /* Both key success and errors preserve errno; deletion runs no destructor. */
    pthread_key_t stale = key;
    if (pthread_key_delete(key) != 0 || pthread_key_delete(key) != EINVAL) return 5;
    if (pthread_getspecific(stale) != NULL || pthread_setspecific(stale, NULL) != EINVAL) return 6;
    if (pthread_key_create(&key, NULL) != 0 || key == stale || pthread_getspecific(key) != NULL) return 7;
    if (errno != 41 || pthread_key_delete(key) != 0) return 8;
    return 0;
}

__attribute__((export_name("keys_limit")))
unsigned keys_limit(void) {
    pthread_key_t keys[128], extra;
    for (unsigned i = 0; i < 128; ++i)
        if (pthread_key_create(&keys[i], NULL) != 0) return 1;
    if (pthread_key_create(&extra, NULL) != EAGAIN) return 2;
    for (unsigned i = 0; i < 128; ++i)
        if (pthread_key_delete(keys[i]) != 0) return 3;
    if (pthread_key_create(NULL, NULL) != EINVAL || pthread_key_delete(0) != EINVAL) return 4;
    return 0;
}

__attribute__((export_name("destructors")))
unsigned destructors(unsigned cyclic) {
    destructor_calls = destructor_error = 0;
    cycle = cyclic;
    if (pthread_key_create(&key, destructor) != 0) return 1;
    if (pthread_setspecific(key, (void *)(uintptr_t)33) != 0) return 2;
    int result = lsf_c_tls_finish();
    if (destructor_error) return 3;
    if (cyclic) {
        if (result != EBUSY || destructor_calls != 4 || pthread_getspecific(key) != (void *)(uintptr_t)33) return 4;
        cycle = 0;
        if (lsf_c_tls_finish() != 0 || destructor_calls != 5) return 5;
    } else if (result != 0 || destructor_calls != 2) return 6;
    if (pthread_getspecific(key) != NULL || pthread_key_delete(key) != 0) return 7;
    return 0;
}

__attribute__((export_name("child_state")))
unsigned child_state(unsigned deleted_key) {
    if (errno != 73 || initial_value != 7 || pthread_getspecific(deleted_key) != NULL) return 1;
    if (lsf_c_tls_finish() != 0 || errno != 73) return 2;
    return 0;
}
