/* SPDX-License-Identifier: Apache-2.0 */
#include "probe.h"
#include "lsf/ownership.h"

static uint32_t calls;
uint32_t exports_examples_recovery_api_run(uint32_t which) {
    if (which == 1) __builtin_trap();
    if (which == 2) {
        size_t previous = __builtin_wasm_memory_grow(0, 1024);
        lsf_require(previous != (size_t)-1);
    }
    if (which == 3) for (;;) __asm__ volatile("" ::: "memory");
    return ++calls;
}
