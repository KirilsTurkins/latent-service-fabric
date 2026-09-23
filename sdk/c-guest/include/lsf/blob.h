/* SPDX-License-Identifier: Apache-2.0 */
#ifndef LSF_GUEST_BLOB_H
#define LSF_GUEST_BLOB_H
#include "guest.h"
#include "resources.h"
LSF_RESOURCE_OWNER(lsf_blob_chunk, latent_blob_blob_own_chunk_t,
    latent_blob_blob_borrow_chunk_t, latent_blob_blob_borrow_chunk,
    latent_blob_blob_chunk_drop_own)

/* Blob reader/writer handles are WIT u64 values, not chunk resources. Explicit
 * async close/seal must complete before releasing request/result storage.
 * Abandonment leaves their budget charged until host activation cleanup. */
static inline void lsf_blob_reference_close(void *object) {
    latent_blob_blob_blob_reference_t *reference = object;
    if (!reference) return;
    probe_string_free(&reference->digest);
    probe_string_free(&reference->media_type);
    *reference = (latent_blob_blob_blob_reference_t){0};
}
#endif
