/* SPDX-License-Identifier: Apache-2.0 */
#ifndef LSF_GUEST_TEXT_H
#define LSF_GUEST_TEXT_H
#include "guest.h"

/* Canonical WIT strings are UTF-8. Decode scalars rather than applying the
 * process locale or counting bytes as letters. No locale/runtime is retained. */
static inline uint32_t lsf_text_next(const probe_string_t *text, size_t *offset) {
    lsf_require(*offset < text->len);
    uint8_t lead = text->ptr[(*offset)++];
    if (lead < 0x80) return lead;
    size_t extra = lead < 0xE0 ? 1 : lead < 0xF0 ? 2 : 3;
    uint32_t value = lead & (extra == 1 ? 0x1F : extra == 2 ? 0x0F : 0x07);
    lsf_require(extra <= text->len - *offset);
    while (extra--) {
        uint8_t byte = text->ptr[(*offset)++];
        lsf_require((byte & 0xC0) == 0x80);
        value = (value << 6) | (byte & 0x3F);
    }
    return value;
}

/* Unicode White_Space, matching Rust str::trim/split_whitespace. */
static inline bool lsf_text_whitespace(uint32_t value) {
    return (value >= 9 && value <= 13) || value == 0x20 || value == 0x85 ||
        value == 0xA0 || value == 0x1680 || (value >= 0x2000 && value <= 0x200A) ||
        value == 0x2028 || value == 0x2029 || value == 0x202F || value == 0x205F || value == 0x3000;
}

static inline void lsf_text_error(probe_string_t *error, const char *message) {
    lsf_scope_t scope;
    lsf_scope_init(&scope, 256);
    lsf_require(lsf_string_copy(&scope, error, (const uint8_t *)message, strlen(message)));
    lsf_string_return(&scope, error);
    lsf_scope_close(&scope);
}
#endif
