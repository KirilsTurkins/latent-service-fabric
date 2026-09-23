/* SPDX-License-Identifier: Apache-2.0 */
// lsf-example-begin: capsule
#include "lsf/text.h"

bool exports_examples_word_count_api_count(probe_string_t *text, uint32_t *value,
                                           probe_string_t *error) {
    if (text->len > 4096) {
        probe_string_free(text);
        lsf_text_error(error, "Use text of at most 4096 bytes.");
        return false;
    }
    uint32_t count = 0;
    bool in_word = false;
    size_t offset = 0;
    while (offset < text->len) {
        bool word = !lsf_text_whitespace(lsf_text_next(text, &offset));
        if (word && !in_word) ++count;
        in_word = word;
    }
    probe_string_free(text);
    *value = count;
    return true;
}
// lsf-example-end: capsule
