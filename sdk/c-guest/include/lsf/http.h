/* SPDX-License-Identifier: Apache-2.0 */
#ifndef LSF_GUEST_HTTP_H
#define LSF_GUEST_HTTP_H
#include "guest.h"

/* Do not use a generated aggregate free as a recursive-ownership contract:
 * the pinned generator can omit aliased nested list/option allocations. */
static inline void lsf_http_response_close(void *object) {
    latent_http_client_response_t *response = object;
    if (!response) return;
    for (size_t i = 0; i < response->headers.len; ++i) {
        probe_string_free(&response->headers.ptr[i].name);
        probe_string_free(&response->headers.ptr[i].value);
    }
    if (response->headers.len) free(response->headers.ptr);
    if (response->body.len) free(response->body.ptr);
    if (response->body_media_type.is_some)
        probe_string_free(&response->body_media_type.val);
    *response = (latent_http_client_response_t){0};
}
#endif
