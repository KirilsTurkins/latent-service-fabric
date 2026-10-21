/* Explicit selected compiler-context PAL. Application calls and these definitions
 * share compiler-owned private symbols when linked with the original libc. */
#include <errno.h>
#include <limits.h>
#include <pthread.h>
#include <stddef.h>
#include <threads.h>

#define KEY_COUNT 128u
#define KEY_BITS 7u
#define LAST_GENERATION (UINT_MAX >> KEY_BITS)
#define DESTRUCTOR_PASSES 4u

_Static_assert(sizeof(pthread_key_t) == sizeof(unsigned), "unsupported pthread key ABI");
_Static_assert(KEY_COUNT == (1u << KEY_BITS), "invalid pthread key encoding");
_Static_assert(_Generic((tss_t *)0, pthread_key_t *: 1, default: 0),
    "unsupported C11 thread-specific key ABI");
_Static_assert(TSS_DTOR_ITERATIONS == DESTRUCTOR_PASSES, "unsupported C11 destructor bound");
#ifdef PTHREAD_KEYS_MAX
_Static_assert(KEY_COUNT >= PTHREAD_KEYS_MAX, "header key limit exceeds PAL");
#endif

struct key_definition {
    unsigned generation;
    unsigned active;
    void (*destructor)(void *);
};
struct key_value {
    unsigned generation;
    void *value;
};

/* Per-Store registry. These operations must remain non-suspending critical code. */
static struct key_definition definitions[KEY_COUNT];
static _Thread_local struct key_value values[KEY_COUNT];
static _Thread_local unsigned finishing;
#if defined(LSF_C_LINKED_LIBC)
#if LSF_C_LINKED_LIBC != 1
#error unsupported linked libc selection
#endif
#ifdef __wasilibc_unmodified_upstream
#error unsupported linked libc errno family
#endif
/* The selected WASI libc owns errno and __errno_location. Its original TLS
 * accesses are redirected by the same checked whole-core context derivation. */
#else
_Thread_local int errno;

int *__errno_location(void) { return &errno; }
#endif

static struct key_definition *lookup(pthread_key_t key, unsigned *index) {
    unsigned value = (unsigned)key;
    *index = value & (KEY_COUNT - 1u);
    unsigned generation = value >> KEY_BITS;
    struct key_definition *definition = &definitions[*index];
    return generation != 0u && definition->active && definition->generation == generation
        ? definition : NULL;
}

int pthread_key_create(pthread_key_t *key, void (*destructor)(void *)) {
    if (key == NULL) return EINVAL;
    for (unsigned index = 0; index < KEY_COUNT; ++index) {
        struct key_definition *definition = &definitions[index];
        /* Exhausted generations are permanently retired, never wrapped. */
        if (!definition->active && definition->generation < LAST_GENERATION) {
            ++definition->generation;
            definition->destructor = destructor;
            definition->active = 1u;
            *key = (pthread_key_t)((definition->generation << KEY_BITS) | index);
            return 0;
        }
    }
    return EAGAIN;
}

int pthread_key_delete(pthread_key_t key) {
    unsigned index;
    struct key_definition *definition = lookup(key, &index);
    if (definition == NULL) return EINVAL;
    definition->active = 0u;
    definition->destructor = NULL;
    return 0;
}

void *pthread_getspecific(pthread_key_t key) {
    unsigned index;
    struct key_definition *definition = lookup(key, &index);
    return definition != NULL && values[index].generation == definition->generation
        ? values[index].value : NULL;
}

int pthread_setspecific(pthread_key_t key, const void *value) {
    unsigned index;
    struct key_definition *definition = lookup(key, &index);
    if (definition == NULL) return EINVAL;
    values[index].generation = definition->generation;
    values[index].value = (void *)value;
    return 0;
}

int tss_create(tss_t *key, tss_dtor_t destructor) {
    return pthread_key_create(key, destructor) == 0 ? thrd_success : thrd_error;
}

void tss_delete(tss_t key) { (void)pthread_key_delete(key); }

void *tss_get(tss_t key) { return pthread_getspecific(key); }

int tss_set(tss_t key, void *value) {
    return pthread_setspecific(key, value) == 0 ? thrd_success : thrd_error;
}

/* Internal closing hook, not a public pthread entry point or retirement proof.
 * Four passes are finite. Reinstalled values after the last pass remain live;
 * the caller must retain their owner and fail/quarantine instead of refunding.
 */
int lsf_c_tls_finish(void) {
    if (finishing) return EDEADLK;
    finishing = 1u;
    for (unsigned pass = 0; pass < DESTRUCTOR_PASSES; ++pass) {
        unsigned called = 0u;
        for (unsigned index = 0; index < KEY_COUNT; ++index) {
            struct key_definition *definition = &definitions[index];
            struct key_value *entry = &values[index];
            if (definition->active && entry->generation == definition->generation
                    && entry->value != NULL && definition->destructor != NULL) {
                void *value = entry->value;
                void (*destructor)(void *) = definition->destructor;
                entry->value = NULL;
                called = 1u;
                destructor(value);
            }
        }
        if (!called) break;
    }
    for (unsigned index = 0; index < KEY_COUNT; ++index) {
        struct key_definition *definition = &definitions[index];
        struct key_value *entry = &values[index];
        if (definition->active && entry->generation == definition->generation
                && entry->value != NULL && definition->destructor != NULL) {
            finishing = 0u;
            return EBUSY;
        }
    }
    for (unsigned index = 0; index < KEY_COUNT; ++index) {
        values[index].value = NULL;
        values[index].generation = 0u;
    }
    finishing = 0u;
    return 0;
}
