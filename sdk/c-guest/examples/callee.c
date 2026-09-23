/* SPDX-License-Identifier: Apache-2.0 */
#include "lsf/guest.h"

uint32_t exports_tests_local_api_answer(void) { return 42; }

bool exports_tests_local_api_fail(uint32_t *value, probe_string_t *error) {
    (void)value;
    lsf_scope_t scope;
    lsf_scope_init(&scope, 128);
    static const uint8_t message[] = "declared application failure";
    lsf_require(lsf_string_copy(&scope, error, message, sizeof(message) - 1));
    lsf_string_return(&scope, error);
    lsf_scope_close(&scope);
    return false;
}

uint32_t exports_tests_local_api_spin(void) {
    for (;;) __asm__ volatile("" ::: "memory");
}
