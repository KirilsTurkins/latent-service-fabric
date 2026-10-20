// Compiler-owned ports for the exact pinned System.Native entrypoints.
// Both require the application world to declare the existing RANDOM authority.
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <wasi/wasip2.h>

void __wrap_SystemNative_GetNonCryptographicallySecureRandomBytes(uint8_t *buffer, int32_t length) {
    if (length < 0 || length > 65536 || (length != 0 && buffer == 0))
        __builtin_trap();
    if (length == 0)
        return;
    wasip2_list_u8_t value = {0};
    random_insecure_get_insecure_random_bytes((uint64_t)length, &value);
    if (value.len != (size_t)length || value.ptr == 0)
        __builtin_trap();
    memcpy(buffer, value.ptr, (size_t)length);
    wasip2_list_u8_free(&value);
}

// Canonical result<u64, random-error>: one-byte discriminant, eight-byte
// aligned payload. Scalar owners retire after lowering; no guest list remains.
typedef struct {
    uint8_t tag;
    uint8_t padding[7];
    uint64_t value;
} lsf_random_u64_result;
_Static_assert(sizeof(lsf_random_u64_result) == 16, "random result size");
_Static_assert(offsetof(lsf_random_u64_result, value) == 8, "random result payload");
_Static_assert(_Alignof(lsf_random_u64_result) == 8, "random result alignment");

__attribute__((import_module("latent:random/random@0.1.0"), import_name("u64-value")))
extern void lsf_random_u64(lsf_random_u64_result *result);

// The pinned PAL ABI returns zero on success, -1 on failure. Its managed caller
// converts failure into CryptographicException. Never acknowledge partial data.
int32_t __wrap_SystemNative_GetCryptographicallySecureRandomBytes(uint8_t *buffer, int32_t length) {
    if (length < 0 || length > 65536 || (length != 0 && buffer == 0))
        return -1;
    for (int32_t offset = 0; offset < length;) {
        lsf_random_u64_result result = {0};
        lsf_random_u64(&result);
        if (result.tag != 0) {
            memset(buffer, 0, (size_t)length);
            return -1;
        }
        int32_t count = length - offset;
        if (count > 8) count = 8;
        // WebAssembly memory is little-endian; spelling out the byte order also
        // keeps the retained reference independent of the compiler host endian.
        for (int32_t index = 0; index < count; ++index)
            buffer[offset + index] = (uint8_t)(result.value >> (8 * index));
        offset += count;
    }
    return 0;
}
