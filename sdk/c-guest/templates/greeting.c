/* SPDX-License-Identifier: Apache-2.0 */
// lsf-example-begin: capsule
#include "lsf/text.h"

bool exports_examples_greeting_api_greet(probe_string_t *name, probe_string_t *value,
                                         probe_string_t *error) {
    size_t first = name->len, end = 0, offset = 0;
    while (offset < name->len) {
        size_t start = offset;
        if (!lsf_text_whitespace(lsf_text_next(name, &offset))) {
            if (first == name->len) first = start;
            end = offset;
        }
    }
    const char *failure = first == name->len ? "Please enter a name." :
        end - first > 100 ? "Use a name of at most 100 bytes." : NULL;
    if (failure) {
        probe_string_free(name);
        lsf_text_error(error, failure);
        return false;
    }
    lsf_scope_t scope;
    lsf_scope_init(&scope, 128);
    size_t length = end - first;
    uint8_t *bytes = lsf_scope_alloc(&scope, length + 8, 1);
    lsf_require(bytes != NULL);
    memcpy(bytes, "Hello, ", 7);
    memcpy(bytes + 7, name->ptr + first, length);
    bytes[length + 7] = '!';
    probe_string_free(name);
    *value = (probe_string_t){bytes, length + 8};
    lsf_string_return(&scope, value);
    lsf_scope_close(&scope);
    return true;
}
// lsf-example-end: capsule
