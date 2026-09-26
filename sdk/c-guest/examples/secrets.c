/* SPDX-License-Identifier: Apache-2.0 */
#include "lsf/secrets.h"

uint64_t exports_tests_local_secrets_api_run(uint32_t which, probe_string_t *text,
                                            uint64_t handle) {
    (void)which;
    (void)handle;
    lsf_secret_t secret = {0};
    latent_secrets_reader_secret_error_t error = {0};
    bool ok = lsf_secret_read(text, &secret, &error);
    probe_string_free(text);
    if (ok) {
        uint64_t length = lsf_secret_borrow(&secret)->bytes.len;
        lsf_secret_close(&secret);
        return length;
    }
    switch (error.tag) {
    case LATENT_SECRETS_READER_SECRET_ERROR_PERMISSION_DENIED: return 10;
    case LATENT_SECRETS_READER_SECRET_ERROR_NOT_FOUND: return 11;
    case LATENT_SECRETS_READER_SECRET_ERROR_EXPIRED: return 12;
    case LATENT_SECRETS_READER_SECRET_ERROR_UNAVAILABLE: return 13;
    default: __builtin_trap();
    }
}
