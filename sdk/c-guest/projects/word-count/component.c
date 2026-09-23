/* SPDX-License-Identifier: Apache-2.0 */
#include "lsf/guest.h"

bool exports_examples_word_count_api_count(probe_string_t *text, uint64_t *out,
                                           exports_examples_word_count_api_error_t *error) {
    if (text->len > 4096) {
        probe_string_free(text);
        error->tag = EXPORTS_EXAMPLES_WORD_COUNT_API_ERROR_TOO_LONG;
        return false;
    }
    if (text->len && memchr(text->ptr, 0, text->len)) {
        probe_string_free(text);
        error->tag = EXPORTS_EXAMPLES_WORD_COUNT_API_ERROR_INVALID_TEXT;
        return false;
    }
    uint64_t count = 0;
    bool word = false;
    for (size_t i = 0; i < text->len; ++i) {
        uint8_t byte = text->ptr[i];
        bool space = byte == ' ' || (byte >= '\t' && byte <= '\r');
        if (!space && !word) ++count;
        word = !space;
    }
    probe_string_free(text);
    *out = count;
    return true;
}
