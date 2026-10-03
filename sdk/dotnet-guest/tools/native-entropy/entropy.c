// The exact pinned System.Native noncryptographic entrypoint only. Secure
// random functions retain their upstream implementation and closed denial.
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
