/* SPDX-License-Identifier: Apache-2.0 */
#include "probe.h"
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <wasi/api.h>

#define LSF_STDIO_MAX_IOVECS 16u
#define LSF_STDIO_MAX_BYTES 4096u

__attribute__((constructor)) static void initialize_standard_stdio(void) {
    if (setvbuf(stdout, NULL, _IONBF, 0) || setvbuf(stderr, NULL, _IONBF, 0)) __builtin_trap();
}

static int valid_range(const void *pointer, uint32_t size) {
    uint64_t memory = (uint64_t)__builtin_wasm_memory_size(0) * 65536;
    uint64_t address = (uintptr_t)pointer;
    return (address != 0 || size == 0) && address <= memory && size <= memory - address;
}

static int valid_utf8(const uint8_t *bytes, uint32_t length) {
    uint32_t offset = 0;
    while (offset < length) {
        uint8_t lead = bytes[offset++];
        if (lead < 0x80) continue;
        uint32_t scalar, count, minimum;
        if (lead >= 0xc2 && lead <= 0xdf) { scalar = lead & 0x1f; count = 1; minimum = 0x80; }
        else if (lead >= 0xe0 && lead <= 0xef) { scalar = lead & 0x0f; count = 2; minimum = 0x800; }
        else if (lead >= 0xf0 && lead <= 0xf4) { scalar = lead & 7; count = 3; minimum = 0x10000; }
        else return 0;
        if (count > length - offset) return 0;
        while (count--) {
            uint8_t next = bytes[offset++];
            if ((next & 0xc0) != 0x80) return 0;
            scalar = (scalar << 6) | (next & 0x3f);
        }
        if (scalar < minimum || scalar > 0x10ffff || (scalar >= 0xd800 && scalar <= 0xdfff)) return 0;
    }
    return 1;
}

int32_t __imported_wasi_snapshot_preview1_fd_write(int32_t fd, int32_t address, int32_t count, int32_t written_address) {
    const __wasi_ciovec_t *vectors = (const __wasi_ciovec_t *)(uintptr_t)(uint32_t)address;
    __wasi_size_t *written = (__wasi_size_t *)(uintptr_t)(uint32_t)written_address;
    uint32_t length = (uint32_t)count;
    if (fd != 1 && fd != 2) return __WASI_ERRNO_BADF;
    if (length > LSF_STDIO_MAX_IOVECS) return __WASI_ERRNO_INVAL;
    if (!valid_range(written, sizeof(*written)) || !valid_range(vectors, length * sizeof(*vectors)))
        return __WASI_ERRNO_FAULT;
    uint8_t message[LSF_STDIO_MAX_BYTES];
    uint32_t total = 0;
    for (uint32_t i = 0; i < length; ++i) {
        __wasi_ciovec_t vector;
        memcpy(&vector, (const uint8_t *)vectors + i * sizeof(vector), sizeof(vector));
        if (vector.buf_len > LSF_STDIO_MAX_BYTES - total) return __WASI_ERRNO_INVAL;
        if (!valid_range(vector.buf, vector.buf_len)) return __WASI_ERRNO_FAULT;
        if (vector.buf_len) memcpy(message + total, vector.buf, vector.buf_len);
        total += vector.buf_len;
    }
    if (!valid_utf8(message, total)) return __WASI_ERRNO_ILSEQ;
    if (total) {
        probe_string_t borrowed = {.ptr = message, .len = total};
        latent_log_log_list_field_t fields = {0};
        latent_log_log_log_error_t error = {0};
        bool accepted = false;
        if (!latent_log_log_write(fd == 1 ? LATENT_LOG_LOG_LEVEL_INFO : LATENT_LOG_LOG_LEVEL_ERROR,
                                  &borrowed, &fields, &accepted, &error)) {
            uint8_t tag = error.tag;
            latent_log_log_log_error_free(&error);
            if (tag == LATENT_LOG_LOG_LOG_ERROR_BUDGET_EXHAUSTED) return __WASI_ERRNO_AGAIN;
            if (tag == LATENT_LOG_LOG_LOG_ERROR_INVALID_FIELD) return __WASI_ERRNO_INVAL;
            return __WASI_ERRNO_IO;
        }
        if (!accepted) return __WASI_ERRNO_IO;
    }
    __wasi_size_t result = total;
    memcpy(written, &result, sizeof(result));
    return 0;
}

int32_t __imported_wasi_snapshot_preview1_fd_fdstat_get(int32_t fd, int32_t address) {
    __wasi_fdstat_t *output = (__wasi_fdstat_t *)(uintptr_t)(uint32_t)address;
    if (fd != 1 && fd != 2) return __WASI_ERRNO_BADF;
    if (!valid_range(output, sizeof(*output))) return __WASI_ERRNO_FAULT;
    __wasi_fdstat_t value = {0};
    value.fs_filetype = __WASI_FILETYPE_UNKNOWN;
    value.fs_rights_base = __WASI_RIGHTS_FD_WRITE;
    memcpy(output, &value, sizeof(value));
    return 0;
}

int32_t __imported_wasi_snapshot_preview1_fd_seek(int32_t fd, int64_t offset, int32_t whence, int32_t output) {
    (void)offset; (void)whence; (void)output;
    return fd == 1 || fd == 2 ? __WASI_ERRNO_NOTSUP : __WASI_ERRNO_BADF;
}

int32_t __imported_wasi_snapshot_preview1_fd_close(int32_t fd) {
    return fd == 1 || fd == 2 ? __WASI_ERRNO_NOTSUP : __WASI_ERRNO_BADF;
}
