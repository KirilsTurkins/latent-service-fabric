/* SPDX-License-Identifier: Apache-2.0 */
#ifndef LSF_GUEST_STREAMING_H
#define LSF_GUEST_STREAMING_H
#include "guest.h"
#include "resources.h"

LSF_RESOURCE_OWNER(lsf_upload, latent_http_streaming_own_upload_t,
    latent_http_streaming_borrow_upload_t, latent_http_streaming_borrow_upload,
    latent_http_streaming_upload_drop_own)
LSF_RESOURCE_OWNER(lsf_body, latent_http_streaming_own_body_t,
    latent_http_streaming_borrow_body_t, latent_http_streaming_borrow_body,
    latent_http_streaming_body_drop_own)
LSF_RESOURCE_OWNER(lsf_http_chunk, latent_http_streaming_own_chunk_t,
    latent_http_streaming_borrow_chunk_t, latent_http_streaming_borrow_chunk,
    latent_http_streaming_chunk_drop_own)

static inline void lsf_streaming_headers_close(latent_http_streaming_list_header_t *headers) {
    for (size_t i = 0; i < headers->len; ++i) {
        probe_string_free(&headers->ptr[i].name);
        probe_string_free(&headers->ptr[i].value);
    }
    if (headers->len) free(headers->ptr);
    *headers = (latent_http_streaming_list_header_t){0};
}

/* Metadata and the body are distinct owners. Move the returned body into an
 * lsf_body_t, then release metadata; this never releases a borrowed body. */
static inline void lsf_streaming_metadata_close(latent_http_streaming_response_t *response) {
    lsf_streaming_headers_close(&response->headers);
    if (response->body_media_type.is_some)
        probe_string_free(&response->body_media_type.val);
    response->body_media_type = (probe_option_string_t){0};
}
#endif
