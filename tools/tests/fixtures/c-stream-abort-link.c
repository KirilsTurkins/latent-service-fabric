#include <stdint.h>
#include <stdlib.h>

static unsigned calls;
int32_t __imported_wasi_snapshot_preview1_random_get(int32_t pointer, int32_t length) {
    if (!pointer || length != 32) __builtin_trap();
    uint8_t *data = (uint8_t *)(uintptr_t)(uint32_t)pointer;
    for (int32_t i = 0; i < length; ++i) data[i] = (uint8_t)(i + 1);
    ++calls;
    return 0;
}

__attribute__((export_name("entropy_success"))) int entropy_success(void) {
    volatile uint32_t first = arc4random();
    volatile uint32_t second = arc4random();
    (void)first; (void)second;
    return calls == 1 ? 0 : 1;
}

__attribute__((export_name("application_abort"))) void application_abort(void) { abort(); }
_Noreturn void libc_abort(void) __asm__("abort");
__attribute__((export_name("original_libc_abort"))) void original_libc_abort(void) { libc_abort(); }
