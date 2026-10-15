/* SPDX-License-Identifier: Apache-2.0 */
#include "probe.h"
#include <errno.h>
#include <stdint.h>
#include <string.h>
#include <wasi/api.h>

static int valid_range(const void *pointer, uint32_t size) {
    uint64_t memory = (uint64_t)__builtin_wasm_memory_size(0) * 65536;
    uint64_t address = (uintptr_t)pointer;
    return (address != 0 || size == 0) && address <= memory && size <= memory - address;
}

int32_t __imported_wasi_snapshot_preview1_clock_time_get(int32_t id, int64_t precision, int32_t address) {
    __wasi_timestamp_t *output = (__wasi_timestamp_t *)(uintptr_t)(uint32_t)address;
    (void)precision;
    if (!valid_range(output, sizeof(*output))) return __WASI_ERRNO_FAULT;
    if (id == __WASI_CLOCKID_MONOTONIC) {
        uint64_t nanos = latent_clock_monotonic_now_nanos();
        memcpy(output, &nanos, sizeof(nanos));
        return 0;
    }
    if (id == __WASI_CLOCKID_REALTIME) {
        uint64_t millis = latent_clock_wall_now_unix_millis();
        if (millis > UINT64_MAX / 1000000) return __WASI_ERRNO_OVERFLOW;
        uint64_t nanos = millis * 1000000;
        memcpy(output, &nanos, sizeof(nanos));
        return 0;
    }
    return __WASI_ERRNO_NOTSUP;
}

int32_t __imported_wasi_snapshot_preview1_clock_res_get(int32_t id, int32_t address) {
    __wasi_timestamp_t *output = (__wasi_timestamp_t *)(uintptr_t)(uint32_t)address;
    if (!valid_range(output, sizeof(*output))) return __WASI_ERRNO_FAULT;
    if (id != __WASI_CLOCKID_REALTIME) return __WASI_ERRNO_NOTSUP;
    uint64_t nanos = 1000000;
    memcpy(output, &nanos, sizeof(nanos));
    return 0;
}

int32_t __imported_wasi_snapshot_preview1_random_get(int32_t address, int32_t requested) {
    uint8_t *buffer = (uint8_t *)(uintptr_t)(uint32_t)address;
    uint32_t length = (uint32_t)requested;
    if (length > 4096) return __WASI_ERRNO_INVAL;
    if (length == 0) return 0;
    if (!valid_range(buffer, length)) return __WASI_ERRNO_FAULT;
    latent_random_random_random_error_t error = {0};
    probe_list_u8_t result = {0};
    if (!latent_random_random_bytes(length, &result, &error)) {
        if (error.tag == LATENT_RANDOM_RANDOM_RANDOM_ERROR_INVALID_LENGTH) return __WASI_ERRNO_INVAL;
        if (error.tag == LATENT_RANDOM_RANDOM_RANDOM_ERROR_BUDGET_EXHAUSTED) return __WASI_ERRNO_AGAIN;
        return __WASI_ERRNO_IO;
    }
    int valid = result.len == length && result.ptr != NULL;
    if (valid) memcpy(buffer, result.ptr, length);
    probe_list_u8_free(&result);
    return valid ? 0 : __WASI_ERRNO_IO;
}
