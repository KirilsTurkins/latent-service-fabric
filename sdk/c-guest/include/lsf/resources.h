/* SPDX-License-Identifier: Apache-2.0 */
#ifndef LSF_GUEST_RESOURCES_H
#define LSF_GUEST_RESOURCES_H
#include "ownership.h"

/* C cannot prohibit struct copies. These guards are unique owners: do not
 * copy them after adoption. Adopt only resources returned by the host. Move
 * consumes the guard before a generated consuming import is called. Borrow
 * remains valid only while the guard and pending call both remain alive.
 * The host still validates every handle; these helpers grant no authority. */
#define LSF_RESOURCE_OWNER(NAME, OWN, BORROW, BORROW_FN, DROP_FN) \
    typedef struct { OWN value; bool owned; } NAME##_t; \
    static inline void NAME##_adopt(NAME##_t *owner, OWN value) { \
        lsf_require(owner && !owner->owned); \
        owner->value = value; owner->owned = true; \
    } \
    static inline BORROW NAME##_borrow(const NAME##_t *owner) { \
        lsf_require(owner && owner->owned); return BORROW_FN(owner->value); \
    } \
    static inline OWN NAME##_move(NAME##_t *owner) { \
        lsf_require(owner && owner->owned); \
        OWN value = owner->value; *owner = (NAME##_t){0}; return value; \
    } \
    static inline void NAME##_close(void *object) { \
        NAME##_t *owner = object; \
        if (owner && owner->owned) { \
            OWN value = NAME##_move(owner); DROP_FN(value); \
        } \
    }
#endif
