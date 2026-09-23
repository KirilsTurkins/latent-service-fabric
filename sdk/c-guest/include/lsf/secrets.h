/* SPDX-License-Identifier: Apache-2.0 */
#ifndef LSF_GUEST_SECRETS_H
#define LSF_GUEST_SECRETS_H
/* Include only in a world importing latent:secrets/reader@0.1.0. */
#include "guest.h"

typedef struct {
    latent_secrets_reader_secret_value_t value;
    bool owned;
} lsf_secret_t;

static inline bool lsf_secret_read(probe_string_t *reference, lsf_secret_t *secret,
                                   latent_secrets_reader_secret_error_t *error) {
    lsf_require(secret && !secret->owned);
    secret->value = (latent_secrets_reader_secret_value_t){0};
    secret->owned = latent_secrets_reader_read(reference, &secret->value, error);
    return secret->owned;
}

static inline const latent_secrets_reader_secret_value_t *lsf_secret_borrow(
    const lsf_secret_t *secret) {
    lsf_require(secret && secret->owned);
    return &secret->value;
}

/* Wipe before deallocation. Explicitly visit aliased nested values rather
 * than relying on the pinned generator's aggregate *_free implementation. */
static inline void lsf_secret_close(void *object) {
    lsf_secret_t *secret = object;
    if (!secret || !secret->owned) return;
    lsf_zeroize(secret->value.bytes.ptr, secret->value.bytes.len);
    if (secret->value.bytes.len) free(secret->value.bytes.ptr);
    probe_string_free(&secret->value.media_type);
    if (secret->value.version.is_some) probe_string_free(&secret->value.version.val);
    *secret = (lsf_secret_t){0};
}
#endif
