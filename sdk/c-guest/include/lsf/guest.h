/* SPDX-License-Identifier: Apache-2.0 */
#ifndef LSF_GUEST_H
#define LSF_GUEST_H
#include "probe.h"
#include "ownership.h"

/* Borrowed literals are valid only while the generated call borrows them.
 * Never pass a literal to a generated *_free function or return it as owned. */
#define LSF_LITERAL(value) ((probe_string_t){(uint8_t *)(value), sizeof(value) - 1u})

static inline bool lsf_string_copy(lsf_scope_t *scope, probe_string_t *out,
                                   const uint8_t *bytes, size_t length) {
    if (!out || (length && !bytes)) return false;
    *out = (probe_string_t){0};
    if (!length) return true;
    uint8_t *copy = lsf_scope_alloc(scope, length, 1);
    if (!copy) return false;
    memcpy(copy, bytes, length);
    *out = (probe_string_t){copy, length};
    return true;
}

/* Transfer an owned allocation to the generated export post-return owner.
 * Empty strings need no allocation. The caller must not free the result. */
static inline void lsf_string_return(lsf_scope_t *scope, probe_string_t *value) {
    if (value->ptr) lsf_require(lsf_scope_detach(scope, value->ptr));
    else lsf_require(value->len == 0);
}

static inline void lsf_string_drop(void *value) {
    probe_string_t *string = value;
    probe_string_free(string);
    *string = (probe_string_t){0};
}
#endif
