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

/* Returns a borrow, not a copy or a transferable owner. */
static inline const latent_secrets_reader_secret_value_t *lsf_secret_borrow(
    const lsf_secret_t *secret) {
    lsf_require(secret && secret->owned);
    return &secret->value;
}

static inline void lsf_secret_close(void *object) {
    lsf_secret_t *secret = object;
    if (!secret || !secret->owned) return;
    lsf_zeroize(secret->value.bytes.ptr, secret->value.bytes.len);
    latent_secrets_reader_secret_value_free(&secret->value);
    *secret = (lsf_secret_t){0};
}
#endif
