/* SPDX-License-Identifier: Apache-2.0 */
#include "lsf/guest.h"

bool exports_examples_greeting_api_greet(probe_string_t *name, probe_string_t *out,
                                         exports_examples_greeting_api_error_t *error) {
    if (!name->len || memchr(name->ptr, 0, name->len)) {
        probe_string_free(name);
        error->tag = EXPORTS_EXAMPLES_GREETING_API_ERROR_INVALID_NAME;
        return false;
    }
    if (name->len > 128) {
        probe_string_free(name);
        error->tag = EXPORTS_EXAMPLES_GREETING_API_ERROR_TOO_LONG;
        return false;
    }
    lsf_scope_t scope;
    lsf_scope_init(&scope, 256);
    size_t length = 7 + name->len + 1;
    uint8_t *bytes = lsf_scope_alloc(&scope, length, 1);
    lsf_require(bytes != NULL);
    memcpy(bytes, "Hello, ", 7);
    memcpy(bytes + 7, name->ptr, name->len);
    bytes[length - 1] = '!';
    probe_string_free(name);
    *out = (probe_string_t){bytes, length};
    lsf_string_return(&scope, out);
    lsf_scope_close(&scope);
    return true;
}
