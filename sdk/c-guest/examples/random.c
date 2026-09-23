/* SPDX-License-Identifier: Apache-2.0 */
#include "lsf/guest.h"

uint64_t exports_tests_random_api_run(uint32_t which, probe_string_t *text,
                                     uint64_t handle) {
    (void)handle;
    probe_string_free(text);
    latent_random_random_random_error_t error = {0};
    if (which == 1) {
        uint64_t value;
        lsf_require(latent_random_random_u64_value(&value, &error));
        return 8;
    }
    lsf_require(which == 0 || which == 2);
    probe_list_u8_t bytes = {0};
    bool ok = latent_random_random_bytes(which == 0 ? 32 : UINT32_MAX, &bytes, &error);
    if (which == 2) {
        lsf_require(!ok && error.tag == LATENT_RANDOM_RANDOM_RANDOM_ERROR_INVALID_LENGTH);
        return 10;
    }
    lsf_require(ok && bytes.len == 32);
    uint64_t length = bytes.len;
    probe_list_u8_free(&bytes);
    return length;
}
