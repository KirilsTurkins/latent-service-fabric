/* SPDX-License-Identifier: Apache-2.0 */
#ifndef LSF_GUEST_OWNERSHIP_H
#define LSF_GUEST_OWNERSHIP_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

/* A scope owns only explicitly adopted objects, never host authority. The
 * scope and callback arguments must outlive every pending canonical subtask.
 * Callbacks must not re-enter the scope. A failed adoption leaves ownership
 * with the caller. No cleanup callback may initiate asynchronous work. */
#define LSF_SCOPE_CAPACITY 32u

typedef void (*lsf_cleanup_fn)(void *);
typedef struct {
    void *object;
    size_t charge;
    lsf_cleanup_fn cleanup;
} lsf_owned_entry_t;

typedef struct {
    size_t limit, live, peak, count;
    lsf_owned_entry_t entries[LSF_SCOPE_CAPACITY];
} lsf_scope_t;

static inline void lsf_require(bool condition) {
    if (!condition) __builtin_trap();
}

static inline void lsf_scope_init(lsf_scope_t *scope, size_t maximum_bytes) {
    *scope = (lsf_scope_t){.limit = maximum_bytes};
}

static inline bool lsf_scope_adopt(lsf_scope_t *scope, void *object,
                                   size_t charge, lsf_cleanup_fn cleanup) {
    if (!scope || !object || !cleanup || scope->count >= LSF_SCOPE_CAPACITY ||
        scope->live > scope->limit || charge > scope->limit - scope->live)
        return false;
    for (size_t i = 0; i < scope->count; ++i)
        if (scope->entries[i].object == object) return false;
    scope->entries[scope->count++] = (lsf_owned_entry_t){object, charge, cleanup};
    scope->live += charge;
    if (scope->live > scope->peak) scope->peak = scope->live;
    return true;
}

/* Detach transfers the owner; it does NOT release the object. Use it exactly
 * once when handing an allocation to a generated export's post-return owner.
 * It does not claim a refund of the host's invocation/resource budget. */
static inline bool lsf_scope_detach(lsf_scope_t *scope, const void *object) {
    if (!scope || !object) return false;
    for (size_t i = 0; i < scope->count; ++i) {
        if (scope->entries[i].object != object) continue;
        scope->live -= scope->entries[i].charge;
        --scope->count;
        memmove(&scope->entries[i], &scope->entries[i + 1],
                (scope->count - i) * sizeof(scope->entries[0]));
        scope->entries[scope->count] = (lsf_owned_entry_t){0};
        return true;
    }
    return false;
}

static inline bool lsf_scope_release(lsf_scope_t *scope, void *object) {
    if (!scope || !object) return false;
    for (size_t i = 0; i < scope->count; ++i) {
        if (scope->entries[i].object != object) continue;
        lsf_cleanup_fn cleanup = scope->entries[i].cleanup;
        lsf_require(lsf_scope_detach(scope, object));
        cleanup(object);
        return true;
    }
    return false;
}

/* Reverse acquisition order; safe to call again after successful cleanup. */
static inline void lsf_scope_close(lsf_scope_t *scope) {
    if (!scope) return;
    while (scope->count) {
        lsf_owned_entry_t entry = scope->entries[--scope->count];
        scope->entries[scope->count] = (lsf_owned_entry_t){0};
        scope->live -= entry.charge;
        entry.cleanup(entry.object);
    }
    lsf_require(scope->live == 0);
}

/* Zero bytes have no allocation and return NULL. Every nonzero allocation is
 * zero-initialized and charged before it is made visible. Arithmetic overflow,
 * scope exhaustion, byte-budget exhaustion and allocator failure return NULL. */
static inline void *lsf_scope_alloc(lsf_scope_t *scope, size_t count, size_t width) {
    if (!scope || !count || !width || count > SIZE_MAX / width ||
        scope->count >= LSF_SCOPE_CAPACITY || scope->live > scope->limit)
        return NULL;
    size_t size = count * width;
    if (size > scope->limit - scope->live) return NULL;
    void *object = calloc(count, width);
    if (!object) return NULL;
    if (!lsf_scope_adopt(scope, object, size, free)) {
        free(object);
        return NULL;
    }
    return object;
}

/* Volatile stores prevent dead-store elimination of this owner's wipe. Copies
 * made by the application are separate owners and must be wiped separately. */
static inline void lsf_zeroize(void *bytes, size_t length) {
    volatile unsigned char *p = (volatile unsigned char *)bytes;
    while (length--) *p++ = 0;
}

#endif
